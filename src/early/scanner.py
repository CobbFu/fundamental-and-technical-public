"""Early-stage scanner orchestrator — the inverse of momentum.

Bottom-up over a wide, smaller-cap US universe; a cheap pure-pandas pass cuts to
survivors, then a heavy `.info`/revisions pass applies the anti-momentum gate and
scores them; cohorts emerge by industry and are labeled against curated cascades.

Mirrors src/cascade/scanner.py (control flow) and src/momentum/scanner.py
(two-pass cost control + change detection).
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import yaml
import yfinance as yf

from src.cascade.config import CascadeConfig, load_cascades
from src.cascade.signals import base_breakout, distance_from_52w_high
from src.early.cohort import Cohort, apply_cohort_bonus, group_into_cohorts
from src.early.data import EarlyDataStore
from src.early.fundamentals import (
    earnings_growth_estimate,
    fundamental_gate_score,
    revision_inflection,
)
from src.early.scoring import (
    DEFAULT_SCORE_THRESHOLD,
    early_composite_score,
    headroom_component,
    passes_gate,
    theme_allowed,
    trailing_ceiling_breached,
)
from src.early.signals import (
    accumulation_score,
    base_proximity,
    reaccumulation_base,
    recent_return,
    rs_line_new_high,
    volatility_contraction,
    weinstein_stage,
)
from src.momentum.data import MomentumDataStore
from src.momentum.signals import momentum_return_2_12
from src.momentum.universe import get_wide_us_universe

logger = logging.getLogger(__name__)

BENCHMARK = "SPY"
DEFAULT_PERIOD = "3y"  # deep enough for base history + backtest replay
MIN_BARS = 60
RECENT_LISTING_BARS = 380  # ~18 months of trading days — below this, defer stage to heavy pass
_MIN_TRIGGER_BARS = 131  # base_breakout needs consolidation_days (126) + 5
SEEDS_PATH = Path(".valuation/early_seeds.yaml")


# ─── Result dataclasses ───


@dataclass
class EarlyCandidate:
    ticker: str
    name: str
    sector: str
    industry: str
    price: float
    market_cap_b: float
    early_score: float
    stage: str
    trailing_12m: float
    dist_from_base: float | None
    revision_score: float | None
    growth_est: float | None
    accumulation: float
    rs_turn: bool | None
    vol_contraction: float
    recency: bool
    cohort: str | None = None
    why_now: str = ""
    weeks_on_list: int = 1
    change: str = "new"
    is_seed: bool = False
    verdict: str = ""
    dist_from_high: float | None = None


@dataclass
class EarlyScanResult:
    date: str
    universe_size: int
    candidates: list[EarlyCandidate]
    cohorts: list[Cohort]
    dropped: list[str] = field(default_factory=list)
    watchlist: list[EarlyCandidate] = field(default_factory=list)


@dataclass
class EarlyTriggerResult:
    date: str
    fired: list[dict]


# ─── Scanner ───


class EarlyScanner:
    """Orchestrator for the early-stage ("pre-momentum") scan."""

    def __init__(self, db_path: Path | str | None = None):
        self.store = EarlyDataStore(db_path)
        self._info_cache: dict[str, dict] = {}

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "EarlyScanner":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # Overridable for offline tests.
    def _fetch_info(self, ticker: str) -> dict:
        return _get_yf_info(ticker, self._info_cache)

    def _fetch_fundamentals(self, ticker: str) -> tuple[float | None, float | None]:
        try:
            t = yf.Ticker(ticker)
            rev = revision_inflection(t.eps_revisions)
            growth = earnings_growth_estimate(t.earnings_estimate)
            return rev, growth
        except Exception as e:
            logger.debug("Fundamentals fetch failed for %s: %s", ticker, e)
            return None, None

    def _build_seed_candidate(
        self, ticker: str, df, bench_df, cascade_set: set[str]
    ) -> EarlyCandidate:
        """Build an always-shown watchlist entry for a seeded name (v2, gate-free).

        Seeds bypass every filter — the anti-momentum ceiling, the market-cap cap,
        the theme filter — so a name you care about is in every scan. The honesty
        comes from `verdict`, which states whether it is actually base-stage,
        re-basing, recovering, or just extended momentum.
        """
        stage = weinstein_stage(df)
        r12 = momentum_return_2_12(df)
        r6 = recent_return(df) if r12 is None else None
        pullback = distance_from_52w_high(df)  # positive = below the 52w high
        reaccum = reaccumulation_base(df)
        info = self._fetch_info(ticker)
        mcap_b = float(info.get("marketCap") or 0) / 1e9
        recency = _is_recent_listing(info)
        accum = accumulation_score(df)
        volc = volatility_contraction(df)
        rs_turn = rs_line_new_high(df, bench_df) if bench_df is not None else None
        revision, growth = self._fetch_fundamentals(ticker)
        score = early_composite_score(
            accum, rs_turn, stage, volc,
            fundamental_gate_score(revision, growth), headroom_component(mcap_b),
        )
        return EarlyCandidate(
            ticker=ticker,
            name=info.get("shortName") or info.get("longName") or ticker,
            sector=info.get("sector", "Unknown"),
            industry=info.get("industry", ""),
            price=float(df["Close"].iloc[-1]),
            market_cap_b=mcap_b,
            early_score=score,
            stage=stage,
            trailing_12m=r12 if r12 is not None else (r6 or 0.0),
            dist_from_base=base_proximity(df),
            revision_score=revision,
            growth_est=growth,
            accumulation=accum,
            rs_turn=rs_turn,
            vol_contraction=volc,
            recency=recency,
            cohort=None,
            why_now=_why_now(rs_turn, accum, volc, stage, recency, revision),
            is_seed=True,
            verdict=_seed_verdict(stage, pullback, reaccum),
            dist_from_high=(-pullback if pullback is not None else None),
        )

    def run_scan(
        self,
        *,
        universe: list[str] | None = None,
        fetch: bool = True,
        persist: bool = True,
        momentum_tier12: set[str] | None = None,
    ) -> EarlyScanResult:
        """Full early scan. See module docstring for the pipeline.

        Args:
            universe: explicit ticker list (skips the wide-universe fetch).
            fetch: if False, read OHLCV from the SQLite cache only (offline/tests).
            persist: write early_state to SQLite.
            momentum_tier12: explicit "too late" set (else read momentum radar.db).
        """
        today = date.today().isoformat()

        tickers = universe if universe is not None else sorted(
            set(get_wide_us_universe()) | set(_load_seeds())
        )

        # 1. OHLCV (+ benchmark)
        if fetch:
            ohlcv = self.store.fetch_ohlcv(tickers + [BENCHMARK], period=DEFAULT_PERIOD)
        else:
            ohlcv = {tk: df for tk in (tickers + [BENCHMARK])
                     if (df := self.store.load_cached_ohlcv(tk)) is not None}
        bench_df = ohlcv.pop(BENCHMARK, None)
        if bench_df is None:
            logger.warning("No benchmark (%s) data — relative-strength tells disabled", BENCHMARK)

        # 2. Anti-momentum ceiling: names already on momentum Tier 1/2 are "too late".
        tier12 = momentum_tier12 if momentum_tier12 is not None else _load_momentum_tier12()
        logger.info("Anti-momentum exclusions (Tier 1/2): %d", len(tier12))

        cascade_cfg = load_cascades()
        cascade_set = _cascade_tickers(cascade_cfg)
        seed_set = set(_load_seeds())

        # 2b. Seed watchlist (v2): seeded names are ALWAYS shown, gate-free, with an
        #     honest verdict — so a name you care about (e.g. IREN) is never invisible,
        #     even when it is already extended or too large for the discovery band.
        watchlist: list[EarlyCandidate] = []
        for tk in sorted(seed_set):
            df = ohlcv.get(tk)
            if df is None or len(df) < MIN_BARS:
                continue
            try:
                watchlist.append(self._build_seed_candidate(tk, df, bench_df, cascade_set))
            except Exception as e:
                logger.debug("Seed watchlist error for %s: %s", tk, e)
        watchlist.sort(key=lambda c: c.early_score, reverse=True)

        # 3. Cheap pass over the whole universe -> technical survivors.
        #    Seeds are handled by the watchlist above, so skip them here.
        survivors: list[dict] = []
        for tk, df in ohlcv.items():
            if tk in seed_set or len(df) < MIN_BARS:
                continue
            try:
                stage = weinstein_stage(df)
                r12 = momentum_return_2_12(df)
                r6 = recent_return(df) if r12 is None else None
                if tk in tier12:
                    continue
                reaccum = False
                if trailing_ceiling_breached(r12, r6):
                    # Door-2 (v2): a cascade name that ran but is now re-basing is
                    # admitted as a re-accumulation candidate; all else is rejected
                    # by the anti-momentum ceiling (12m, or 6m for short history).
                    if tk in cascade_set and reaccumulation_base(df):
                        reaccum, stage = True, "REACCUM_BASE"
                    else:
                        continue
                # Drop non-base stages, EXCEPT short-history names (possible recent
                # spins/IPOs): defer their stage judgment to the heavy pass, where
                # .info confirms recency and passes_gate's recency override applies.
                elif (
                    stage not in ("STAGE1_BASE", "STAGE1_2_TURN")
                    and len(df) >= RECENT_LISTING_BARS
                ):
                    continue
                dist = base_proximity(df)
                adv = float((df["Close"] * df["Volume"]).tail(20).mean())
                survivors.append({"ticker": tk, "df": df, "stage": stage,
                                  "r12": r12 or 0.0, "dist": dist, "adv": adv,
                                  "reaccum": reaccum})
            except Exception as e:
                logger.debug("Cheap pass error for %s: %s", tk, e)
        logger.info("Cheap pass: %d survivors of %d", len(survivors), len(ohlcv))

        # 4. Heavy pass (survivors only): .info + revisions + full gate + score.
        candidates: list[EarlyCandidate] = []
        for s in survivors:
            tk, df = s["ticker"], s["df"]
            try:
                info = self._fetch_info(tk)
                mcap_b = float(info.get("marketCap") or 0) / 1e9
                recency = _is_recent_listing(info)
                if not theme_allowed(
                    sector=info.get("sector"), industry=info.get("industry"),
                    in_cascade=tk in cascade_set, in_seeds=False,
                ):
                    continue  # theme focus (v2): drop Financials/Real Estate; narrow Materials
                if not passes_gate(
                    trailing_12m=s["r12"], on_momentum_tier12=False, market_cap_b=mcap_b,
                    stage=s["stage"], dist_from_base=s["dist"], avg_dollar_vol=s["adv"],
                    recency=recency, reaccum=s.get("reaccum", False),
                ):
                    continue
                revision, growth = self._fetch_fundamentals(tk)
                rs_turn = rs_line_new_high(df, bench_df) if bench_df is not None else None
                accum = accumulation_score(df)
                volc = volatility_contraction(df)
                score = early_composite_score(
                    accum, rs_turn, s["stage"], volc,
                    fundamental_gate_score(revision, growth), headroom_component(mcap_b),
                )
                candidates.append(EarlyCandidate(
                    ticker=tk,
                    name=info.get("shortName") or info.get("longName") or tk,
                    sector=info.get("sector", "Unknown"),
                    industry=info.get("industry", ""),
                    price=float(df["Close"].iloc[-1]),
                    market_cap_b=mcap_b,
                    early_score=score,
                    stage=s["stage"],
                    trailing_12m=s["r12"],
                    dist_from_base=s["dist"],
                    revision_score=revision,
                    growth_est=growth,
                    accumulation=accum,
                    rs_turn=rs_turn,
                    vol_contraction=volc,
                    recency=recency,
                    why_now=_why_now(rs_turn, accum, volc, s["stage"], recency, revision),
                ))
            except Exception as e:
                logger.debug("Heavy pass error for %s: %s", tk, e)

        # 5. Cohorts emerge from all scored names; a confirmed cohort (2+ peers
        #    basing together) lends a conviction bonus that can rescue a borderline name.
        scored_cohorts = group_into_cohorts(candidates, cascade_cfg)
        apply_cohort_bonus(candidates, scored_cohorts)

        # 6. Threshold + rank + change detection.
        kept = [c for c in candidates if c.early_score >= DEFAULT_SCORE_THRESHOLD]
        kept.sort(key=lambda c: c.early_score, reverse=True)
        prev = self.store.load_early_state()
        kept_tickers = {c.ticker for c in kept}
        for c in kept:
            p = prev.get(c.ticker)
            c.weeks_on_list = (p["weeks_on_list"] + 1) if p else 1
            c.change = "unchanged" if p else "new"
        dropped = [t for t in prev if t not in kept_tickers]

        if persist:
            self.store.save_early_state([_to_state(c, prev, today) for c in kept])

        # Re-group on the surfaced set so reported cohort counts match the rows shown.
        report_cohorts = group_into_cohorts(kept, cascade_cfg)
        return EarlyScanResult(
            date=today,
            universe_size=len(ohlcv),
            candidates=kept,
            cohorts=report_cohorts,
            dropped=dropped,
            watchlist=watchlist,
        )

    def run_daily_triggers(self) -> EarlyTriggerResult:
        """Flag base-breakout firings on existing candidates — the 'September' moment."""
        today = date.today().isoformat()
        fired: list[dict] = []
        for tk in self.store.load_early_state():
            df = self.store.load_cached_ohlcv(tk)
            if df is None or len(df) < _MIN_TRIGGER_BARS:
                continue
            bp = base_breakout(df)
            if bp in ("broke_out", "breaking"):
                fired.append({
                    "ticker": tk,
                    "base_status": bp,
                    "price": float(df["Close"].iloc[-1]),
                    "note": "Base breakout on elevated volume — probe-to-Stage-2 trigger.",
                })
        return EarlyTriggerResult(date=today, fired=fired)


# ─── Helpers ───


def _to_state(c: EarlyCandidate, prev: dict[str, dict], today: str) -> dict:
    p = prev.get(c.ticker)
    return {
        "ticker": c.ticker,
        "early_score": c.early_score,
        "stage": c.stage,
        "trailing_12m": c.trailing_12m,
        "dist_from_base": c.dist_from_base,
        "market_cap_b": c.market_cap_b,
        "revision_score": c.revision_score,
        "growth_est": c.growth_est,
        "cohort": c.cohort,
        "accumulation": c.accumulation,
        "rs_turn": 1 if c.rs_turn else 0,
        "vol_contraction": c.vol_contraction,
        "recency": "spin/ipo<18mo" if c.recency else "",
        "weeks_on_list": c.weeks_on_list,
        "first_seen": p["first_seen"] if p else today,
        "last_seen": today,
    }


def _why_now(
    rs_turn: bool | None, accumulation: float, vol_contraction: float,
    stage: str, recency: bool, revision: float | None,
) -> str:
    bits: list[str] = []
    if rs_turn:
        bits.append("RS new-high pre-price")
    if accumulation >= 0.6:
        bits.append("OBV up on flat base")
    if vol_contraction >= 0.5:
        bits.append("vol squeeze")
    if stage == "STAGE1_2_TURN":
        bits.append("Stage 1->2 turn")
    if revision is not None and revision > 0:
        bits.append("revisions up")
    if recency:
        bits.append("recent spin/IPO")
    return "; ".join(bits) or "base-stage setup"


def _cascade_tickers(cfg: CascadeConfig) -> set[str]:
    """All tickers referenced by any curated cascade tier."""
    return {tk for c in cfg.cascades for tier in c.tiers for tk in tier.tickers}


def _seed_verdict(stage: str, pullback: float | None, reaccum: bool) -> str:
    """Honest one-line read for a watchlist (seeded) name. `pullback` is positive
    below the 52w high (0.20 = 20% below)."""
    if reaccum:
        return "RE-BASE forming — watch for breakout trigger"
    if pullback is None:
        return "watch — insufficient history"
    if pullback <= 0.05:
        return "EXTENDED — momentum, not early"
    if stage == "STAGE2":
        if pullback >= 0.15:
            return "RECOVERING — not a base yet"
        return "EXTENDED — momentum, not early"
    if stage == "STAGE1_BASE":
        return "BASE — early candidate"
    if stage == "STAGE1_2_TURN":
        return "TURN — base breaking, watch"
    if stage == "STAGE4":
        return "DOWNTREND — avoid"
    return "watch"


def _load_seeds(path: Path = SEEDS_PATH) -> list[str]:
    try:
        data = yaml.safe_load(path.read_text())
        return list(data.get("seeds", []) or [])
    except (FileNotFoundError, AttributeError):
        return []


def _load_momentum_tier12() -> set[str]:
    """Tickers on momentum Tier 1/2 (the 'too late' set). Empty if momentum never ran."""
    try:
        store = MomentumDataStore()
        state = store.load_scan_state()
        store.close()
        return {t for t, s in state.items() if s.get("tier") in (1, 2)}
    except Exception as e:
        logger.warning("Could not read momentum scan_state (%s) — no exclusions", e)
        return set()


def _is_recent_listing(info: dict, months: int = 18) -> bool:
    ts = info.get("firstTradeDateMilliseconds") or info.get("firstTradeDateEpochUtc")
    if not ts:
        return False
    try:
        seconds = ts / 1000 if ts > 1e12 else ts
        first = datetime.fromtimestamp(seconds, tz=timezone.utc).date()
    except (ValueError, OSError, OverflowError, TypeError):
        return False
    return (date.today() - first).days <= int(months * 30.5)


def _get_yf_info(ticker: str, cache: dict[str, dict]) -> dict:
    """Get yfinance .info with in-memory caching (mirrors momentum/scanner.py)."""
    if ticker in cache:
        return cache[ticker]
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    cache[ticker] = info
    return info
