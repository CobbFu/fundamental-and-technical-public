"""Fundamental inflection gate for the early scanner — the "why now".

Reuses momentum's analyst-signal extractors. The early scan's fundamental
requirement is leading: analysts must be *net raising* estimates now (revision
inflection) with positive forward growth. True 2nd-derivative acceleration needs
stored weekly snapshots — deferred to v2 (see plan NOTES).
"""

import pandas as pd

from src.momentum.fundamentals import (
    analyst_buy_percentage,
    earnings_growth_estimate,
    earnings_revision_score,
)

__all__ = [
    "analyst_buy_percentage",
    "earnings_growth_estimate",
    "earnings_revision_score",
    "fundamental_gate_score",
    "growth_ok",
    "revision_inflection",
]


def revision_inflection(eps_revisions: pd.DataFrame | None) -> float | None:
    """Net analyst revision direction in [-1, 1]; > 0 = inflecting up. None if unknown."""
    return earnings_revision_score(eps_revisions)


def growth_ok(earnings_estimate: pd.DataFrame | None, min_growth: float = 0.10) -> bool:
    """True if the current-year EPS growth estimate clears `min_growth`."""
    g = earnings_growth_estimate(earnings_estimate)
    return g is not None and g >= min_growth


def fundamental_gate_score(
    revision: float | None, growth: float | None, max_growth: float = 0.50
) -> float:
    """Blend revision direction + forward growth into [0, 1].

    revision in [-1, 1] -> [0, 1]; growth clamped to [0, max_growth] -> [0, 1].
    Missing inputs contribute 0 (neutral), so a name with no analyst coverage
    scores low on the fundamental component but is not hard-excluded.
    """
    rev_norm = 0.0 if revision is None else max(0.0, min(1.0, (revision + 1.0) / 2.0))
    growth_norm = 0.0 if growth is None else max(0.0, min(1.0, growth / max_growth))
    return float((rev_norm + growth_norm) / 2.0)
