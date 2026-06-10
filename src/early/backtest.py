"""Point-in-time backtest harness — the acid test (plan task 16).

Truncates cached OHLCV to a historical date and re-runs the early filter to ask:
"would this have flagged the known winners WHILE they were still in their base?"
This both validates the design and calibrates the thresholds — if the filter
cannot catch the five names we already know won, it is wrong (CLAUDE.md test).

Fundamentals are NOT point-in-time available from yfinance, so replay uses the
TECHNICAL gate only (trailing-return ceiling + Weinstein stage + base proximity).

Note on adjustment: the cached series is split/dividend-adjusted as of today, so a
historical level is back-adjusted by splits that occurred after `as_of`. This is
harmless here because every signal used in replay is RATIO-based (trailing_12m,
dist_from_base, RS) and thus scale-invariant. Adding a non-ratio signal would break
that invariant and reintroduce a subtle look-ahead.
"""

import logging

import numpy as np
import pandas as pd

from src.early.data import EarlyDataStore
from src.early.scanner import BENCHMARK, MIN_BARS
from src.early.scoring import MAX_DIST_FROM_BASE, trailing_ceiling_breached
from src.early.signals import (
    accumulation_score,
    base_proximity,
    recent_return,
    rs_line_new_high,
    volatility_contraction,
    weinstein_stage,
)
from src.momentum.signals import momentum_return_2_12

logger = logging.getLogger(__name__)

# Known multi-baggers + an approximate BASE date (before the run). Calibrate
# against data; these are best-guess from the methodology/session cases.
# Base dates verified against scan_history() catchable windows (2026-06-06): each is
# the last in-base date before the name went STAGE2. NOT the run-up dates from the
# methodology cheatsheet (those were already mid-run — Stage-2 continuation entries).
DEFAULT_WINNERS: dict[str, str] = {
    "SNDK": "2025-08-15",  # SanDisk — flat base before the run (spun Feb-2025)
    "BE": "2024-12-10",    # Bloom Energy — base before the Jan-2025 markup
    "WDC": "2025-06-13",   # Western Digital — base before the Jul-2025 run
    "MU": "2025-07-16",    # Micron — base before the Aug-2025 run
    "NBIS": "2025-04-24",  # Nebius — first base (+31% 6m); by Sept it was +358% (mid-run)
}

_STAGE_C = {"STAGE1_2_TURN": 1.0, "STAGE1_BASE": 0.6}


def replay_one(
    store: EarlyDataStore, ticker: str, as_of: str, bench_df: pd.DataFrame | None
) -> dict:
    """Re-run the technical filter on `ticker` using only data up to `as_of`."""
    df = store.load_cached_ohlcv(ticker, days=2000)
    if df is None:
        return {"ticker": ticker, "gate_pass": False, "reason": "no data"}

    as_of_ts = pd.Timestamp(as_of)
    df = df[df.index <= as_of_ts]  # strict — no look-ahead
    bench = bench_df[bench_df.index <= as_of_ts] if bench_df is not None else None
    if len(df) < MIN_BARS:
        return {"ticker": ticker, "gate_pass": False, "reason": "insufficient bars",
                "bars": len(df)}

    stage = weinstein_stage(df)
    r12 = momentum_return_2_12(df)
    r6 = recent_return(df) if r12 is None else None
    dist = base_proximity(df)
    gate = (
        not trailing_ceiling_breached(r12, r6)
        and stage in ("STAGE1_BASE", "STAGE1_2_TURN")
        and (dist is None or dist <= MAX_DIST_FROM_BASE)
    )
    rs = rs_line_new_high(df, bench)
    accum = accumulation_score(df)
    volc = volatility_contraction(df)
    tech = float(np.mean([accum, 1.0 if rs else 0.0, _STAGE_C.get(stage, 0.0), volc]) * 100)

    return {
        "ticker": ticker,
        "as_of": as_of,
        "gate_pass": bool(gate),
        "technical_score": round(tech, 1),
        "stage": stage,
        "trailing_12m": None if r12 is None else round(r12, 3),
        "dist_from_base": None if dist is None else round(dist, 3),
        "bars": len(df),
    }


def replay_at(
    store: EarlyDataStore, as_of: str, tickers: list[str], bench_df: pd.DataFrame | None
) -> list[dict]:
    """Replay the filter for many tickers at a single historical date."""
    return [replay_one(store, tk, as_of, bench_df) for tk in tickers]


def scan_history(
    store: EarlyDataStore,
    ticker: str,
    bench_df: pd.DataFrame | None,
    step_days: int = 21,
    lookback_days: int = 540,
) -> list[dict]:
    """Replay the filter month-by-month to reveal a name's CATCHABLE WINDOW.

    Shows, across history, the months where the technical gate would have flagged
    the name — i.e. how long the base lasted before the run. Used for calibration
    and to demonstrate the lead time the scanner would have given.
    """
    df = store.load_cached_ohlcv(ticker, days=2000)
    if df is None:
        return []
    sample = df.index[-lookback_days:][::step_days]
    return [replay_one(store, ticker, d.strftime("%Y-%m-%d"), bench_df) for d in sample]


def validate_known_winners(
    store: EarlyDataStore, winners: dict[str, str] | None = None, fetch: bool = True
) -> dict:
    """Acid test: how many known winners would the filter have caught in their base?

    Returns a calibration report. Verdict PASS requires >= 4 of 5 caught.
    """
    winners = winners or DEFAULT_WINNERS
    if fetch:
        store.fetch_ohlcv(list(winners) + [BENCHMARK], period="3y")
    bench = store.load_cached_ohlcv(BENCHMARK, days=2000)

    results = {tk: replay_one(store, tk, base_date, bench)
               for tk, base_date in winners.items()}
    caught = sum(1 for r in results.values() if r.get("gate_pass"))
    verdict = "PASS" if caught >= 4 else "RECALIBRATE"
    logger.info("Known-winner validation: %d/%d caught -> %s", caught, len(winners), verdict)
    return {"winners": results, "caught": caught, "total": len(winners), "verdict": verdict}
