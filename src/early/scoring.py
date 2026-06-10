"""Early-scan scoring + the hard gate (the anti-momentum ceiling).

The gate is a binary pre-filter that EXCLUDES — it never ranks. Its whole job is
to reject what momentum loves (already-run names) and keep only base-stage names
with headroom. Survivors are then ranked by the composite score.
"""

import numpy as np

# Gate bounds + score threshold — straw-men, calibrated by the backtest (plan task 16).
MAX_TRAILING_12M = 0.50         # reject anything already up >50% over 12m
MAX_RECENT_6M = 0.60            # short-history fallback ceiling (recent IPOs/spins)
HEADROOM_MIN_B = 1.0            # market-cap floor ($1B) — liquidity / not a shell
HEADROOM_MAX_B = 20.0           # market-cap ceiling ($20B) — 10-30x must be possible
MIN_DOLLAR_VOL = 5e6           # $5M avg daily dollar volume — tradable
MAX_DIST_FROM_BASE = 0.30       # reject if price has run >30% past its base high
DEFAULT_SCORE_THRESHOLD = 60.0  # minimum composite to surface as a candidate

_BASE_STAGES = ("STAGE1_BASE", "STAGE1_2_TURN")

# ─── Theme focus (v2) ───
# Only Financials + Real Estate are excluded; everything else is in. yfinance uses
# both "Financials" and "Financial Services" labels, so list both.
EXCLUDED_SECTORS = {"Financials", "Financial Services", "Real Estate"}
MATERIALS_SECTORS = {"Materials", "Basic Materials"}
# Materials is allowed only for the AI/EV-supply-chain slice, not commodity steel/chemicals.
MATERIALS_ALLOWED_KEYWORDS = (
    "lithium", "rare earth", "semiconductor", "specialty chemical", "copper",
)


def theme_allowed(
    *, sector: str | None, industry: str | None, in_cascade: bool, in_seeds: bool
) -> bool:
    """Theme focus filter (v2). Drop Financials/Real Estate; narrow Materials.

    Cascade or seed membership overrides the sector label — so a name like IREN that
    yfinance mislabels as "Financial Services" but is really AI-compute is NOT dropped.
    """
    if in_cascade or in_seeds:
        return True
    s = (sector or "").strip()
    if s in EXCLUDED_SECTORS:
        return False
    if s in MATERIALS_SECTORS:
        ind = (industry or "").lower()
        return any(k in ind for k in MATERIALS_ALLOWED_KEYWORDS)
    return True


def passes_gate(
    *,
    trailing_12m: float | None,
    on_momentum_tier12: bool,
    market_cap_b: float | None,
    stage: str,
    dist_from_base: float | None,
    avg_dollar_vol: float | None,
    recency: bool,
    reaccum: bool = False,
) -> bool:
    """Hard anti-momentum gate. ALL conditions must hold. Binary; excludes only.

    Door-1 (default): never-ran Stage-1 base. Door-2 (`reaccum=True`, v2): a name
    that RAN then re-based — skip the trailing-return and stage/dist checks, but
    still enforce the cap + liquidity (Door-2 is scoped to cascade names in-band).
    """
    if on_momentum_tier12:
        return False  # already on the momentum radar -> too late
    if not reaccum and trailing_12m is not None and trailing_12m >= MAX_TRAILING_12M:
        return False
    if market_cap_b is None or not (HEADROOM_MIN_B <= market_cap_b <= HEADROOM_MAX_B):
        return False
    if avg_dollar_vol is None or avg_dollar_vol < MIN_DOLLAR_VOL:
        return False
    if reaccum:
        return True  # re-accumulation base: cap + liquidity already cleared
    if stage not in _BASE_STAGES:
        # Recent spin/IPO with too little history for a clean stage read: allow.
        return bool(recency)
    if dist_from_base is not None and dist_from_base > MAX_DIST_FROM_BASE:
        return False
    return True


def trailing_ceiling_breached(r12: float | None, r6: float | None) -> bool:
    """Anti-momentum ceiling. True = already run too far to be a base.

    Uses the 12-month return when available, else falls back to a 6-month return
    ceiling for short-history names (recent IPOs/spins) so a name that has already
    ripped in its first months is not mistaken for a base.
    """
    if r12 is not None:
        return r12 >= MAX_TRAILING_12M
    return r6 is not None and r6 >= MAX_RECENT_6M


def headroom_component(market_cap_b: float | None) -> float:
    """Map market cap within the band to [0, 1] — smaller = more headroom = higher."""
    if market_cap_b is None:
        return 0.0
    span = HEADROOM_MAX_B - HEADROOM_MIN_B
    return float(np.clip(1.0 - (market_cap_b - HEADROOM_MIN_B) / span, 0.0, 1.0))


def early_composite_score(
    accumulation: float,
    rs_turn: bool | None,
    stage: str,
    vol_contraction: float,
    fundamental: float,
    headroom: float,
) -> float:
    """Equal-weighted composite in [0, 100] (mirrors composite_momentum_score)."""
    stage_c = {"STAGE1_2_TURN": 1.0, "REACCUM_BASE": 0.7, "STAGE1_BASE": 0.6}.get(stage, 0.0)
    components = [
        accumulation,
        1.0 if rs_turn else 0.0,
        stage_c,
        vol_contraction,
        fundamental,
        headroom,
    ]
    return float(np.mean(components) * 100)
