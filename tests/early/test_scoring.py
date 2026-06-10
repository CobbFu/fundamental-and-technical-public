"""Unit tests for the early-scan gate + composite score."""

from src.early.scoring import (
    early_composite_score,
    headroom_component,
    passes_gate,
    theme_allowed,
)


def _gate(**overrides) -> bool:
    base = dict(
        trailing_12m=0.05,
        on_momentum_tier12=False,
        market_cap_b=5.0,
        stage="STAGE1_2_TURN",
        dist_from_base=0.05,
        avg_dollar_vol=1e8,
        recency=False,
    )
    base.update(overrides)
    return passes_gate(**base)


def test_gate_accepts_base_smallcap():
    assert _gate() is True


def test_gate_rejects_already_run():
    assert _gate(trailing_12m=0.90) is False


def test_gate_rejects_momentum_tier12():
    assert _gate(on_momentum_tier12=True) is False


def test_gate_rejects_out_of_band_cap():
    assert _gate(market_cap_b=300.0) is False
    assert _gate(market_cap_b=0.2) is False


def test_gate_rejects_illiquid():
    assert _gate(avg_dollar_vol=1e5) is False


def test_gate_rejects_extended_from_base():
    assert _gate(dist_from_base=0.50) is False


def test_gate_recency_override_for_nonbase_stage():
    assert _gate(stage="STAGE2", recency=True) is True
    assert _gate(stage="STAGE2", recency=False) is False


def test_headroom_monotonic_smaller_is_higher():
    assert headroom_component(2.0) > headroom_component(18.0)
    assert headroom_component(None) == 0.0


def test_score_in_range_and_high_when_all_fire():
    s = early_composite_score(1.0, True, "STAGE1_2_TURN", 1.0, 1.0, 1.0)
    assert 0.0 <= s <= 100.0
    assert s > 90.0


def test_score_low_when_nothing_fires():
    s = early_composite_score(0.0, False, "STAGE1_BASE", 0.0, 0.0, 0.0)
    assert s < 20.0


# ─── v2: theme focus filter ───


def test_theme_drops_financials_and_real_estate():
    assert theme_allowed(sector="Financial Services", industry="Banks - Regional",
                         in_cascade=False, in_seeds=False) is False
    assert theme_allowed(sector="Real Estate", industry="REIT - Healthcare",
                         in_cascade=False, in_seeds=False) is False


def test_theme_allows_core_sectors():
    assert theme_allowed(sector="Technology", industry="Semiconductors",
                         in_cascade=False, in_seeds=False) is True
    assert theme_allowed(sector="Industrials", industry="Electrical Equipment",
                         in_cascade=False, in_seeds=False) is True


def test_theme_membership_overrides_mislabeled_sector():
    # IREN: yfinance tags it Financial Services, but seed/cascade membership wins.
    assert theme_allowed(sector="Financial Services", industry="Capital Markets",
                         in_cascade=False, in_seeds=True) is True
    assert theme_allowed(sector="Financial Services", industry="Capital Markets",
                         in_cascade=True, in_seeds=False) is True


def test_theme_materials_is_narrow():
    assert theme_allowed(sector="Basic Materials", industry="Lithium",
                         in_cascade=False, in_seeds=False) is True
    assert theme_allowed(sector="Basic Materials", industry="Steel",
                         in_cascade=False, in_seeds=False) is False


# ─── v2: Door-2 re-accumulation gate path ───


def test_gate_reaccum_bypasses_trailing_and_stage():
    # A name that ran (high trailing) and is non-base passes when reaccum=True...
    assert _gate(trailing_12m=2.0, stage="REACCUM_BASE", reaccum=True) is True


def test_gate_reaccum_still_enforces_cap_and_liquidity():
    assert _gate(trailing_12m=2.0, stage="REACCUM_BASE", reaccum=True,
                 market_cap_b=300.0) is False
    assert _gate(trailing_12m=2.0, stage="REACCUM_BASE", reaccum=True,
                 avg_dollar_vol=1e5) is False


def test_gate_reaccum_still_rejects_momentum_tier12():
    assert _gate(trailing_12m=2.0, stage="REACCUM_BASE", reaccum=True,
                 on_momentum_tier12=True) is False
