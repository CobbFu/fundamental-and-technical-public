"""OHLCV batch downloader and SQLite cache for the early-stage scanner.

Stores price history and early-scan state in SQLite at .valuation/data/early/early.db.
Mirrors src/cascade/data.py and src/momentum/data.py: WAL mode, batch upsert,
and a cache fallback so a wide universe survives yfinance rate-limit dropouts.
"""

import logging
import sqlite3
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(".valuation/data/early/early.db")

# yfinance batch settings — wide universe (~1500), so cache fallback matters
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

CREATE TABLE IF NOT EXISTS early_state (
    ticker TEXT PRIMARY KEY,
    early_score REAL,
    stage TEXT,
    trailing_12m REAL,
    dist_from_base REAL,
    market_cap_b REAL,
    revision_score REAL,
    growth_est REAL,
    cohort TEXT,
    accumulation REAL,
    rs_turn INTEGER,
    vol_contraction REAL,
    recency TEXT,
    weeks_on_list INTEGER DEFAULT 0,
    first_seen TEXT,
    last_seen TEXT
);

CREATE INDEX IF NOT EXISTS idx_early_ohlcv_ticker ON ohlcv(ticker);
CREATE INDEX IF NOT EXISTS idx_early_ohlcv_date ON ohlcv(date);
"""


class EarlyDataStore:
    """SQLite-backed price history and early-scan state store."""

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            db_path = DEFAULT_DB_PATH
        self.db_path: str | Path
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
        return f"EarlyDataStore(db_path={self.db_path!r})"

    # ─── OHLCV operations ───

    def fetch_ohlcv(
        self,
        tickers: list[str],
        period: str = "3y",
    ) -> dict[str, pd.DataFrame]:
        """Batch-download OHLCV via yfinance and upsert into SQLite.

        Downloads in chunks of 80 with 2s delays. Tickers that fail to download
        (rate limits / network) fall back to the SQLite cache so a wide-universe
        scan stays deterministic.

        Returns:
            Dict mapping ticker -> DataFrame [Open, High, Low, Close, Volume].
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

        # Cache fallback for tickers that failed to download (~3y ≈ 760 days).
        missing = set(tickers) - set(result.keys())
        cache_hits = 0
        for ticker in missing:
            cached = self.load_cached_ohlcv(ticker, days=760)
            if cached is not None and not cached.empty:
                result[ticker] = cached
                cache_hits += 1
        if cache_hits:
            logger.info("Cache fallback: %d tickers recovered from SQLite", cache_hits)

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

    def load_cached_ohlcv(self, ticker: str, days: int = 760) -> pd.DataFrame | None:
        """Read last N days of OHLCV from SQLite cache (ascending by date)."""
        conn = self._get_conn()
        query = (
            "SELECT date, open, high, low, close, volume FROM ohlcv "
            "WHERE ticker = ? ORDER BY date DESC LIMIT ?"
        )
        rows = conn.execute(query, (ticker, days)).fetchall()
        if not rows:
            return None

        df = pd.DataFrame(
            [dict(r) for r in rows],
            columns=["date", "open", "high", "low", "close", "volume"],
        )
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df.columns = ["Open", "High", "Low", "Close", "Volume"]
        return df

    def load_all_cached_tickers(self) -> list[str]:
        """Return all tickers with cached OHLCV data."""
        conn = self._get_conn()
        rows = conn.execute("SELECT DISTINCT ticker FROM ohlcv").fetchall()
        return [r["ticker"] for r in rows]

    # ─── Early-scan state operations ───

    def load_early_state(self) -> dict[str, dict]:
        """Load all early_state records as ticker -> dict."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM early_state").fetchall()
        return {r["ticker"]: dict(r) for r in rows}

    def save_early_state(self, entries: list[dict]) -> None:
        """Upsert early_state entries (list of dicts with a 'ticker' key)."""
        conn = self._get_conn()
        for entry in entries:
            conn.execute(
                "INSERT OR REPLACE INTO early_state "
                "(ticker, early_score, stage, trailing_12m, dist_from_base, market_cap_b, "
                "revision_score, growth_est, cohort, accumulation, rs_turn, vol_contraction, "
                "recency, weeks_on_list, first_seen, last_seen) "
                "VALUES (:ticker, :early_score, :stage, :trailing_12m, :dist_from_base, "
                ":market_cap_b, :revision_score, :growth_est, :cohort, :accumulation, "
                ":rs_turn, :vol_contraction, :recency, :weeks_on_list, :first_seen, :last_seen)",
                entry,
            )
        conn.commit()

    def clear_early_state(self) -> None:
        """Clear all early_state records (for a fresh scan)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM early_state")
        conn.commit()
