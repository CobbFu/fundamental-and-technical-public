"""Momentum scanner orchestrator — runs scans, manages tiers, tracks changes.

Coordinates universe resolution, data fetching, signal computation,
tier management, and state persistence. The main entry point for
weekly momentum scans, fallen angel scans, and daily new-highs checks.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yfinance as yf

from src.momentum.data import MomentumDataStore
from src.momentum.fallen_angels import (
    drawdown_from_high,
    is_fallen_angel,
    simplified_altman_z_score,
    simplified_piotroski_f_score,
)
from src.momentum.fundamentals import (
    analyst_buy_percentage,
    earnings_growth_estimate,
    earnings_revision_score,
    short_interest_pct,
)
from src.momentum.fundamentals import fcf_yield as compute_fcf_yield
from src.momentum.fundamentals import forward_pe as compute_forward_pe
from src.momentum.signals import (
    absolute_momentum_check,
    composite_momentum_score,
    fresh_stale_momentum,
    frog_in_pan,
    ma_position,
    ma_slope_200,
    momentum_acceleration,
    momentum_return_2_12,
    obv_trend,
    relative_strength_vs_sector,
    slow_fast_agreement,
)
from src.momentum.universe import (
    get_european_tickers,
    get_russell1000_tickers,
    get_sector_etf_map,
    get_ticker_metadata,
)

logger = logging.getLogger(__name__)


# ─── Result dataclasses ───


@dataclass
class TierEntry:
    ticker: str
    name: str
    sector: str
    return_12m: float
    fip_score: float
    composite_score: float
    tier: int  # 1, 2, or 3
    weeks_on_list: int
    change: str  # "new", "promoted", "demoted", "unchanged", "dropped"
    # Stage detection (v2)
    acceleration: float | None = None
    freshness: str | None = None
    stage: str = "MID"
    ma_slope_200d: float | None = None
    slow_fast: str = "bull"
    # Fundamental enrichment (v3 — Phase 17)
    revision_score: float | None = None      # [-1, 1] net revision direction
    buy_pct: float | None = None             # [0, 1] analyst buy percentage
    earnings_growth: float | None = None     # decimal growth estimate
    forward_pe: float | None = None          # forward P/E ratio
    fcf_yield: float | None = None           # FCF / market cap
    short_pct: float | None = None           # short interest % of float
    piotroski_f: int | None = None           # F-Score 0-9


@dataclass
class ScanResult:
    date: str
    universe_size: int
    tier1: list[TierEntry]
    tier2: list[TierEntry]
    tier3: list[TierEntry]  # top 50 only
    promotions: list[TierEntry] = field(default_factory=list)
    demotions: list[TierEntry] = field(default_factory=list)
    new_entries: list[TierEntry] = field(default_factory=list)
    drops: list[str] = field(default_factory=list)
    market_regime: str = "risk-on"


@dataclass
class FallenAngelEntry:
    ticker: str
    name: str
    sector: str
    drawdown_pct: float
    f_score: int
    z_score: float | None
    fcf_positive: bool
    market_cap_b: float
    weeks_on_list: int


@dataclass
class FallenAngelResult:
    date: str
    candidates_scanned: int
    angels: list[FallenAngelEntry]


@dataclass
class DailyHighsResult:
    date: str
    ticker: str
    name: str
    new_high_count_20d: int
    return_12m: float
    on_radar: bool  # already on Tier 1/2?


# ─── Configuration ───

DEFAULT_TIER1_SIZE = 7
DEFAULT_TIER2_SIZE = 15
DEFAULT_TIER3_SIZE = 50
MIN_COMPOSITE_TIER1 = 70.0  # minimum score for Tier 1
MIN_COMPOSITE_TIER2 = 55.0  # minimum score for Tier 2
TBILL_RATE_DEFAULT = 0.045  # fallback T-bill rate if not fetchable


class MomentumScanner:
    """Main orchestrator for weekly momentum scanning."""

    def __init__(self, db_path: Path | str | None = None):
        self.store = MomentumDataStore(db_path)

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "MomentumScanner":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def run_weekly_scan(
        self,
        *,
        universe: str = "us",
        tier1_size: int = DEFAULT_TIER1_SIZE,
        tier2_size: int = DEFAULT_TIER2_SIZE,
        tier3_size: int = DEFAULT_TIER3_SIZE,
    ) -> ScanResult:
        """Full weekly momentum scan.

        1. Get universe tickers
        2. Fetch/update OHLCV (batch, with cache)
        3. Fetch sector ETF data for relative strength
        4. Compute all signals per ticker
        5. Rank by composite score
        6. Apply tier thresholds
        7. Compare vs previous week: detect promotions, demotions, new entries, drops
        8. Update SQLite scan_state
        9. Return ScanResult
        """
        today = date.today().isoformat()

        # 1. Get universe
        if universe == "eu":
            tickers = get_european_tickers()
        else:
            tickers = get_russell1000_tickers()
        logger.info("Universe (%s): %d tickers", universe, len(tickers))

        # 2. Fetch OHLCV (25mo for stage detection: fresh/stale needs 504 days)
        ohlcv_map = self.store.fetch_ohlcv(tickers, period="25mo")
        logger.info("OHLCV fetched for %d tickers", len(ohlcv_map))

        # 3. Fetch sector ETF data + broad market ETF for absolute momentum
        sector_etfs = get_sector_etf_map(region=universe)
        broad_etf = "EXSA.DE" if universe == "eu" else "SPY"
        unique_etfs = list(set(sector_etfs.values())) + [broad_etf]
        etf_data = self.store.fetch_ohlcv(unique_etfs, period="25mo")

        # Check absolute momentum (market regime)
        broad_df = etf_data.get(broad_etf)
        market_regime = "risk-on"
        if broad_df is not None:
            is_risk_on = absolute_momentum_check(
                broad_df, TBILL_RATE_DEFAULT,
            )
            market_regime = "risk-on" if is_risk_on else "risk-off"
        logger.info("Market regime: %s", market_regime)

        # 4. Compute signals per ticker
        # Use cached Wikipedia metadata (name + sector)
        wiki_meta = get_ticker_metadata(region=universe)
        scored: list[dict] = []

        for ticker, df in ohlcv_map.items():
            if ticker in unique_etfs:
                continue  # skip ETFs themselves
            if len(df) < 200:
                continue  # insufficient data

            try:
                ret_2_12 = momentum_return_2_12(df)
                fip = frog_in_pan(df)
                obv = obv_trend(df)
                above_50, above_200 = ma_position(df)

                # Relative strength: find sector ETF from cached metadata
                meta = wiki_meta.get(ticker, {})
                sector = meta.get("sector", "Unknown")
                name = meta.get("name", ticker)
                sector_etf_ticker = sector_etfs.get(sector, broad_etf)
                sector_df = etf_data.get(sector_etf_ticker)
                rel_str = (
                    relative_strength_vs_sector(df, sector_df)
                    if sector_df is not None
                    else 1.0
                )

                # Composite score
                score = composite_momentum_score(ret_2_12, fip, obv, rel_str, above_50, above_200)

                # Stage detection signals
                accel = momentum_acceleration(df)
                fresh = fresh_stale_momentum(df)
                slope = ma_slope_200(df)
                sf = slow_fast_agreement(df)
                stage = _assign_stage(accel, fresh, slope, sf)

                scored.append({
                    "ticker": ticker,
                    "name": name,
                    "sector": sector,
                    "return_12m": ret_2_12 if ret_2_12 is not None else 0.0,
                    "fip_score": fip,
                    "composite_score": score,
                    "obv_trend": 1 if obv else 0,
                    "rel_strength": rel_str,
                    "acceleration": accel,
                    "freshness": fresh,
                    "stage": stage,
                    "ma_slope_200d": slope,
                    "slow_fast": sf,
                })
            except Exception as e:
                logger.debug("Error computing signals for %s: %s", ticker, e)

        # 5. Rank by composite score
        scored.sort(key=lambda x: x["composite_score"], reverse=True)
        logger.info("Scored %d tickers", len(scored))

        # 6. Load previous state for change detection
        prev_state = self.store.load_scan_state()

        # 7. Assign tiers and detect changes
        tier1_entries: list[TierEntry] = []
        tier2_entries: list[TierEntry] = []
        tier3_entries: list[TierEntry] = []
        promotions: list[TierEntry] = []
        demotions: list[TierEntry] = []
        new_entries: list[TierEntry] = []
        current_tickers = set()

        for rank, item in enumerate(scored):
            if rank >= tier3_size:
                break

            ticker = item["ticker"]
            current_tickers.add(ticker)
            prev = prev_state.get(ticker)
            prev_tier = prev["tier"] if prev else None
            weeks = (prev["weeks_on_list"] + 1) if prev else 1

            # Determine tier
            tier = _assign_tier(rank, item["composite_score"], tier1_size, tier2_size)

            # Detect change
            if prev_tier is None:
                change = "new"
            elif tier < prev_tier:
                change = "promoted"
            elif tier > prev_tier:
                change = "demoted"
            else:
                change = "unchanged"

            entry = TierEntry(
                ticker=ticker,
                name=item["name"],
                sector=item["sector"],
                return_12m=item["return_12m"],
                fip_score=item["fip_score"],
                composite_score=item["composite_score"],
                tier=tier,
                weeks_on_list=weeks,
                change=change,
                acceleration=item.get("acceleration"),
                freshness=item.get("freshness"),
                stage=item.get("stage", "MID"),
                ma_slope_200d=item.get("ma_slope_200d"),
                slow_fast=item.get("slow_fast", "bull"),
            )

            if tier == 1:
                tier1_entries.append(entry)
            elif tier == 2:
                tier2_entries.append(entry)
            else:
                tier3_entries.append(entry)

            if change == "promoted":
                promotions.append(entry)
            elif change == "demoted":
                demotions.append(entry)
            elif change == "new":
                new_entries.append(entry)

        # 7b. Fundamental enrichment (Tier 1+2 only — ~22 stocks, not 900)
        # Pass 1: analyst data (revisions, consensus, earnings growth)
        # Pass 2: .info data (forward P/E, FCF yield, short interest, Piotroski)
        tier12_entries = tier1_entries + tier2_entries
        if tier12_entries:
            logger.info(
                "Fundamental enrichment: %d Tier 1+2 stocks", len(tier12_entries),
            )
            info_cache: dict[str, dict] = {}
            for entry in tier12_entries:
                # Pass 1: analyst data
                try:
                    t = yf.Ticker(entry.ticker)
                    entry.revision_score = earnings_revision_score(t.eps_revisions)
                    entry.buy_pct = analyst_buy_percentage(t.recommendations)
                    entry.earnings_growth = earnings_growth_estimate(t.earnings_estimate)
                except Exception as e:
                    logger.debug("Pass 1 error for %s: %s", entry.ticker, e)
                # Pass 2: .info data
                try:
                    info = _get_yf_info(entry.ticker, info_cache)
                    entry.forward_pe = compute_forward_pe(info)
                    entry.fcf_yield = compute_fcf_yield(info)
                    entry.short_pct = short_interest_pct(info)
                    entry.piotroski_f = simplified_piotroski_f_score(info)
                except Exception as e:
                    logger.debug("Pass 2 error for %s: %s", entry.ticker, e)

        # Detect drops (were on list, no longer)
        drops = [t for t in prev_state if t not in current_tickers]

        # 8. Update scan_state in SQLite (reuse tier/weeks from step 7 entries)
        all_entries = tier1_entries + tier2_entries + tier3_entries
        entry_lookup = {e.ticker: e for e in all_entries}

        state_entries = []
        for rank, item in enumerate(scored[:tier3_size]):
            ticker = item["ticker"]
            entry = entry_lookup.get(ticker)
            if entry is None:
                continue
            prev = prev_state.get(ticker)
            first_seen = prev["first_seen"] if prev else today
            state_entry = {
                "ticker": ticker,
                "tier": entry.tier,
                "composite_score": entry.composite_score,
                "weeks_on_list": entry.weeks_on_list,
                "first_seen": first_seen,
                "last_seen": today,
                "fip_score": item["fip_score"],
                "return_12m": item["return_12m"],
                "obv_trend": item["obv_trend"],
                "rel_strength": item["rel_strength"],
                "acceleration": item.get("acceleration"),
                "freshness": item.get("freshness"),
                "stage": item.get("stage", "MID"),
                "ma_slope_200d": item.get("ma_slope_200d"),
                "revision_score": entry.revision_score,
                "buy_pct": entry.buy_pct,
                "earnings_growth": entry.earnings_growth,
                "forward_pe": entry.forward_pe,
                "fcf_yield": entry.fcf_yield,
                "short_pct": entry.short_pct,
                "piotroski_f": entry.piotroski_f,
            }
            state_entries.append(state_entry)

        self.store.save_scan_state(state_entries)

        return ScanResult(
            date=today,
            universe_size=len(ohlcv_map),
            tier1=tier1_entries,
            tier2=tier2_entries,
            tier3=tier3_entries,
            promotions=promotions,
            demotions=demotions,
            new_entries=new_entries,
            drops=drops,
            market_regime=market_regime,
        )

    def run_daily_new_highs(self) -> DailyHighsResult | None:
        """Daily new 52-week high check. Returns max 1 name or None.

        1. Load cached OHLCV for all tracked tickers
        2. Find tickers at new 52-week high
        3. Check frequency in last 20 days (5+ = notable)
        4. Pick the most notable that isn't already Tier 1/2
        """
        today = date.today().isoformat()
        cached_tickers = self.store.load_all_cached_tickers()
        if not cached_tickers:
            return None

        scan_state = self.store.load_scan_state()
        best_candidate: DailyHighsResult | None = None
        best_count = 0

        for ticker in cached_tickers:
            df = self.store.load_cached_ohlcv(ticker, days=252)
            if df is None or len(df) < 252:
                continue

            close = df["Close"].values
            current = close[-1]
            high_252 = float(close.max())

            # Check if at or near 52-week high (within 1%)
            if current < high_252 * 0.99:
                continue

            # Record the new high
            self.store.record_new_high(ticker, today)

            # Count recent new highs (20 trading days ≈ 1 month)
            count = self.store.count_new_highs(ticker, lookback_trading_days=20)
            if count < 5:
                continue  # not notable enough

            # Prefer tickers NOT already on Tier 1/2
            on_radar = ticker in scan_state and scan_state[ticker]["tier"] in (1, 2)

            # Prefer: highest count, not on radar
            priority = count + (0 if on_radar else 100)
            if priority > best_count:
                ret_2_12 = momentum_return_2_12(df) or 0.0
                wiki_meta = get_ticker_metadata()
                meta = wiki_meta.get(ticker, {})
                best_candidate = DailyHighsResult(
                    date=today,
                    ticker=ticker,
                    name=meta.get("name", ticker),
                    new_high_count_20d=count,
                    return_12m=ret_2_12,
                    on_radar=on_radar,
                )
                best_count = priority

        return best_candidate


class FallenAngelScanner:
    """Scanner for quality companies in sustained decline."""

    def __init__(self, db_path: Path | str | None = None):
        self.store = MomentumDataStore(db_path)

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "FallenAngelScanner":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def run_scan(self) -> FallenAngelResult:
        """Weekly fallen angel scan.

        1. From cached OHLCV, find stocks with 25-40% drawdown from 52wk high
        2. For candidates, fetch yfinance .info for fundamentals
        3. Apply quality filters (F-Score, Z-Score, market cap, FCF)
        4. Rank by drawdown (deeper = more interesting, given quality passes)
        5. Update SQLite
        """
        today = date.today().isoformat()
        cached_tickers = self.store.load_all_cached_tickers()
        if not cached_tickers:
            return FallenAngelResult(date=today, candidates_scanned=0, angels=[])

        prev_state = self.store.load_fallen_angels_state()
        candidates_scanned = 0
        angels: list[FallenAngelEntry] = []
        ticker_info_cache: dict[str, dict] = {}

        for ticker in cached_tickers:
            df = self.store.load_cached_ohlcv(ticker, days=252)
            if df is None or len(df) < 200:
                continue

            dd = drawdown_from_high(df)
            if dd < 0.20:  # pre-filter: at least 20% off high
                continue

            candidates_scanned += 1

            try:
                info = _get_yf_info(ticker, ticker_info_cache)
                f_score = simplified_piotroski_f_score(info)
                z_score = simplified_altman_z_score(info)
                market_cap = info.get("marketCap")
                fcf = info.get("freeCashflow")

                if not is_fallen_angel(dd, f_score, z_score, market_cap, fcf):
                    continue

                prev = prev_state.get(ticker)
                weeks = (prev["weeks_on_list"] + 1) if prev else 1

                angels.append(FallenAngelEntry(
                    ticker=ticker,
                    name=info.get("shortName", ticker),
                    sector=info.get("sector", "Unknown"),
                    drawdown_pct=dd,
                    f_score=f_score,
                    z_score=z_score,
                    fcf_positive=fcf is not None and fcf > 0,
                    market_cap_b=(market_cap / 1e9) if market_cap else 0.0,
                    weeks_on_list=weeks,
                ))
            except Exception as e:
                logger.debug("Error processing fallen angel %s: %s", ticker, e)

        # Sort by drawdown (deeper = more interesting)
        angels.sort(key=lambda a: a.drawdown_pct, reverse=True)

        # Update SQLite state
        state_entries = []
        for a in angels:
            prev = prev_state.get(a.ticker)
            state_entries.append({
                "ticker": a.ticker,
                "drawdown_pct": a.drawdown_pct,
                "f_score": a.f_score,
                "z_score": a.z_score,
                "fcf_positive": 1 if a.fcf_positive else 0,
                "weeks_on_list": a.weeks_on_list,
                "first_seen": prev["first_seen"] if prev else today,
                "last_seen": today,
            })
        self.store.save_fallen_angels_state(state_entries)

        logger.info(
            "Fallen angel scan: %d candidates → %d angels",
            candidates_scanned, len(angels),
        )
        return FallenAngelResult(
            date=today,
            candidates_scanned=candidates_scanned,
            angels=angels,
        )


# ─── Shared helpers ───


def _assign_stage(
    accel: float | None,
    freshness: str | None,
    ma_slope: float | None,
    slow_fast: str,
) -> str:
    """Classify momentum stage: EARLY, MID, or LATE."""
    # LATE conditions (any one triggers)
    if freshness == "stale":
        return "LATE"
    if accel is not None and accel < 0.6:
        return "LATE"
    if slow_fast == "correction":
        return "LATE"
    if ma_slope is not None and ma_slope < 0.0:
        return "LATE"

    # EARLY conditions
    if freshness == "fresh" and (accel is None or accel > 1.0):
        return "EARLY"
    if freshness is None and accel is not None and accel > 1.5:
        return "EARLY"

    return "MID"


def _assign_tier(rank: int, score: float, tier1_size: int, tier2_size: int) -> int:
    """Assign tier based on rank and minimum score thresholds."""
    if rank < tier1_size and score >= MIN_COMPOSITE_TIER1:
        return 1
    if rank < tier1_size + tier2_size and score >= MIN_COMPOSITE_TIER2:
        return 2
    return 3


def _get_yf_info(ticker: str, cache: dict[str, dict]) -> dict:
    """Get yfinance .info with in-memory caching."""
    if ticker in cache:
        return cache[ticker]
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    cache[ticker] = info
    return info
