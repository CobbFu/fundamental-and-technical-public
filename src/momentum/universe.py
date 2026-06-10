"""Universe management for momentum scanning — US + European stocks.

US: S&P 500 + S&P 400 from Wikipedia (~900 tickers).
Europe: 14+ Wikipedia indices covering STOXX 600 equivalent (~500 tickers).
Fallback: SEC EDGAR company_tickers_exchange.json (~7,500 NYSE/NASDAQ).
Results are cached to disk with a 7-day TTL per region.

Wikipedia tables also provide company name and GICS sector, which are
cached alongside tickers to eliminate per-ticker yfinance .info calls.
"""

import json
import logging
import time
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(".valuation/data/momentum")
UNIVERSE_CACHE = CACHE_DIR / "universe.json"
WIDE_CACHE = CACHE_DIR / "universe_wide.json"
EU_CACHE = CACHE_DIR / "universe_eu.json"
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days

_STORAGE_OPTS = {"User-Agent": "Mozilla/5.0"}
_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_SP400_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
_SP600_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
_SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

# GICS sectors → sector ETF tickers (11 sectors, rarely changes)
SECTOR_ETF_MAP: dict[str, str] = {
    "Technology": "XLK",
    "Information Technology": "XLK",
    "Healthcare": "XLV",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Financial Services": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Cyclical": "XLY",
    "Consumer Staples": "XLP",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

# European GICS sectors → iShares STOXX 600 sector ETFs (XETRA-listed)
SECTOR_ETF_MAP_EU: dict[str, str] = {
    "Technology": "EXS1.DE",
    "Information Technology": "EXS1.DE",
    "Healthcare": "EXH7.DE",
    "Health Care": "EXH7.DE",
    "Financials": "EXH1.DE",
    "Financial Services": "EXH1.DE",
    "Consumer Discretionary": "EXV6.DE",
    "Consumer Cyclical": "EXV6.DE",
    "Consumer Staples": "EXHD.DE",
    "Consumer Defensive": "EXHD.DE",
    "Energy": "EXSA.DE",  # No dedicated energy ETF — use broad STOXX 600
    "Industrials": "EXH4.DE",
    "Materials": "EXV7.DE",
    "Basic Materials": "EXV7.DE",
    "Utilities": "EXH9.DE",
    "Real Estate": "EXID.DE",
    "Communication Services": "EXHB.DE",
}


def get_sector_etf_map(region: str = "us") -> dict[str, str]:
    """Return GICS sector → ETF ticker mapping for region."""
    if region == "eu":
        return SECTOR_ETF_MAP_EU.copy()
    return SECTOR_ETF_MAP.copy()


def get_russell1000_tickers() -> list[str]:
    """Get ~900 large/mid-cap US stock tickers.

    Strategy:
    1. Check disk cache (7-day TTL)
    2. Wikipedia S&P 500 + S&P 400 (~903 curated tickers)
    3. Fallback: SEC EDGAR NYSE/NASDAQ filers (~7,500 tickers)

    Returns:
        Sorted list of ticker symbols.
    """
    cached = _load_cache(UNIVERSE_CACHE)
    if cached is not None:
        logger.info("Loaded %d tickers from cache", len(cached["tickers"]))
        return cached["tickers"]

    # Primary: Wikipedia S&P 500 + S&P 400
    tickers, metadata = _fetch_wikipedia_universe()
    if len(tickers) >= 400:
        logger.info("Wikipedia universe: %d tickers", len(tickers))
        _save_cache(tickers, metadata, source="wikipedia")
        return tickers

    # Fallback: SEC EDGAR (no metadata — sector/name not available)
    logger.warning("Wikipedia returned only %d tickers, falling back to SEC EDGAR", len(tickers))
    sec_tickers = _fetch_sec_universe()
    if sec_tickers:
        logger.info("SEC EDGAR universe: %d tickers", len(sec_tickers))
        _save_cache(sec_tickers, {}, source="sec_edgar")
        return sec_tickers

    raise RuntimeError("Both universe sources (Wikipedia, SEC EDGAR) failed")


def get_wide_us_universe() -> list[str]:
    """Get ~1500 US large/mid/small-cap tickers (S&P 500 + 400 + 600).

    Wider and smaller-cap than `get_russell1000_tickers()` — used by the early
    scanner, which fishes below the large-cap band where 10-30x headroom lives.
    Metadata (name + GICS sector) is captured alongside, cached 7 days.

    Returns:
        Sorted list of ticker symbols.
    """
    cached = _load_cache(WIDE_CACHE)
    if cached is not None:
        logger.info("Loaded %d wide-US tickers from cache", len(cached["tickers"]))
        tickers_c: list[str] = cached["tickers"]
        return tickers_c

    tickers, metadata = _fetch_wikipedia_universe([_SP500_URL, _SP400_URL, _SP600_URL])
    if len(tickers) >= 800:
        logger.info("Wide US universe: %d tickers", len(tickers))
        _save_cache(tickers, metadata, source="wikipedia_wide", cache_path=WIDE_CACHE)
        return tickers

    raise RuntimeError(f"Wide US universe fetch failed — only {len(tickers)} tickers")


def get_wide_us_metadata() -> dict[str, dict[str, str]]:
    """Get cached metadata (name, sector) for the wide US universe."""
    cached = _load_cache(WIDE_CACHE)
    if cached is not None:
        meta: dict[str, dict[str, str]] = cached.get("metadata", {})
        return meta
    return {}


def get_ticker_metadata(region: str = "us") -> dict[str, dict[str, str]]:
    """Get cached metadata (name, sector) for universe tickers.

    Returns:
        Dict mapping ticker → {"name": str, "sector": str}.
        Empty dict if no metadata cached (e.g., SEC EDGAR fallback).
    """
    cache_path = EU_CACHE if region == "eu" else UNIVERSE_CACHE
    cached = _load_cache(cache_path)
    if cached is not None:
        return cached.get("metadata", {})
    return {}


def get_european_tickers() -> list[str]:
    """Get ~500 European stock tickers from Wikipedia indices.

    Strategy:
    1. Check disk cache (7-day TTL)
    2. Wikipedia scrape of 14+ European indices (FTSE 100, DAX, CAC 40, etc.)

    Returns:
        Sorted list of ticker symbols with exchange suffixes.
    """
    cached = _load_cache(EU_CACHE)
    if cached is not None:
        logger.info("Loaded %d EU tickers from cache", len(cached["tickers"]))
        return cached["tickers"]

    tickers, metadata = _fetch_european_universe()
    if len(tickers) >= 100:
        logger.info("European universe: %d tickers", len(tickers))
        _save_cache(tickers, metadata, source="wikipedia_eu", cache_path=EU_CACHE)
        return tickers

    if not tickers:
        raise RuntimeError("European universe fetch failed — no tickers from any index")
    logger.warning("European Wikipedia fetch returned only %d tickers", len(tickers))
    return tickers


def _fetch_wikipedia_universe(
    urls: list[str] | None = None,
) -> tuple[list[str], dict[str, dict[str, str]]]:
    """Fetch S&P constituents from one or more Wikipedia index pages.

    Defaults to S&P 500 + S&P 400 (momentum universe). Pass a wider URL list
    (e.g. + S&P 600) for the early scanner's universe.

    Returns:
        (sorted ticker list, metadata dict: ticker → {name, sector})
    """
    if urls is None:
        urls = [_SP500_URL, _SP400_URL]

    tickers: list[str] = []
    metadata: dict[str, dict[str, str]] = {}

    for url in urls:
        try:
            tables = pd.read_html(url, storage_options=_STORAGE_OPTS)
            df = tables[0]

            # Resolve column names (S&P 500 vs S&P 400 differ slightly)
            sym_col = "Symbol" if "Symbol" in df.columns else "Ticker symbol"
            name_col = "Security" if "Security" in df.columns else "Company"
            sector_col = "GICS Sector" if "GICS Sector" in df.columns else None

            for _, row in df.iterrows():
                raw_sym = str(row[sym_col]).strip()
                # BRK.B → BRK-B for yfinance compatibility
                ticker = raw_sym.replace(".", "-")
                if not ticker:
                    continue

                tickers.append(ticker)
                metadata[ticker] = {
                    "name": str(row.get(name_col, ticker)).strip(),
                    "sector": (
                        str(row.get(sector_col, "Unknown")).strip()
                        if sector_col else "Unknown"
                    ),
                }
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", url, e)

    # Dedupe preserving first occurrence (S&P 500 entry preferred over S&P 400)
    seen = set()
    unique: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    return sorted(unique), metadata


def _fetch_sec_universe() -> list[str]:
    """Fetch all NYSE/NASDAQ tickers from SEC EDGAR."""
    try:
        resp = requests.get(
            _SEC_URL,
            headers={"User-Agent": "MomentumScanner valuation@odyssey.dev"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data["data"], columns=data["fields"])
        major = df[df["exchange"].isin({"NYSE", "NASDAQ", "Nasdaq"})]
        return sorted(major["ticker"].drop_duplicates().tolist())
    except Exception as e:
        logger.warning("Failed to fetch SEC EDGAR tickers: %s", e)
        return []


def _load_cache(cache_path: Path = UNIVERSE_CACHE) -> dict | None:
    """Load cached universe if fresh enough.

    Returns full cache dict with 'tickers', 'metadata', etc., or None.
    """
    if not cache_path.exists():
        return None

    try:
        data = json.loads(cache_path.read_text())
        cached_at = data.get("cached_at", 0)
        if time.time() - cached_at > CACHE_TTL_SECONDS:
            logger.info("Universe cache expired: %s", cache_path)
            return None
        tickers = data.get("tickers", [])
        if len(tickers) < 100:
            logger.warning("Cached universe too small (%d), refetching", len(tickers))
            return None
        return data
    except (json.JSONDecodeError, KeyError):
        return None


def _save_cache(
    tickers: list[str],
    metadata: dict[str, dict[str, str]],
    source: str = "unknown",
    cache_path: Path = UNIVERSE_CACHE,
) -> None:
    """Save universe + metadata to disk cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "cached_at": time.time(),
        "source": source,
        "count": len(tickers),
        "tickers": tickers,
        "metadata": metadata,
    }
    cache_path.write_text(json.dumps(data, indent=2))
    logger.info("Cached %d tickers (%s) to %s", len(tickers), source, cache_path)


# ─── European Universe ───


# Wikipedia indices for European coverage (~500 tickers from 14 countries)
_EU_INDICES: list[dict] = [
    {
        "name": "FTSE 100",
        "url": "https://en.wikipedia.org/wiki/FTSE_100_Index",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": ".L",
    },
    {
        "name": "DAX",
        "url": "https://en.wikipedia.org/wiki/DAX",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": None,  # Already has .DE suffix
    },
    {
        "name": "CAC 40",
        "url": "https://en.wikipedia.org/wiki/CAC_40",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": None,  # Already has .PA suffix
    },
    {
        "name": "OMX Stockholm 30",
        "url": "https://en.wikipedia.org/wiki/OMX_Stockholm_30",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": None,  # Already has .ST suffix
    },
    {
        "name": "SMI",
        "url": "https://en.wikipedia.org/wiki/Swiss_Market_Index",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": ".SW",
    },
    {
        "name": "IBEX 35",
        "url": "https://en.wikipedia.org/wiki/IBEX_35",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": None,  # Already has .MC suffix
    },
    {
        "name": "FTSE MIB",
        "url": "https://en.wikipedia.org/wiki/FTSE_MIB",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": ".MI",
    },
    {
        "name": "AEX",
        "url": "https://en.wikipedia.org/wiki/AEX_index",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": ".AS",
    },
    {
        "name": "OMX Helsinki 25",
        "url": "https://en.wikipedia.org/wiki/OMX_Helsinki_25",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": ".HE",
    },
    {
        "name": "BEL 20",
        "url": "https://en.wikipedia.org/wiki/BEL_20",
        "ticker_col": "Ticker",
        "name_col": "Name",
        "suffix": ".BR",
    },
    {
        "name": "OBX",
        "url": "https://en.wikipedia.org/wiki/OBX_Index",
        "ticker_col": "Ticker symbol",
        "name_col": "Company",
        "suffix": ".OL",
        "strip_prefix": "OSE: ",
    },
    {
        "name": "OMX Copenhagen 25",
        "url": "https://en.wikipedia.org/wiki/OMX_Copenhagen_25",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": ".CO",
    },
    {
        "name": "ATX",
        "url": "https://en.wikipedia.org/wiki/Austrian_Traded_Index",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": ".VI",
    },
    {
        "name": "PSI-20",
        "url": "https://en.wikipedia.org/wiki/PSI-20",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": ".LS",
    },
    # Mid-cap indices for deeper coverage
    {
        "name": "FTSE 250",
        "url": "https://en.wikipedia.org/wiki/FTSE_250_Index",
        "ticker_col": "Ticker",
        "name_col": "Company",
        "suffix": ".L",
    },
    {
        "name": "MDAX",
        "url": "https://en.wikipedia.org/wiki/MDAX",
        "ticker_col": "Symbol",
        "name_col": "Name",
        "suffix": ".DE",
    },
]

# European exchange suffixes for region detection
EU_SUFFIXES = (
    ".DE", ".L", ".PA", ".ST", ".OL", ".MI", ".AS", ".HE",
    ".BR", ".SW", ".CO", ".VI", ".LS", ".MC",
)


def _fetch_european_universe() -> tuple[list[str], dict[str, dict[str, str]]]:
    """Fetch European stock constituents from multiple Wikipedia indices.

    Returns:
        (sorted ticker list, metadata dict: ticker → {name, sector, index})
    """
    tickers: list[str] = []
    metadata: dict[str, dict[str, str]] = {}

    for idx_def in _EU_INDICES:
        try:
            tables = pd.read_html(idx_def["url"], storage_options=_STORAGE_OPTS)
            df = _find_best_table(tables, idx_def)
            if df is None:
                logger.warning("No suitable table found for %s", idx_def["name"])
                continue

            ticker_col = _find_column(df, idx_def["ticker_col"])
            name_col = _find_column(df, idx_def.get("name_col", "Company"))

            if ticker_col is None:
                logger.warning("No ticker column in %s", idx_def["name"])
                continue

            for _, row in df.iterrows():
                raw = str(row[ticker_col]).strip()
                if not raw or raw == "nan":
                    continue

                # Strip prefix if needed (e.g., OBX: "OSE: AKRBP" → "AKRBP")
                strip_prefix = idx_def.get("strip_prefix")
                if strip_prefix and raw.startswith(strip_prefix):
                    raw = raw[len(strip_prefix):]

                # Apply suffix if ticker doesn't already have an exchange suffix
                ticker = _apply_suffix(raw, idx_def.get("suffix"))

                name = ""
                if name_col is not None:
                    name = str(row[name_col]).strip()
                    if name == "nan":
                        name = ""

                tickers.append(ticker)
                if ticker not in metadata:
                    metadata[ticker] = {
                        "name": name or ticker,
                        "sector": "Unknown",
                        "index": idx_def["name"],
                    }

            logger.info("%s: extracted %d candidates", idx_def["name"], len(df))

        except Exception as e:
            logger.warning("Failed to fetch %s: %s", idx_def["name"], e)

    # Dedupe preserving first occurrence
    seen: set[str] = set()
    unique: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    logger.info("European universe: %d unique tickers from %d indices",
                len(unique), len(_EU_INDICES))
    return sorted(unique), metadata


def _find_best_table(
    tables: list[pd.DataFrame], idx_def: dict
) -> pd.DataFrame | None:
    """Find the table most likely to contain stock constituents.

    Heuristic: largest table with a column matching the ticker column name.
    """
    ticker_col_hint = idx_def["ticker_col"].lower()

    candidates = []
    for df in tables:
        for col in df.columns:
            col_lower = str(col).lower()
            if ticker_col_hint in col_lower or "ticker" in col_lower or "symbol" in col_lower:
                candidates.append(df)
                break

    if not candidates:
        # Fall back to largest table
        return max(tables, key=len) if tables else None

    # Return largest matching table
    return max(candidates, key=len)


def _find_column(df: pd.DataFrame, col_hint: str) -> str | None:
    """Find a column by fuzzy matching (handles Wikipedia footnote suffixes).

    E.g., "Ticker" matches "Ticker[38]" or "Ticker symbol".
    """
    hint_lower = col_hint.lower()
    for col in df.columns:
        col_lower = str(col).lower()
        if col_lower == hint_lower or col_lower.startswith(hint_lower):
            return col
    # Broader match: hint anywhere in column name
    for col in df.columns:
        if hint_lower in str(col).lower():
            return col
    return None


def _apply_suffix(raw: str, suffix: str | None) -> str:
    """Apply exchange suffix if the ticker doesn't already have one."""
    if suffix is None:
        return raw
    # Check if ticker already has a dot-suffix (e.g., "ADS.DE" from DAX)
    if "." in raw:
        return raw
    return raw + suffix
