"""Tests for verdict composition + flag detection.

Two regimes:
- Mean-reversion path (existing): uses _verdict_for_timeframe directly.
- Stage 2 trend-following path (added 2026-05-14): regime_gate branches to
  _trend_following_verdict. The WDC May 13 case anchors the late-Stage-2
  weekly-trifecta path: regime_gate fires (Stage 2 confirmed), weekly trifecta
  flags it as late-cycle, verdict = hold_tighten (tighten stops, not exit).
"""

from src.tracker.models import TimeframeRead
from src.tracker.verdict import (
    _verdict_for_timeframe,
    compose_verdict_full,
    detect_flags,
    is_climax_top,
    is_ep_probe,
    is_stage2_continuation,
    regime_gate,
    verdict_changed,
)


def _wdc_daily() -> TimeframeRead:
    """WDC daily read from 2026-05-13."""
    return TimeframeRead(
        timeframe="1D",
        price=488.74,
        ema={20: 429.18, 50: 366.02, 200: 234.69},
        rsi=70.18,
        macd={"line": 43.19, "signal": 37.93, "hist": 5.26},
        bb={"upper": 513.68, "basis": 423.16, "lower": 332.63},
    )


def _wdc_weekly() -> TimeframeRead:
    """WDC weekly read from 2026-05-13 — full parabolic trifecta."""
    return TimeframeRead(
        timeframe="1W",
        price=488.74,
        ema={20: 322.73, 50: 223.73, 200: 106.21},
        rsi=87.43,
        rsi_ma=80.03,
        macd={"line": 75.67, "signal": 58.26, "hist": 17.42},
        bb={"upper": 475.69, "basis": 306.34, "lower": 136.99},
    )


def test_wdc_daily_alone_is_hold_tighten() -> None:
    assert _verdict_for_timeframe(_wdc_daily()) == "hold_tighten"


def test_wdc_weekly_trifecta_is_dont_chase() -> None:
    assert _verdict_for_timeframe(_wdc_weekly()) == "dont_chase"


def test_wdc_weekly_trifecta_flag_emitted() -> None:
    flags = detect_flags(_wdc_weekly())
    assert "parabolic_trifecta_1W" in flags
    assert "weekly_rsi_extreme" in flags


def test_wdc_compose_under_new_framework_is_hold_tighten() -> None:
    """WDC May 13 — Stage 2 regime + weekly parabolic trifecta = hold_tighten.

    Pre-2026-05-14 framework returned dont_chase via the conservative-min rule.
    Post-2026-05-14 framework recognises WDC is in confirmed Stage 2 (daily
    above rising 200-EMA, +108% over 200-EMA), routes to trend-following, then
    the weekly trifecta late-stage warning downgrades to hold_tighten.
    The signal is the same — don't add, tighten stops — without the panic.
    """
    final, flags, regime = compose_verdict_full(_wdc_daily(), _wdc_weekly())
    assert final == "hold_tighten"
    assert regime == "stage2"
    assert "parabolic_trifecta_1W" in flags
    assert "regime_stage2" in flags


def test_mid_trend_pullback_archetype() -> None:
    """Clean stack, RSI 60, inside bands -> watch."""
    read = TimeframeRead(
        timeframe="1D",
        price=150.0,
        ema={20: 145.0, 50: 135.0, 200: 120.0},  # 25% above 200, < 50% (not parabolic)
        rsi=62.0,
        macd={"line": 1.5, "signal": 1.2, "hist": 0.3},
        bb={"upper": 158.0, "basis": 148.0, "lower": 138.0},
    )
    assert _verdict_for_timeframe(read) == "watch"


def test_decision_zone_archetype() -> None:
    """Stack partially broken (price below 20-EMA but above 50), RSI 50 -> watch."""
    read = TimeframeRead(
        timeframe="1D",
        price=140.0,
        ema={20: 145.0, 50: 130.0, 200: 110.0},
        rsi=50.0,
        macd={"line": 0.5, "signal": 0.8, "hist": -0.3},
        bb={"upper": 152.0, "basis": 142.0, "lower": 132.0},
    )
    assert _verdict_for_timeframe(read) == "watch"


def test_clean_bearish_is_exit() -> None:
    read = TimeframeRead(
        timeframe="1D",
        price=80.0,
        ema={20: 90.0, 50: 100.0, 200: 110.0},
        rsi=35.0,
        macd={"line": -2.0, "signal": -1.5, "hist": -0.5},
        bb={"upper": 105.0, "basis": 95.0, "lower": 85.0},
    )
    assert _verdict_for_timeframe(read) == "exit"


def test_oversold_bounce_setup() -> None:
    read = TimeframeRead(
        timeframe="1D",
        price=70.0,
        ema={20: 90.0, 50: 95.0, 200: 100.0},  # bearish stack would normally be exit
        rsi=25.0,
        macd={"line": -3.0, "signal": -2.0, "hist": -1.0},
        bb={"upper": 100.0, "basis": 90.0, "lower": 80.0},
    )
    # bearish stack overrides oversold detection — exit wins
    assert _verdict_for_timeframe(read) == "exit"


def test_ema_stack_break_flag() -> None:
    """Healthy uptrend that just lost the 20-EMA -> stack-break flag."""
    read = TimeframeRead(
        timeframe="1D",
        price=140.0,
        ema={20: 145.0, 50: 130.0, 200: 110.0},
        rsi=50.0,
        macd={"line": 0.0, "signal": 0.5, "hist": -0.5},
        bb={"upper": 150.0, "basis": 140.0, "lower": 130.0},
    )
    flags = detect_flags(read)
    assert "ema_stack_break_1D" in flags


def test_first_refresh_is_marked_changed() -> None:
    assert verdict_changed("hold", None) is True


def test_no_change_returns_false() -> None:
    assert verdict_changed("hold", "hold") is False


def test_change_returns_true() -> None:
    assert verdict_changed("trim", "hold") is True


# ---------------------------------------------------------------------------
# Regime gate + Stage 2 archetypes (added 2026-05-14).
# ---------------------------------------------------------------------------


def _stage2_uptrend_daily(**overrides: object) -> TimeframeRead:
    """Confirmed Stage 2 daily: clean stack, price 50% over 200-EMA."""
    defaults: dict[str, object] = dict(
        timeframe="1D",
        price=150.0,
        ema={20: 145.0, 50: 130.0, 200: 100.0},  # 50 > 200, stack rising
        rsi=65.0,
        macd={"line": 2.0, "signal": 1.5, "hist": 0.5},
        bb={"upper": 158.0, "basis": 148.0, "lower": 138.0},
    )
    defaults.update(overrides)
    return TimeframeRead(**defaults)  # type: ignore[arg-type]


def test_regime_gate_fires_on_clean_stage2_uptrend() -> None:
    assert regime_gate(_stage2_uptrend_daily(), None) is True


def test_regime_gate_fails_when_below_200ema() -> None:
    bear = _stage2_uptrend_daily(price=90.0)  # below 200-EMA
    assert regime_gate(bear, None) is False


def test_regime_gate_fails_when_50_below_200() -> None:
    """50 < 200 = death cross territory, not Stage 2."""
    death_cross = _stage2_uptrend_daily(ema={20: 110.0, 50: 105.0, 200: 115.0})
    assert regime_gate(death_cross, None) is False


def test_regime_gate_fails_when_too_close_to_200ema_without_12m() -> None:
    """Fallback path: needs ≥25% above 200-EMA when 12m return unknown."""
    too_close = _stage2_uptrend_daily(price=110.0, ema={20: 108.0, 50: 105.0, 200: 100.0})
    assert regime_gate(too_close, None) is False


def test_regime_gate_passes_when_12m_return_high() -> None:
    """12m return overrides the structural fallback."""
    fresh_breakout = _stage2_uptrend_daily(
        price=110.0,  # only 10% above 200-EMA
        ema={20: 108.0, 50: 105.0, 200: 100.0},
        return_12m_pct=45.0,  # but 12m return says it's a real trend
    )
    assert regime_gate(fresh_breakout, None) is True


def test_climax_top_fires_at_40pct_4w() -> None:
    daily = _stage2_uptrend_daily(return_4w_pct=42.0)
    assert is_climax_top(daily) is True


def test_climax_top_does_not_fire_below_threshold() -> None:
    daily = _stage2_uptrend_daily(return_4w_pct=35.0)
    assert is_climax_top(daily) is False


def test_climax_top_safe_default_when_data_missing() -> None:
    assert is_climax_top(_stage2_uptrend_daily()) is False


def test_stage2_continuation_fires_on_tight_base_breakout() -> None:
    daily = _stage2_uptrend_daily(
        price=146.0,  # within 10% of 20-EMA (145), not above by >10%
        return_4w_pct=15.0,
        base_range_pct=0.10,  # tight 10% base
        volume_ratio=1.8,  # breakout volume
    )
    assert is_stage2_continuation(daily) is True


def test_stage2_continuation_blocked_by_climax_veto() -> None:
    daily = _stage2_uptrend_daily(
        price=146.0,
        return_4w_pct=45.0,  # over climax threshold
        base_range_pct=0.10,
        volume_ratio=1.8,
    )
    assert is_stage2_continuation(daily) is False


def test_stage2_continuation_blocked_when_too_far_from_20ema() -> None:
    daily = _stage2_uptrend_daily(
        price=170.0,  # 17% above 20-EMA (145)
        return_4w_pct=15.0,
        base_range_pct=0.10,
        volume_ratio=1.8,
    )
    assert is_stage2_continuation(daily) is False


def test_stage2_continuation_blocked_by_loose_base() -> None:
    daily = _stage2_uptrend_daily(
        price=146.0,
        return_4w_pct=15.0,
        base_range_pct=0.20,  # 20% base = too loose
        volume_ratio=1.8,
    )
    assert is_stage2_continuation(daily) is False


def test_stage2_continuation_requires_breakout_volume() -> None:
    daily = _stage2_uptrend_daily(
        price=146.0,
        return_4w_pct=15.0,
        base_range_pct=0.10,
        volume_ratio=1.0,  # average volume only
    )
    assert is_stage2_continuation(daily) is False


def test_ep_probe_fires_on_clean_catalyst_day() -> None:
    daily = _stage2_uptrend_daily(
        volume_ratio=7.0,
        range_atr_ratio=2.5,
        close_in_top_quartile=True,
        consecutive_up_days=1,
    )
    assert is_ep_probe(daily) is True


def test_ep_probe_v4_no_longer_blocks_on_3_up_days() -> None:
    """v4 (2026-05-15) dropped the Stockbee 3-up-days veto.

    The veto rejected PLTR Feb 6 2024 (a textbook EP where the stock had
    drifted up 3 days into the catalyst). v4 replaces it with a narrower
    deferral rule: only veto when 4w return > 50% AND RSI > 80 — i.e.,
    genuinely climactic pre-event runs, not normal drift.
    """
    daily = _stage2_uptrend_daily(
        volume_ratio=7.0,
        range_atr_ratio=2.5,
        close_in_top_quartile=True,
        consecutive_up_days=3,  # would have blocked under v2
    )
    assert is_ep_probe(daily) is True


def test_ep_probe_v4_deferral_when_4w_50pct_and_rsi_80() -> None:
    """v4 deferral replaces the Stockbee veto — fires only on climactic runs."""
    daily = _stage2_uptrend_daily(
        rsi=82.0,  # over the 80 threshold
        volume_ratio=7.0,
        range_atr_ratio=2.5,
        close_in_top_quartile=True,
        return_4w_pct=55.0,  # over the 50 threshold
    )
    assert is_ep_probe(daily) is False


def test_ep_probe_needs_close_in_top_quartile() -> None:
    daily = _stage2_uptrend_daily(
        volume_ratio=7.0,
        range_atr_ratio=2.5,
        close_in_top_quartile=False,
        consecutive_up_days=1,
    )
    assert is_ep_probe(daily) is False


def test_compose_full_emits_stage2_add_when_archetype_fires() -> None:
    daily = _stage2_uptrend_daily(
        price=146.0,
        return_4w_pct=15.0,
        base_range_pct=0.10,
        volume_ratio=1.8,
    )
    verdict, flags, regime = compose_verdict_full(daily, None)
    assert verdict == "stage2_add"
    assert regime == "stage2"


def test_compose_full_routes_non_stage2_to_mean_reversion() -> None:
    """A stock below its 200-EMA hits the mean-reversion path."""
    daily = _stage2_uptrend_daily(price=90.0)  # below 200-EMA
    _, flags, regime = compose_verdict_full(daily, None)
    assert regime == "mean_reversion"
    assert "regime_mean_reversion" in flags


def test_compose_with_only_daily() -> None:
    """WDC daily alone — Stage 2 regime, no archetype fires (no derived OHLCV
    fields), no weekly trifecta available, falls to default `hold`.
    """
    final, _, regime = compose_verdict_full(_wdc_daily(), None)
    assert final == "hold"
    assert regime == "stage2"


def test_compose_with_no_data_defaults_hold_and_mean_reversion() -> None:
    """No data → regime gate fails → mean-reversion path → default hold."""
    final, flags, regime = compose_verdict_full(None, None)
    assert final == "hold"
    assert regime == "mean_reversion"
    assert "regime_mean_reversion" in flags


# ---------------------------------------------------------------------------
# v4 regime gate + archetype tests (added 2026-05-15).
# Each test anchors to a real bar from the 15-May v4 calibration sample.
# Evidence: bar-by-bar backtest of the v4 calibration sample.
# ---------------------------------------------------------------------------


def test_regime_gate_v4_passes_post_drawdown_emerger() -> None:
    """NVDA Jan 2023: −38% trailing 12m return rejected v2; v4 uses 30-WMA
    structure + 26-week emergence (price 26 weeks ago < price today) instead.

    This is the canonical CLAUDE.md mission case — if v4 can't admit this
    setup, the methodology fails its founding test.
    """
    nvda_jan_2023 = TimeframeRead(
        timeframe="1D",
        price=16.51,
        ema={20: 15.50, 50: 14.80, 200: 16.00},  # 50 > 200 (just barely)
        rsi=62.0,
        macd={"line": 0.5, "signal": 0.3, "hist": 0.2},
        bb={"upper": 16.80, "basis": 15.00, "lower": 13.20},
        return_12m_pct=-38.0,  # would have killed v2 regime gate
        sma_30w=14.50,  # price > 30-WMA ✓
        sma_30w_rising=True,  # 30-WMA turned up in late 2022 ✓
        return_26w_pct=10.0,  # price > price 26 weeks ago ✓
    )
    assert regime_gate(nvda_jan_2023, None) is True


def test_regime_gate_v4_rejects_dead_cat_bounce() -> None:
    """v4 emergence test rejects names where price 26 weeks ago > price today.

    Dead-cat bounces above the 200-EMA pass v2's structural fallback but fail
    v4's 26w emergence check — preventing false fires on broken stocks.
    """
    dead_cat = TimeframeRead(
        timeframe="1D",
        price=50.0,
        ema={20: 48.0, 50: 47.0, 200: 40.0},  # passes v2 structural test
        rsi=55.0,
        macd={"line": 0.5, "signal": 0.3, "hist": 0.2},
        bb={"upper": 55.0, "basis": 49.0, "lower": 43.0},
        sma_30w=52.0,  # 30-WMA above price = trending down
        sma_30w_rising=False,
        return_26w_pct=-25.0,  # price was higher 26 weeks ago — fails emergence
    )
    assert regime_gate(dead_cat, None) is False


def test_climax_top_v4_holds_off_when_momentum_accelerating() -> None:
    """BE Apr 14 2026: +41% 4w return BUT RSI rising + MACD positive expanding.
    v2 fired the veto on magnitude alone. v4 requires confirming deceleration.
    """
    be_apr_14 = _stage2_uptrend_daily(
        rsi=68.0,
        rsi_ma=60.0,  # RSI > RSI-MA → still accelerating
        macd={"line": 5.0, "signal": 4.0, "hist": 1.0},  # histogram positive expanding
        return_4w_pct=41.0,  # over the 40% magnitude threshold
    )
    assert is_climax_top(be_apr_14) is False


def test_climax_top_v4_fires_on_full_deceleration() -> None:
    """BE Nov 19 2025 (pre-flush): +57% 4w + RSI rolling + MACD topping.
    All three v4 conditions fire → veto correctly active, saved a −32% flush.
    """
    be_nov_19 = _stage2_uptrend_daily(
        rsi=78.0,
        rsi_ma=80.0,  # RSI < RSI-MA → rolling
        macd={"line": 5.0, "signal": 5.5, "hist": -0.5},  # histogram negative
        return_4w_pct=57.0,  # over magnitude threshold
    )
    assert is_climax_top(be_nov_19) is True


def test_ep_probe_v4_fires_on_z_score_alone() -> None:
    """BE Apr 14 2026: vol z-score 2.7σ on a 25M-vol bar against a 10M baseline.
    v2 fired only on volume_ratio ≥ 5× — BE missed at 2.5×. v4 catches via
    z-score (scale-invariant; works on liquid mid-caps).
    """
    be_apr_14 = _stage2_uptrend_daily(
        volume_z_score=2.7,
        gap_aware_range_atr_ratio=2.8,
        close_position_in_range=0.98,
    )
    assert is_ep_probe(be_apr_14) is True


def test_ep_probe_v4_fires_on_dollar_notional_alone() -> None:
    """SNDK Sep 4 2025: z-score 6σ ✓ AND notional $637M (below $1B floor).
    Either-or logic — z-score path fires.
    """
    sndk_sep_4 = _stage2_uptrend_daily(
        volume_z_score=6.0,
        volume_dollar_notional=637_000_000.0,
        gap_aware_range_atr_ratio=5.0,
        close_position_in_range=0.98,
    )
    assert is_ep_probe(sndk_sep_4) is True


def test_ep_probe_v4_fires_on_notional_when_z_score_low() -> None:
    """Liquid large-cap with smaller z-score but huge notional. Either-or."""
    big_notional = _stage2_uptrend_daily(
        volume_z_score=1.5,  # below 2.5σ
        volume_dollar_notional=8_000_000_000.0,  # $8B — well above $1B floor
        gap_aware_range_atr_ratio=2.5,
        close_position_in_range=0.85,
    )
    assert is_ep_probe(big_notional) is True


def test_ep_probe_v4_uses_gap_aware_range_for_earnings_gaps() -> None:
    """NVDA Feb 23 2023: intraday range $0.86 (failed v2's ≥2× ATR), but
    gap-aware range $3.13 = 2.93× ATR (passes v4). The fix is one rule.
    """
    nvda_feb_23 = _stage2_uptrend_daily(
        volume_z_score=7.55,
        range_atr_ratio=1.0,  # would have failed v2
        gap_aware_range_atr_ratio=2.93,  # v4 passes
        close_position_in_range=0.74,
    )
    # 0.74 is above v4's 0.70 calibrated threshold
    assert is_ep_probe(nvda_feb_23) is True


def test_ep_probe_v4_calibrated_top_q_threshold() -> None:
    """v4 calibrated top-Q to 0.70 from v2's 0.75. NVDA Feb 23 closed at 0.74."""
    bar_at_calibrated_threshold = _stage2_uptrend_daily(
        volume_z_score=3.0,
        gap_aware_range_atr_ratio=2.5,
        close_position_in_range=0.70,  # exactly at threshold
    )
    assert is_ep_probe(bar_at_calibrated_threshold) is True

    just_below = _stage2_uptrend_daily(
        volume_z_score=3.0,
        gap_aware_range_atr_ratio=2.5,
        close_position_in_range=0.69,
    )
    assert is_ep_probe(just_below) is False


def test_ep_probe_v4_v2_back_compat() -> None:
    """Entries refreshed before v4 lack volume_z_score / notional / gap-aware
    range / close_position_in_range. v4 verdict.py falls back to v2 fields
    when v4 fields are absent — no breakage.
    """
    v2_entry = _stage2_uptrend_daily(
        volume_ratio=7.0,           # v2 path: 7× ≥ 5×
        range_atr_ratio=2.5,         # v2 path: 2.5× ≥ 2×
        close_in_top_quartile=True,  # v2 path
        consecutive_up_days=1,
    )
    assert is_ep_probe(v2_entry) is True


def test_trend_pullback_fires_on_canonical_setup() -> None:
    """A held Stage 2 stock pulls back to its 20-EMA on a green volume day.
    The missed-first-leg re-entry — v4's new fourth Stage 2 archetype.
    """
    pullback = _stage2_uptrend_daily(
        price=145.5,  # within 2% of 20-EMA (145)
        rsi=52.0,  # in the 45-60 reset zone
        macd={"line": 1.5, "signal": 1.6, "hist": 0.1},  # histogram non-negative
        volume_ratio=1.2,  # bounce volume
        return_4w_pct=8.0,  # not climactic
    )
    from src.tracker.verdict import is_trend_pullback
    assert is_trend_pullback(pullback) is True


def test_trend_pullback_rejects_overbought_rsi() -> None:
    """RSI 65 = still extended, not a reset. No pullback entry."""
    not_reset = _stage2_uptrend_daily(
        price=145.5,
        rsi=65.0,  # above 60 zone
        macd={"line": 1.5, "signal": 1.6, "hist": 0.1},
        volume_ratio=1.2,
    )
    from src.tracker.verdict import is_trend_pullback
    assert is_trend_pullback(not_reset) is False


def test_trend_pullback_rejects_extended_from_20ema() -> None:
    """Price 10% above 20-EMA is not a pullback to support."""
    extended = _stage2_uptrend_daily(
        price=159.5,  # 10% above 20-EMA (145)
        rsi=55.0,
        macd={"line": 1.5, "signal": 1.6, "hist": 0.1},
        volume_ratio=1.2,
    )
    from src.tracker.verdict import is_trend_pullback
    assert is_trend_pullback(extended) is False


def test_compose_full_emits_ep_probe_on_v4_catalyst() -> None:
    """End-to-end: a v4-only catalyst (z-score + gap-aware) routes to ep_probe."""
    daily = _stage2_uptrend_daily(
        volume_z_score=3.5,
        volume_dollar_notional=2_500_000_000.0,
        gap_aware_range_atr_ratio=3.0,
        close_position_in_range=0.92,
    )
    verdict, flags, regime = compose_verdict_full(daily, None)
    assert verdict == "ep_probe"
    assert regime == "stage2"


# ---------------------------------------------------------------------------
# VCP morphology (v5 — 2026-05-15).
# ---------------------------------------------------------------------------


def test_vcp_setup_fires_on_three_tightening_contractions() -> None:
    """Canonical Minervini setup: 3 contractions, each ≤70% of previous."""
    from src.tracker.verdict import is_vcp_setup
    daily = _stage2_uptrend_daily(
        # Contractions ordered most-recent first → 4%, 7%, 12%, 18%.
        # Each one < 0.70 of the prior. Textbook VCP.
        vcp_contractions=[0.04, 0.07, 0.12, 0.18],
    )
    assert is_vcp_setup(daily) is True


def test_vcp_setup_rejects_widening_contractions() -> None:
    """If a later contraction is bigger than the previous, the pattern broke."""
    from src.tracker.verdict import is_vcp_setup
    daily = _stage2_uptrend_daily(
        vcp_contractions=[0.10, 0.07, 0.05],  # latest is WIDER, not tighter
    )
    assert is_vcp_setup(daily) is False


def test_vcp_setup_rejects_insufficient_contractions() -> None:
    """Need at least 3 contractions to call it a VCP."""
    from src.tracker.verdict import is_vcp_setup
    daily = _stage2_uptrend_daily(vcp_contractions=[0.04, 0.10])
    assert is_vcp_setup(daily) is False


def test_vcp_setup_rejects_when_data_missing() -> None:
    """No vcp_contractions on the payload → fall through (back-compat)."""
    from src.tracker.verdict import is_vcp_setup
    daily = _stage2_uptrend_daily()  # no contractions populated
    assert is_vcp_setup(daily) is False


def test_vcp_setup_respects_tightening_ratio() -> None:
    """Three contractions but the tightening isn't strict enough → no fire."""
    from src.tracker.verdict import is_vcp_setup
    # 10%, 9%, 8.5% — barely tighter, not the 70% step v5 requires.
    daily = _stage2_uptrend_daily(vcp_contractions=[0.085, 0.09, 0.10])
    assert is_vcp_setup(daily) is False


def test_vcp_breakout_fires_on_setup_plus_pivot_break_plus_volume() -> None:
    """The actionable trigger: setup confirmed + price clears pivot on volume."""
    from src.tracker.verdict import is_vcp_breakout
    daily = _stage2_uptrend_daily(
        price=152.0,                                # at/just above pivot
        vcp_contractions=[0.04, 0.07, 0.12],
        vcp_pivot_high=150.0,
        volume_z_score=2.0,                         # institutional volume on breakout
    )
    assert is_vcp_breakout(daily) is True


def test_vcp_breakout_rejects_when_price_below_pivot() -> None:
    """Setup is complete but price hasn't cleared the pivot yet — still watch, not buy."""
    from src.tracker.verdict import is_vcp_breakout
    daily = _stage2_uptrend_daily(
        price=140.0,                                # well below pivot
        vcp_contractions=[0.04, 0.07, 0.12],
        vcp_pivot_high=150.0,
        volume_z_score=2.0,
    )
    assert is_vcp_breakout(daily) is False


def test_vcp_breakout_rejects_when_volume_quiet() -> None:
    """Breakout requires confirmation — no volume = no fire."""
    from src.tracker.verdict import is_vcp_breakout
    daily = _stage2_uptrend_daily(
        price=152.0,
        vcp_contractions=[0.04, 0.07, 0.12],
        vcp_pivot_high=150.0,
        # No volume signals populated
    )
    assert is_vcp_breakout(daily) is False


def test_vcp_breakout_rejects_at_climax() -> None:
    """A VCP-shaped pattern in a climactic stock is exhaustion, not entry.

    Climax veto fires when all three: 4w return > 40%, RSI rolling BELOW its MA
    (i.e. momentum cooling), MACD histogram topping.
    """
    from src.tracker.verdict import is_vcp_breakout
    daily = _stage2_uptrend_daily(
        price=152.0,
        vcp_contractions=[0.04, 0.07, 0.12],
        vcp_pivot_high=150.0,
        volume_z_score=2.0,
        # Climax conditions: extended run, RSI cooling below MA, MACD topping
        return_4w_pct=55.0,
        rsi=66.0,
        rsi_ma=70.0,
        macd={"line": 2.0, "signal": 2.5, "hist": -0.5},
    )
    assert is_vcp_breakout(daily) is False


def test_compose_full_emits_vcp_buy_on_breakout() -> None:
    """End-to-end: a complete VCP breakout routes to vcp_buy verdict."""
    daily = _stage2_uptrend_daily(
        price=152.0,
        vcp_contractions=[0.04, 0.07, 0.12],
        vcp_pivot_high=150.0,
        volume_z_score=2.0,
    )
    verdict, _, regime = compose_verdict_full(daily, None)
    assert verdict == "vcp_buy"
    assert regime == "stage2"


def test_compose_full_emits_watch_on_vcp_setup() -> None:
    """VCP setup forming (no breakout yet) routes to watch — pre-trigger surfacing."""
    daily = _stage2_uptrend_daily(
        price=145.0,                                # well below pivot
        vcp_contractions=[0.04, 0.07, 0.12],
        vcp_pivot_high=150.0,
    )
    verdict, _, regime = compose_verdict_full(daily, None)
    assert verdict == "watch"
    assert regime == "stage2"
