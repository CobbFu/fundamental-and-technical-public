"""Momentum Radar & Fallen Angel Scanner.

Market-wide screening system that detects stocks in sustained multi-month
climbs (Momentum Radar) and quality companies in sustained decline
(Fallen Angel Scanner). Uses academic signals: Jegadeesh/Titman 2-12 return,
Frog-in-the-Pan (FIP), OBV, relative strength, Piotroski F-Score, Altman Z-Score.
"""

from src.momentum.fundamentals import (
    analyst_buy_percentage,
    earnings_growth_estimate,
    earnings_revision_score,
    fcf_yield,
    forward_pe,
    short_interest_pct,
)
from src.momentum.scanner import (
    DailyHighsResult,
    FallenAngelEntry,
    FallenAngelResult,
    FallenAngelScanner,
    MomentumScanner,
    ScanResult,
    TierEntry,
)
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

__all__ = [
    "MomentumScanner",
    "FallenAngelScanner",
    "ScanResult",
    "TierEntry",
    "FallenAngelResult",
    "FallenAngelEntry",
    "DailyHighsResult",
    "momentum_return_2_12",
    "frog_in_pan",
    "obv_trend",
    "relative_strength_vs_sector",
    "ma_position",
    "absolute_momentum_check",
    "composite_momentum_score",
    "momentum_acceleration",
    "fresh_stale_momentum",
    "ma_slope_200",
    "slow_fast_agreement",
    "earnings_revision_score",
    "analyst_buy_percentage",
    "earnings_growth_estimate",
    "forward_pe",
    "fcf_yield",
    "short_interest_pct",
]
