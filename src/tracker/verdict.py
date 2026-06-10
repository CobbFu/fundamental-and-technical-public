"""Verdict composition + flag detection — regime-gated.

Implements the project's regime-gated technical framework: mean-reversion
archetypes plus the trend-following archetypes added after the SNDK forensic.

Architecture:

    compose_verdict(daily, weekly)
        │
        ├─ regime_gate(daily, weekly) -> True (Stage 2) | False (mean-reversion)
        │
        ├─ Stage 2 path:
        │     1. is_ep_probe(daily)             → ep_probe
        │     2. is_stage2_continuation(daily)  → stage2_add
        │     3. is_climax_top(daily)           → hold_tighten (Stage 2 in climax)
        │     4. _stage2_first_trim(daily)      → trim (broke 20-EMA on volume)
        │     5. default                        → hold
        │
        └─ Mean-reversion path:
              existing logic — parabolic / mid-trend pullback / decision zone

The regime gate is the single decision point that branches the methodology.
The `regime` field on `LastRefresh` records which path fired so the digest
can show a mode banner.

Pure functions — no I/O, no TV calls. All inputs are TimeframeRead instances
with optional trend-following derived fields populated by /ta-read.
"""

from __future__ import annotations

from src.tracker.models import (
    VERDICT_CONSERVATISM,
    Flag,
    Regime,
    TimeframeRead,
    Verdict,
)

# ---------------------------------------------------------------------------
# Flags — emitted for any read regardless of regime.
# ---------------------------------------------------------------------------


def detect_flags(read: TimeframeRead) -> list[Flag]:
    """Emit machine-readable tags for noteworthy conditions on this timeframe."""
    flags: list[Flag] = []
    tf = read.timeframe.upper()

    # Parabolic trifecta: RSI > 80 + price > +50% over EMA200 + price > BB upper.
    ema200 = read.ema.get(200)
    bb_upper = read.bb.get("upper")
    if (
        ema200 is not None
        and bb_upper is not None
        and read.rsi > 80.0
        and ema200 > 0
        and (read.price - ema200) / ema200 > 0.50
        and read.price > bb_upper
    ):
        flags.append(f"parabolic_trifecta_{tf}")

    # Weekly RSI extreme — even without the full trifecta this is rare.
    if tf == "1W" and read.rsi >= 80.0:
        flags.append("weekly_rsi_extreme")

    # EMA stack break: in a previously bullish stack, price crossed below EMA20.
    ema20 = read.ema.get(20)
    ema50 = read.ema.get(50)
    if (
        ema20 is not None
        and ema50 is not None
        and ema200 is not None
        and ema20 > ema50 > ema200
        and read.price < ema20
    ):
        flags.append(f"ema_stack_break_{tf}")

    # Stage 2 trend-following flags. Cheap to compute, surfaced for visibility.
    if read.return_4w_pct is not None and read.return_4w_pct > 40.0:
        flags.append(f"climax_top_{tf}")
    if read.consecutive_up_days is not None and read.consecutive_up_days >= 3:
        flags.append(f"three_up_days_{tf}")

    return flags


# ---------------------------------------------------------------------------
# Regime gate.
# ---------------------------------------------------------------------------


def regime_gate(
    daily: TimeframeRead | None, weekly: TimeframeRead | None
) -> bool:
    """Return True iff the stock is in confirmed Stage 2.

    v4 (2026-05-15) — calibrated against NVDA Jan-May 2023 mission gate:
      - Daily price > daily 200-EMA
      - Daily 50-EMA > daily 200-EMA (proxy for 200-EMA rising for 8+ weeks)
      - Weinstein Stage 2 structure: price > 30-WMA AND 30-WMA rising.
        Replaces the v2 "12m return > 20%" rule which locked out NVDA Jan 2023
        emerging from the −38% 2022 bear. The 12m trailing-return test is
        backward-looking and rejects every post-drawdown emerger. The 30-WMA
        structure check is forward-looking (is the trend resuming?).
      - Emergence test: price > price 26 weeks ago.
        Confirms the stock is actually higher than half a year prior — a
        Stage 1→Stage 2 transition signal. Permissive enough to admit names
        recovering from drawdowns; strict enough to reject dead-cat bounces.
      - Weekly price > weekly 200-EMA if weekly 200-EMA is available.

    Back-compat fallbacks: if v4 fields are missing (entries refreshed before
    2026-05-15), use the v2 fallback paths (12m return + "≥25% above 200-EMA").

    Missing data is treated conservatively (defers to mean-reversion path).
    """
    if daily is None:
        return False

    d_ema200 = daily.ema.get(200)
    d_ema50 = daily.ema.get(50)
    if d_ema200 is None or d_ema200 <= 0:
        return False
    if daily.price <= d_ema200:
        return False

    # Stage 2 structure check.
    #
    # v4 path (preferred): use 30-WMA + rising + 26w emergence. This is
    # Weinstein's textbook Stage 2 test and admits post-drawdown emergers
    # (NVDA Jan 2023: −38% trailing 12m + daily 50-EMA briefly below 200-EMA,
    # but 30-WMA had turned up and price > price 26 weeks ago — the genuine
    # Stage 1→2 transition signal).
    #
    # v2 fallback (when 30-WMA absent): require daily 50-EMA > 200-EMA as the
    # "200-EMA rising for ≥8w" proxy + 12m return > 20% or ≥25% above 200-EMA.
    # The 50>200 daily check is preserved on the fallback path because the v2
    # fallback lacks the 30-WMA confirmation.
    if daily.sma_30w is not None and daily.sma_30w_rising is not None:
        if daily.price <= daily.sma_30w:
            return False
        if not daily.sma_30w_rising:
            return False
    else:
        # v2 fallback path — keep the 50>200 daily check as the structural proxy.
        if d_ema50 is None or d_ema50 <= d_ema200:
            return False
        if daily.return_12m_pct is not None:
            if daily.return_12m_pct < 20.0:
                return False
        else:
            if (daily.price - d_ema200) / d_ema200 < 0.25:
                return False

    # v4 emergence test: today's price > price 26 weeks ago. Confirms genuine
    # Stage 1→2 transition rather than a dead-cat bounce. NVDA Jan 12 2023:
    # +10% over 26w (vs −38% over 12m — the 12m gate would have rejected, the
    # 26w gate catches the move into a +480% run). Skipped when field absent
    # (entries refreshed before 2026-05-15) to preserve back-compat.
    if daily.return_26w_pct is not None and daily.return_26w_pct <= 0.0:
        return False

    # Weekly confirmation when available.
    if weekly is not None:
        w_ema200 = weekly.ema.get(200)
        if w_ema200 is not None and w_ema200 > 0 and weekly.price <= w_ema200:
            return False

    return True


# ---------------------------------------------------------------------------
# Stage 2 archetypes.
# ---------------------------------------------------------------------------


def is_climax_top(daily: TimeframeRead) -> bool:
    """Minervini climax-top, v4 (2026-05-15) — three-condition AND gate.

    v2 fired on `return_4w_pct > 40%` alone. That rejected every Stage 2
    ignition in the backtest (BE Apr 14 +41%, SNDK Sep 4 +54%, NBIS Sep 10
    +77%) — the bars *starting* multi-month runs. The fix: fire only when the
    move is also showing *deceleration* signals, not just magnitude.

    All three conditions must fire to demote to hold_tighten:
      1. return_4w_pct > 40% (magnitude — the move is mature)
      2. RSI rolling below RSI-MA (momentum-of-momentum turning down)
      3. MACD histogram negative (trend strength fading)

    The BE Nov 19 2025 case correctly fires the veto (all three trigger →
    saved a −32% flush 2 days later). BE Apr 14 2026 does NOT fire (RSI rising,
    MACD positive expanding → veto held off → catches the +42% leg).

    Falls back to v2 behavior if RSI-MA or MACD data missing.
    """
    if daily.return_4w_pct is None:
        return False
    if daily.return_4w_pct <= 40.0:
        return False

    # v4 deceleration confirmation. If either signal is missing, conservatively
    # fall back to v2 (single-condition veto) to preserve back-compat behavior.
    rsi_rolling = daily.rsi_ma is not None and daily.rsi < daily.rsi_ma
    macd_hist = daily.macd.get("hist")
    macd_topping = macd_hist is not None and macd_hist < 0.0

    if daily.rsi_ma is None or macd_hist is None:
        # Back-compat: v2 single-condition behavior when data incomplete.
        return True

    return rsi_rolling and macd_topping


def is_stage2_continuation(daily: TimeframeRead) -> bool:
    """Tight lateral base above the rising 20-EMA + breakout on volume.

    The SNDK-killer archetype. Requires:
      - Climax veto passes (not >40% in 4w)
      - Price within +10%/-5% of 20-EMA (constructive, not extended)
      - Tight base: last 15-25 bars range ≤ 15% of price
      - Breakout volume ≥ 1.5x 20-day average
      - MACD histogram positive (trend confirmed)

    Crucially, RSI is *not* an input. RSI > 70 is welcomed.
    """
    if is_climax_top(daily):
        return False

    ema_20 = daily.ema.get(20)
    if ema_20 is None or ema_20 <= 0:
        return False

    # Constructive distance from the 20-EMA: not extended, not under it.
    if daily.price > ema_20 * 1.10:
        return False
    if daily.price < ema_20 * 0.95:
        return False

    if daily.base_range_pct is None or daily.base_range_pct > 0.15:
        return False

    if daily.volume_ratio is None or daily.volume_ratio < 1.5:
        return False

    macd_hist = daily.macd.get("hist")
    if macd_hist is None or macd_hist <= 0:
        return False

    return True


def is_ep_probe(daily: TimeframeRead) -> bool:
    """Episodic Pivot — catalyst-day entry, v4 (2026-05-15).

    v2 used `volume_ratio ≥ 5×`, intraday `range/ATR ≥ 2×`, and
    `close_in_top_quartile = True` (≥0.75), with a Stockbee veto on 3+
    consecutive up days. The retrospective backtest exposed three failures:

      1. The 5× volume threshold is calibrated for thin-tape small caps. On
         liquid mid/large caps (BE, SNDK, WDC, NVDA), real institutional-flow
         catalysts present as 2–5× because the rolling baseline already
         includes prior catalyst days. v4 replaces with a scale-invariant
         OR-condition: z-score ≥ 2.5σ OR dollar notional ≥ $1B.

      2. The intraday range/ATR test fails on earnings gaps where most of the
         move is in the overnight gap (NVDA Feb 23 2023: intraday range $0.86
         on a $7+ overnight gap). v4 uses gap-aware range:
         `max(high, prev_close) − min(low, prev_close)`.

      3. The 0.75 top-quartile threshold is brittle — NVDA Feb 23 2023 closed
         at 0.74 (1pp short) and was rejected. v4 calibrates to ≥0.70.

      4. The 3-up-days Stockbee veto rejected PLTR Feb 6 2024 (a textbook EP
         where the stock had been drifting up into the catalyst). v4 drops
         this veto and replaces it with a narrower "deferral rule": defer
         only when 4w return > 50% AND RSI > 80 — i.e., genuinely climactic
         pre-event runs, not normal drift.

    All v4 fields are optional with v2 fallbacks for back-compat.
    """
    # Volume catalyst — v4 OR-condition (z-score or notional), v2 fallback (5×).
    z_score = daily.volume_z_score
    notional = daily.volume_dollar_notional
    if z_score is not None or notional is not None:
        catalyst_vol = (z_score is not None and z_score >= 2.5) or (
            notional is not None and notional >= 1_000_000_000.0
        )
        if not catalyst_vol:
            return False
    elif daily.volume_ratio is None or daily.volume_ratio < 5.0:
        # v2 back-compat: no v4 volume data, fall through to the 5× test.
        return False

    # Range expansion — v4 gap-aware, v2 intraday fallback.
    gap_range_ratio = daily.gap_aware_range_atr_ratio
    if gap_range_ratio is not None:
        if gap_range_ratio < 2.0:
            return False
    elif daily.range_atr_ratio is None or daily.range_atr_ratio < 2.0:
        return False

    # Close position — v4 calibrated to ≥0.70 (was ≥0.75 boolean).
    close_pos = daily.close_position_in_range
    if close_pos is not None:
        if close_pos < 0.70:
            return False
    elif daily.close_in_top_quartile is not True:
        return False

    # v4 deferral rule (replaces the 3-up-days Stockbee veto). Defers only when
    # the pre-catalyst run is genuinely climactic. RSI threshold lives at 80
    # (rather than 75) because liquid mid-caps frequently hit 75 during normal
    # Stage 2 acceleration without being topping.
    if daily.return_4w_pct is not None and daily.return_4w_pct > 50.0 and daily.rsi > 80.0:
        return False

    return True


def is_vcp_setup(
    daily: TimeframeRead,
    *,
    min_contractions: int = 3,
    tightening_ratio: float = 0.70,
) -> bool:
    """Minervini Volatility Contraction Pattern — pre-breakout setup detector (v5).

    Fires when a stock is in the *forming* phase of a VCP, before the breakout
    triggers. Catches the setup weeks earlier than `is_vcp_breakout`, which
    requires the breakout itself to be underway.

    Required: 3+ progressively tighter contractions from the OHLCV history,
    each one ≤ 70% of the previous (default tightening_ratio). The contraction
    list lives in `daily.vcp_contractions`, populated by /ta-read from
    peak-to-trough analysis over the last ~12 weeks.

    Conservative on data: vcp_contractions is None or empty → returns False
    (falls through to v4 archetypes without disturbing the verdict logic).

    Args:
        daily: TimeframeRead with vcp_contractions populated.
        min_contractions: minimum number of pullback peaks required. Default 3.
        tightening_ratio: each contraction must be ≤ this fraction of the prior.
            Default 0.70 (each pullback 30%+ tighter than the previous).
    """
    contractions = daily.vcp_contractions
    if contractions is None or len(contractions) < min_contractions:
        return False

    # Contractions ordered most-recent first → walk pairwise, each must be
    # smaller than the one before it by at least the tightening ratio.
    # Convention: contractions[0] is the latest (smallest) pullback.
    for i in range(len(contractions) - 1):
        recent = contractions[i]
        prior = contractions[i + 1]
        if recent <= 0 or prior <= 0:
            return False
        if recent > prior * tightening_ratio:
            return False

    return True


def is_vcp_breakout(daily: TimeframeRead) -> bool:
    """Minervini Volatility Contraction Pattern breakout — v5 (2026-05-15).

    Fires when a VCP setup (3+ tightening contractions) is complete AND price
    is breaking out of the most recent pivot high on elevated volume. This is
    the actionable trigger; `is_vcp_setup` is the watching-phase precursor.

    Conditions:
      - VCP setup confirmed (see `is_vcp_setup`).
      - Price within +2% of (or above) the pivot high `vcp_pivot_high`.
      - Volume confirmation: volume_z_score ≥ 1.5σ OR volume_ratio ≥ 1.5×.
      - Climax veto inactive (caller routes parabolic names elsewhere).

    Conservative on data: any required field missing → returns False
    (falls back to Stage 2 Continuation / EP / Trend Pullback in priority order).
    """
    if not is_vcp_setup(daily):
        return False

    pivot = daily.vcp_pivot_high
    if pivot is None or pivot <= 0:
        return False

    # Price at or above the pivot, with small tolerance for the breakout bar
    if daily.price < pivot * 0.98:
        return False

    # Volume confirmation — accept either v4 z-score signal or v2 volume_ratio
    z = daily.volume_z_score
    vol_ratio = daily.volume_ratio
    has_z = z is not None and z >= 1.5
    has_ratio = vol_ratio is not None and vol_ratio >= 1.5
    if not (has_z or has_ratio):
        return False

    # Don't fire on top of a climactic move — caller's downstream logic also
    # handles this, but the early return keeps the priority chain consistent.
    if is_climax_top(daily):
        return False

    return True


def is_trend_pullback(daily: TimeframeRead) -> bool:
    """Trend Pullback re-entry — v4 (2026-05-15), new archetype.

    Solves the "missed the first leg, where do I add now?" problem. v2 had no
    answer for held positions after a missed ignition bar; this is exactly
    the case that tends to get missed (e.g. BE, SNDK at every pullback to the
    20-EMA after the initial leg). This archetype fires when a confirmed Stage 2 stock
    pulls back to its rising 20-EMA on declining volume and bounces.

    Conditions (all must hold):
      - Stage 2 regime already confirmed (caller responsibility — only invoked
        inside the trend-following branch).
      - Climax veto inactive.
      - Today's price within ±2% of the 20-EMA (close to the dynamic support).
      - RSI in 45–60 zone (reset, not extended, not weak).
      - Today's volume_ratio ≥ 1.0 (the bounce day has at least average vol).
      - MACD histogram non-negative (momentum at least not worsening).

    Conservative on data: any missing field → returns False (falls through to
    hold).
    """
    if is_climax_top(daily):
        return False

    ema_20 = daily.ema.get(20)
    if ema_20 is None or ema_20 <= 0:
        return False

    # Within ±2% of the rising 20-EMA — the dynamic support tag.
    distance_pct = (daily.price - ema_20) / ema_20
    if distance_pct < -0.02 or distance_pct > 0.02:
        return False

    # RSI reset zone — not weak (post-flush) and not extended (still in trend).
    if not (45.0 <= daily.rsi <= 60.0):
        return False

    # Bounce-day volume — the move needs participation, not a drift.
    if daily.volume_ratio is None or daily.volume_ratio < 1.0:
        return False

    # MACD must not be deteriorating. Histogram non-negative = momentum at
    # least flat or turning back up.
    macd_hist = daily.macd.get("hist")
    if macd_hist is None or macd_hist < 0.0:
        return False

    return True


def _stage2_first_trim(daily: TimeframeRead) -> bool:
    """First trim signal inside Stage 2: close below 20-EMA on rising volume.

    Only fires if volume_ratio is populated. Volume-less close-below-20-EMA
    is just noise and shouldn't move the verdict.
    """
    ema_20 = daily.ema.get(20)
    if ema_20 is None:
        return False
    if daily.price >= ema_20:
        return False
    if daily.volume_ratio is None:
        return False
    return daily.volume_ratio > 1.5


def _stage2_exit_signal(daily: TimeframeRead) -> bool:
    """Stage 2 transitioning to Stage 3: close below 50-EMA on rising volume.

    This is the Weinstein "first real warning" — the 50-EMA is the structural
    line institutions defend. A volume-backed breach is the cue to exit. Falls
    back to False if volume data is missing.
    """
    ema_50 = daily.ema.get(50)
    if ema_50 is None:
        return False
    if daily.price >= ema_50:
        return False
    if daily.volume_ratio is None:
        return False
    return daily.volume_ratio > 1.5


def _is_weekly_late_stage(weekly: TimeframeRead | None) -> bool:
    """Weekly parabolic trifecta inside a Stage 2 stock = late-cycle warning.

    Stage 2 framework still says "don't exit blindly", but tighten the stops
    and stop adding. Worse than `hold`, better than `dont_chase`.
    """
    if weekly is None:
        return False
    w_ema200 = weekly.ema.get(200)
    w_bb_upper = weekly.bb.get("upper")
    if w_ema200 is None or w_ema200 <= 0 or w_bb_upper is None:
        return False
    return (
        weekly.rsi > 80.0
        and weekly.price > w_bb_upper
        and (weekly.price - w_ema200) / w_ema200 > 0.50
    )


def _trend_following_verdict(
    daily: TimeframeRead | None, weekly: TimeframeRead | None
) -> Verdict:
    """Stage 2 path: try archetypes in priority order, default to hold.

    Priority order (v5 — 2026-05-15):
      1. Exit signal (close < 50-EMA on volume)            → exit
      2. Episodic Pivot                                     → ep_probe
      3. Stage 2 Continuation                               → stage2_add
      4. VCP Breakout (v5 — un-stubbed)                     → vcp_buy
      5. Trend Pullback (v4 — missed-leg re-entry)          → stage2_add
      6. Climax top (4w > 40% + RSI rolling + MACD topping) → hold_tighten
      7. Weekly parabolic trifecta (late Stage 2)           → hold_tighten
      8. VCP setup forming (v5 — pre-breakout watch)        → watch
      9. First trim signal (< 20-EMA on volume)             → trim
     10. default                                            → hold
    """
    if daily is None:
        return "hold"

    # Exits checked first — if the stock is breaking down structurally, we
    # don't want a buy archetype false-firing on the same bar.
    if _stage2_exit_signal(daily):
        return "exit"

    # Highest-priority entries — fresh catalyst, then base-breakout, then VCP.
    if is_ep_probe(daily):
        return "ep_probe"
    if is_stage2_continuation(daily):
        return "stage2_add"
    if is_vcp_breakout(daily):
        return "vcp_buy"

    # Trend Pullback (v4) — the missed-first-leg re-entry. Fires after the
    # primary entry archetypes so we don't double-count the same bar.
    if is_trend_pullback(daily):
        return "stage2_add"

    # Late-stage warnings — Stage 2 intact but trail tightly, no add.
    if is_climax_top(daily):
        return "hold_tighten"
    if _is_weekly_late_stage(weekly):
        return "hold_tighten"

    # VCP setup forming — pre-breakout watch. Fires after the late-stage
    # warnings so a climactic name doesn't get a misleading "watch" verdict.
    if is_vcp_setup(daily):
        return "watch"

    # First trim signal — 20-EMA broken on volume but 50-EMA still above.
    if _stage2_first_trim(daily):
        return "trim"

    # Default within Stage 2: hold the trend.
    return "hold"


# ---------------------------------------------------------------------------
# Mean-reversion archetypes (existing logic, unchanged).
# ---------------------------------------------------------------------------


def _verdict_for_timeframe(read: TimeframeRead) -> Verdict:
    """Apply the mean-reversion framework to a single timeframe.

    Mirrors the three-archetype matrix in `ta-read/SKILL.md` section 6.
    """
    ema200 = read.ema.get(200)
    ema20 = read.ema.get(20)
    ema50 = read.ema.get(50)
    bb_upper = read.bb.get("upper")
    bb_basis = read.bb.get("basis")

    # Parabolic hard rule — applied per timeframe.
    if (
        ema200 is not None
        and bb_upper is not None
        and read.rsi > 80.0
        and ema200 > 0
        and (read.price - ema200) / ema200 > 0.50
        and read.price > bb_upper
    ):
        return "dont_chase"

    clean_bullish = (
        ema20 is not None
        and ema50 is not None
        and ema200 is not None
        and read.price > ema20 > ema50 > ema200
    )
    clean_bearish = (
        ema20 is not None
        and ema50 is not None
        and ema200 is not None
        and read.price < ema20 < ema50 < ema200
    )

    if clean_bearish:
        return "exit"

    if clean_bullish:
        assert ema200 is not None
        distance_pct = (read.price - ema200) / ema200
        if distance_pct > 0.50 and read.rsi >= 70.0:
            return "hold_tighten"
        if 55.0 <= read.rsi <= 70.0 and bb_upper is not None and read.price <= bb_upper:
            return "watch"
        if read.rsi >= 60.0:
            return "hold"
        return "hold"

    stack_broken = (
        ema20 is not None
        and ema50 is not None
        and ema200 is not None
        and read.price < ema20
        and read.price > ema50
        and ema50 > ema200
    )
    if stack_broken:
        if 45.0 <= read.rsi <= 55.0:
            return "watch"
        if read.rsi < 45.0:
            return "hold_tighten"
        return "hold_tighten"

    bb_lower = read.bb.get("lower")
    if read.rsi < 30.0 and bb_lower is not None and read.price < bb_lower:
        return "watch"

    if bb_basis is not None and read.price < bb_basis:
        return "hold_tighten"
    return "hold"


def _mean_reversion_verdict(
    daily: TimeframeRead | None, weekly: TimeframeRead | None
) -> Verdict:
    """Existing logic — take the more conservative of the two timeframes."""
    candidates: list[Verdict] = []
    if daily is not None:
        candidates.append(_verdict_for_timeframe(daily))
    if weekly is not None:
        candidates.append(_verdict_for_timeframe(weekly))
    if not candidates:
        return "hold"
    return min(candidates, key=VERDICT_CONSERVATISM.index)


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def compose_verdict(
    daily: TimeframeRead | None, weekly: TimeframeRead | None
) -> tuple[Verdict, list[Flag]]:
    """Return (verdict, flags). The regime is recovered by `compose_verdict_full`."""
    verdict, flags, _ = compose_verdict_full(daily, weekly)
    return verdict, flags


def compose_verdict_full(
    daily: TimeframeRead | None, weekly: TimeframeRead | None
) -> tuple[Verdict, list[Flag], Regime]:
    """Branch on the regime gate, return verdict + flags + regime label.

    Callers that need to record the regime on LastRefresh use this. Existing
    callers using compose_verdict() get the 2-tuple shape unchanged.
    """
    flags: list[Flag] = []
    if daily is not None:
        flags.extend(detect_flags(daily))
    if weekly is not None:
        flags.extend(detect_flags(weekly))

    in_stage2 = regime_gate(daily, weekly)

    if in_stage2:
        verdict = _trend_following_verdict(daily, weekly)
        flags.append("regime_stage2")
        return verdict, flags, "stage2"
    else:
        verdict = _mean_reversion_verdict(daily, weekly)
        flags.append("regime_mean_reversion")
        return verdict, flags, "mean_reversion"


def verdict_changed(new: Verdict, prev: Verdict | None) -> bool:
    """First refresh (no prior verdict) is always treated as changed."""
    if prev is None:
        return True
    return new != prev
