"""OHLCV batch downloader and SQLite cache for momentum scanning.

Stores price history and scan state in SQLite at .valuation/data/momentum/radar.db.
Supports incremental updates (only fetches rows newer than latest cached date).
"""

import logging
import sqlite3
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(".valuation/data/momentum/radar.db")

# yfinance batch settings
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

CREATE TABLE IF NOT EXISTS scan_state (
    ticker TEXT PRIMARY KEY,
    tier INTEGER,
    composite_score REAL,
    weeks_on_list INTEGER DEFAULT 0,
    first_seen TEXT,
    last_seen TEXT,
    fip_score REAL,
    return_12m REAL,
    obv_trend INTEGER,
    rel_strength REAL
);

CREATE TABLE IF NOT EXISTS fallen_angels (
    ticker TEXT PRIMARY KEY,
    drawdown_pct REAL,
    f_score INTEGER,
    z_score REAL,
    fcf_positive INTEGER,
    weeks_on_list INTEGER DEFAULT 0,
    first_seen TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS new_highs_tracker (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker ON ohlcv(ticker);
CREATE INDEX IF NOT EXISTS idx_ohlcv_date ON ohlcv(date);
CREATE INDEX IF NOT EXISTS idx_new_highs_date ON new_highs_tracker(date);
"""


class MomentumDataStore:
    """SQLite-backed price history and scan state store."""

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
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Add columns for stage detection (v2) if missing."""
        conn = self._get_conn()
        cursor = conn.execute("PRAGMA table_info(scan_state)")
        existing = {row[1] for row in cursor.fetchall()}
        migrations = [
            # Stage detection (v2)
            ("acceleration", "REAL"),
            ("freshness", "TEXT"),
            ("stage", "TEXT DEFAULT 'MID'"),
            ("ma_slope_200d", "REAL"),
            # Fundamental enrichment (v3)
            ("revision_score", "REAL"),
            ("buy_pct", "REAL"),
            ("earnings_growth", "REAL"),
            ("forward_pe", "REAL"),
            ("fcf_yield", "REAL"),
            ("short_pct", "REAL"),
            ("piotroski_f", "INTEGER"),
        ]
        for col, col_type in migrations:
            if col not in existing:
                conn.execute(f"ALTER TABLE scan_state ADD COLUMN {col} {col_type}")
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __repr__(self) -> str:
        return f"MomentumDataStore(db_path={self.db_path!r})"

    # ─── OHLCV operations ───

    def fetch_ohlcv(
        self,
        tickers: list[str],
        period: str = "1y",
    ) -> dict[str, pd.DataFrame]:
        """Batch-download OHLCV via yfinance and upsert into SQLite.

        Downloads in chunks of 80 with 2s delays to avoid rate limits.
        Only inserts rows newer than the latest cached date per ticker.

        Returns:
            Dict mapping ticker → DataFrame with columns [Open, High, Low, Close, Volume].
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

            # Handle single-ticker case: yfinance still returns MultiIndex columns
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

        # Fall back to SQLite cache for tickers that failed to download.
        # This prevents non-deterministic results when yfinance drops
        # tickers due to rate limits or network hiccups.
        missing = set(tickers) - set(result.keys())
        cache_hits = 0
        for ticker in missing:
            cached = self.load_cached_ohlcv(ticker, days=760)  # ~25 months
            if cached is not None and not cached.empty:
                result[ticker] = cached
                cache_hits += 1
        if cache_hits:
            logger.info(
                "Cache fallback: %d tickers recovered from SQLite", cache_hits,
            )

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

    def load_cached_ohlcv(self, ticker: str, days: int = 252) -> pd.DataFrame | None:
        """Read last N days of OHLCV from SQLite cache.

        Returns:
            DataFrame with columns [Open, High, Low, Close, Volume] indexed by date,
            or None if no data cached.
        """
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
        """Return list of all tickers with cached OHLCV data."""
        conn = self._get_conn()
        rows = conn.execute("SELECT DISTINCT ticker FROM ohlcv").fetchall()
        return [r["ticker"] for r in rows]

    # ─── Scan state operations ───

    def load_scan_state(self) -> dict[str, dict]:
        """Load all scan_state records as ticker → dict."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM scan_state").fetchall()
        return {r["ticker"]: dict(r) for r in rows}

    def save_scan_state(self, entries: list[dict]) -> None:
        """Upsert scan_state entries (list of dicts with 'ticker' key)."""
        conn = self._get_conn()
        for entry in entries:
            conn.execute(
                "INSERT OR REPLACE INTO scan_state "
                "(ticker, tier, composite_score, weeks_on_list, first_seen, last_seen, "
                "fip_score, return_12m, obv_trend, rel_strength, "
                "acceleration, freshness, stage, ma_slope_200d, "
                "revision_score, buy_pct, earnings_growth, "
                "forward_pe, fcf_yield, short_pct, piotroski_f) "
                "VALUES (:ticker, :tier, :composite_score, :weeks_on_list, "
                ":first_seen, :last_seen, :fip_score, :return_12m, :obv_trend, :rel_strength, "
                ":acceleration, :freshness, :stage, :ma_slope_200d, "
                ":revision_score, :buy_pct, :earnings_growth, "
                ":forward_pe, :fcf_yield, :short_pct, :piotroski_f)",
                entry,
            )
        conn.commit()

    def clear_scan_state(self) -> None:
        """Clear all scan_state records (for fresh scan)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM scan_state")
        conn.commit()

    # ─── Fallen angels state ───

    def load_fallen_angels_state(self) -> dict[str, dict]:
        """Load all fallen_angels records as ticker → dict."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM fallen_angels").fetchall()
        return {r["ticker"]: dict(r) for r in rows}

    def save_fallen_angels_state(self, entries: list[dict]) -> None:
        """Upsert fallen_angels entries."""
        conn = self._get_conn()
        for entry in entries:
            conn.execute(
                "INSERT OR REPLACE INTO fallen_angels "
                "(ticker, drawdown_pct, f_score, z_score, fcf_positive, "
                "weeks_on_list, first_seen, last_seen) "
                "VALUES (:ticker, :drawdown_pct, :f_score, :z_score, :fcf_positive, "
                ":weeks_on_list, :first_seen, :last_seen)",
                entry,
            )
        conn.commit()

    # ─── New highs tracker ───

    def record_new_high(self, ticker: str, date: str) -> None:
        """Record a new 52-week high occurrence."""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO new_highs_tracker (ticker, date) VALUES (?, ?)",
            (ticker, date),
        )
        conn.commit()

    def count_new_highs(self, ticker: str, lookback_trading_days: int = 20) -> int:
        """Count new 52-week high occurrences in the last N trading days.

        Uses calendar_days = trading_days * 1.5 to account for weekends/holidays.
        """
        calendar_days = int(lookback_trading_days * 1.5)
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM new_highs_tracker "
            "WHERE ticker = ? AND date >= date('now', ? || ' days')",
            (ticker, -calendar_days),
        ).fetchone()
        return row["cnt"] if row else 0
