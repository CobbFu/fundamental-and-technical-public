"""Cascade scanner orchestrator — watches supply chain cascades for early breakouts.

Coordinates cascade config loading, OHLCV fetching, signal computation,
breadth thrust detection, and tier status assignment. Separate from
the momentum scanner — different signals, different cadence, different purpose.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yfinance as yf

from src.cascade.config import (
    all_tickers,
    cross_cascade_map,
    load_cascades,
)
from src.cascade.data import CascadeDataStore
from src.cascade.signals import (
    base_breakout,
    distance_from_52w_high,
    return_3m,
    volume_ratio,
)
from src.momentum.signals import ma_position, relative_strength_vs_sector
from src.momentum.universe import EU_SUFFIXES, get_sector_etf_map, get_ticker_metadata

logger = logging.getLogger(__name__)

# Breadth threshold: 60% of tier above 50d MA = ACTIVE
BREADTH_ACTIVE_THRESHOLD = 0.6


# ─── Result dataclasses ───


@dataclass
class StockSignals:
    ticker: str
    name: str
    return_3m: float | None
    volume_ratio: float | None
    dist_52w_high: float | None
    rel_strength: float | None
    base_status: str  # "broke_out", "breaking", "near_top", "in_base", "above", "no_base"
    above_50d_ma: bool
    signal: str = ""  # plain-English verdict


@dataclass
class TierResult:
    name: str
    stocks: list[StockSignals]
    breadth: int  # count of stocks above 50d MA
    breadth_total: int  # total stocks in tier
    status: str  # "ACTIVE", "NEXT", "QUIET", "MATURE"


@dataclass
class CascadeResult:
    name: str
    demand_driver: str
    tiers: list[TierResult]
    cross_cascade_tickers: list[str] = field(default_factory=list)


@dataclass
class CascadeScanResult:
    date: str
    cascades: list[CascadeResult]
    cross_cascade: dict[str, list[str]]  # ticker -> [cascade names]


class CascadeScanner:
    """Main orchestrator for supply chain cascade monitoring."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        cascades_path: Path | None = None,
    ):
        self.store = CascadeDataStore(db_path)
        self._cascades_path = cascades_path

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "CascadeScanner":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def run_scan(self) -> CascadeScanResult:
        """Full cascade scan.

        1. Load cascade config
        2. Collect all unique tickers
        3. Fetch OHLCV (batch, with cache)
        4. Fetch sector ETF data for relative strength
        5. Get ticker metadata for names
        6. For each cascade -> for each tier -> compute signals
        7. Compute breadth per tier
        8. Assign tier status (ACTIVE/NEXT/QUIET/MATURE)
        9. Build cross-cascade map
        10. Return CascadeScanResult
        """
        today = date.today().isoformat()

        # 1. Load config
        config = load_cascades(self._cascades_path)
        logger.info("Loaded %d cascades", len(config.cascades))

        # 2. Collect unique tickers
        unique_tickers = all_tickers(config)
        logger.info("Unique tickers: %d", len(unique_tickers))

        # 3. Fetch OHLCV — 1 year sufficient for 3m signals + base detection
        ohlcv_map = self.store.fetch_ohlcv(unique_tickers, period="1y")
        logger.info("OHLCV fetched for %d tickers", len(ohlcv_map))

        # 4. Sector ETF data for relative strength (both US + EU)
        us_sector_etfs = get_sector_etf_map("us")
        eu_sector_etfs = get_sector_etf_map("eu")
        all_etf_tickers = list(
            set(us_sector_etfs.values()) | set(eu_sector_etfs.values())
        )
        etf_data = self.store.fetch_ohlcv(all_etf_tickers, period="1y")

        # 5. Ticker metadata for names (merge US + EU)
        wiki_meta_us = get_ticker_metadata("us")
        wiki_meta_eu = get_ticker_metadata("eu")
        wiki_meta = {**wiki_meta_us, **wiki_meta_eu}
        # Cache for yfinance .info lookups (international tickers not in wiki)
        info_cache: dict[str, dict] = {}

        # 6. Compute signals per ticker (compute once, reuse across cascades)
        signals_cache: dict[str, StockSignals] = {}
        for ticker in unique_tickers:
            df = ohlcv_map.get(ticker)
            if df is None or len(df) < 63:
                continue

            # Name: try wiki first, then yfinance
            meta = wiki_meta.get(ticker, {})
            name = meta.get("name", "")
            sector = meta.get("sector", "Unknown")

            if not name:
                name = _get_yf_name(ticker, info_cache)

            # Compute signals
            ret3 = return_3m(df)
            vol = volume_ratio(df)
            dist = distance_from_52w_high(df)
            base = base_breakout(df)
            above_50, _ = ma_position(df)

            # Relative strength vs sector (pick ETF map by ticker region)
            is_eu = any(ticker.endswith(s) for s in EU_SUFFIXES)
            etf_map = eu_sector_etfs if is_eu else us_sector_etfs
            fallback_etf = "EXSA.DE" if is_eu else "SPY"
            sector_etf_ticker = etf_map.get(sector, fallback_etf)
            sector_df = etf_data.get(sector_etf_ticker)
            rel_str = (
                relative_strength_vs_sector(df, sector_df)
                if sector_df is not None
                else 1.0
            )

            # Signal verdict
            signal = _compute_signal_verdict(above_50, vol, base, ret3, dist)

            signals_cache[ticker] = StockSignals(
                ticker=ticker,
                name=name or ticker,
                return_3m=ret3,
                volume_ratio=vol,
                dist_52w_high=dist,
                rel_strength=rel_str,
                base_status=base,
                above_50d_ma=above_50,
                signal=signal,
            )

        # 7-8. Build cascade results with breadth and tier status
        cc_map = cross_cascade_map(config)
        cascade_results: list[CascadeResult] = []

        for cascade_def in config.cascades:
            tier_results: list[TierResult] = []

            for tier_def in cascade_def.tiers:
                stocks = [
                    signals_cache[t]
                    for t in tier_def.tickers
                    if t in signals_cache
                ]
                breadth = sum(1 for s in stocks if s.above_50d_ma)
                breadth_total = len(tier_def.tickers)
                tier_results.append(TierResult(
                    name=tier_def.name,
                    stocks=stocks,
                    breadth=breadth,
                    breadth_total=breadth_total,
                    status="QUIET",  # assigned below
                ))

            # Assign tier statuses
            _assign_tier_statuses(tier_results)

            # Cross-cascade tickers for this cascade
            cascade_tickers = {
                t for tier in cascade_def.tiers for t in tier.tickers
            }
            cross_tickers = [t for t in cascade_tickers if t in cc_map]

            cascade_results.append(CascadeResult(
                name=cascade_def.name,
                demand_driver=cascade_def.demand_driver,
                tiers=tier_results,
                cross_cascade_tickers=sorted(cross_tickers),
            ))

        # 9. Persist state
        state_entries = []
        for ticker, sig in signals_cache.items():
            state_entries.append({
                "ticker": ticker,
                "return_3m": sig.return_3m,
                "volume_ratio": sig.volume_ratio,
                "dist_52w_high": sig.dist_52w_high,
                "rel_strength": sig.rel_strength,
                "base_status": sig.base_status,
                "above_50d_ma": 1 if sig.above_50d_ma else 0,
                "last_seen": today,
            })
        self.store.save_cascade_state(state_entries)

        return CascadeScanResult(
            date=today,
            cascades=cascade_results,
            cross_cascade=cc_map,
        )


# ─── Helpers ───


def _assign_tier_statuses(tiers: list[TierResult]) -> None:
    """Assign ACTIVE/NEXT/QUIET/MATURE status to tiers in cascade order.

    Rules:
    - ACTIVE: breadth >= 60% of tier
    - MATURE: ACTIVE + all stocks "above" base (already running, not breaking out)
    - NEXT: first non-ACTIVE tier after an ACTIVE tier
    - QUIET: everything else
    """
    found_active = False
    next_assigned = False

    for tier in tiers:
        if tier.breadth_total == 0:
            tier.status = "QUIET"
            continue

        breadth_pct = tier.breadth / tier.breadth_total

        if breadth_pct >= BREADTH_ACTIVE_THRESHOLD:
            # Check if mature (all above base, no fresh breakouts).
            # First active tier is always ACTIVE (cascade origin), never MATURE.
            all_above = all(
                s.base_status in ("above",) for s in tier.stocks
            ) if tier.stocks else False

            if all_above and found_active:
                tier.status = "MATURE"
            else:
                tier.status = "ACTIVE"
            found_active = True
        elif found_active and not next_assigned:
            tier.status = "NEXT"
            next_assigned = True
        else:
            tier.status = "QUIET"


def _compute_signal_verdict(
    above_50d: bool,
    vol: float | None,
    base: str,
    ret3: float | None,
    dist: float | None,
) -> str:
    """Plain-English signal verdict combining all columns."""
    vol_elevated = vol is not None and vol >= 1.5

    if above_50d and vol_elevated and base in ("broke_out", "breaking"):
        return "Confirmed"
    if above_50d and (vol_elevated or base in ("near_top", "breaking")):
        return "Warming"
    if base in ("breaking",) and not above_50d:
        return "Early"
    if above_50d and not vol_elevated and base == "above":
        return "Mature"
    if not above_50d and base in ("in_base", "no_base"):
        return "Quiet"

    # Tier is ACTIVE but this stock isn't participating
    if not above_50d:
        return "Lagging"

    return "Holding"


def _get_yf_name(ticker: str, cache: dict[str, dict]) -> str:
    """Get company name from yfinance .info with caching."""
    if ticker in cache:
        return cache[ticker].get("shortName", ticker)
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    cache[ticker] = info
    return info.get("shortName", ticker)
