"""OHLCV batch downloader and SQLite cache for cascade monitoring.

Stores price history and cascade state in SQLite at .valuation/data/cascade/monitor.db.
Mirrors src/momentum/data.py pattern: WAL mode, schema migration, batch upsert.
"""

import logging
import sqlite3
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(".valuation/data/cascade/monitor.db")

# yfinance batch settings — cascade has ~44 tickers, fits in 1 batch
BATCH_SIZE = 80
BATCH_DELAY_SECONDS = 2

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ohlcv (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS cascade_state (
    ticker TEXT PRIMARY KEY,
    return_3m REAL,
    volume_ratio REAL,
    dist_52w_high REAL,
    rel_strength REAL,
    base_status TEXT,
    above_50d_ma INTEGER,
    last_seen TEXT
);

CREATE INDEX IF NOT EXISTS idx_cascade_ohlcv_ticker ON ohlcv(ticker);
CREATE INDEX IF NOT EXISTS idx_cascade_ohlcv_date ON ohlcv(date);
"""


class CascadeDataStore:
    """SQLite-backed price history and cascade state store."""

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = DEFAULT_DB_PATH
        if str(db_path) == ":memory:":
            self.db_path = ":memory:"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn: sqlite3.Connection | None = None
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __repr__(self) -> str:
        return f"CascadeDataStore(db_path={self.db_path!r})"

    # ─── OHLCV operations ───

    def fetch_ohlcv(
        self,
        tickers: list[str],
        period: str = "1y",
    ) -> dict[str, pd.DataFrame]:
        """Batch-download OHLCV via yfinance and upsert into SQLite.

        Same logic as MomentumDataStore.fetch_ohlcv — downloads in chunks
        of 80 with 2s delays.
        """
        result: dict[str, pd.DataFrame] = {}
        total = len(tickers)
        chunks = [tickers[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]

        for chunk_idx, chunk in enumerate(chunks):
            if chunk_idx > 0:
                time.sleep(BATCH_DELAY_SECONDS)

            logger.info(
                "Downloading OHLCV chunk %d/%d (%d tickers)",
                chunk_idx + 1, len(chunks), len(chunk),
            )

            try:
                data = yf.download(
                    chunk,
                    period=period,
                    group_by="ticker",
                    progress=False,
                    threads=True,
                )
            except Exception as e:
                logger.warning("yfinance download failed for chunk %d: %s", chunk_idx + 1, e)
                continue

            if data.empty:
                continue

            if len(chunk) == 1:
                ticker = chunk[0]
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        df = data[ticker][["Open", "High", "Low", "Close", "Volume"]].copy()
                    else:
                        df = data[["Open", "High", "Low", "Close", "Volume"]].copy()
                    df.dropna(subset=["Close"], inplace=True)
                    if not df.empty:
                        self._upsert_ohlcv(ticker, df)
                        result[ticker] = df
                except (KeyError, TypeError):
                    logger.debug("No data for %s", ticker)
            else:
                for ticker in chunk:
                    try:
                        if ticker not in data.columns.get_level_values(0):
                            continue
                        df = data[ticker][["Open", "High", "Low", "Close", "Volume"]].copy()
                        df.dropna(subset=["Close"], inplace=True)
                        if not df.empty:
                            self._upsert_ohlcv(ticker, df)
                            result[ticker] = df
                    except (KeyError, TypeError):
                        logger.debug("No data for %s in chunk %d", ticker, chunk_idx + 1)

        logger.info("Fetched OHLCV for %d / %d tickers", len(result), total)
        return result

    def _upsert_ohlcv(self, ticker: str, df: pd.DataFrame) -> None:
        """Insert OHLCV rows, skipping duplicates (INSERT OR IGNORE)."""
        conn = self._get_conn()
        rows = [
            (
                ticker,
                idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
                float(row["Open"]) if pd.notna(row["Open"]) else None,
                float(row["High"]) if pd.notna(row["High"]) else None,
                float(row["Low"]) if pd.notna(row["Low"]) else None,
                float(row["Close"]) if pd.notna(row["Close"]) else None,
                int(row["Volume"]) if pd.notna(row["Volume"]) else None,
            )
            for idx, row in df.iterrows()
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO ohlcv (ticker, date, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()

    # ─── Cascade state operations ───

    def load_cascade_state(self) -> dict[str, dict]:
        """Load all cascade_state records as ticker -> dict."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM cascade_state").fetchall()
        return {r["ticker"]: dict(r) for r in rows}

    def save_cascade_state(self, entries: list[dict]) -> None:
        """Upsert cascade_state entries."""
        conn = self._get_conn()
        for entry in entries:
            conn.execute(
                "INSERT OR REPLACE INTO cascade_state "
                "(ticker, return_3m, volume_ratio, dist_52w_high, rel_strength, "
                "base_status, above_50d_ma, last_seen) "
                "VALUES (:ticker, :return_3m, :volume_ratio, :dist_52w_high, :rel_strength, "
                ":base_status, :above_50d_ma, :last_seen)",
                entry,
            )
        conn.commit()
