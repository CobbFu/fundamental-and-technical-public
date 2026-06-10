"""Cascade Monitor — Supply Chain Early Detection System.

Watches 6 PM-curated supply chain cascades for coordinated breakouts
using regime shift detection signals. Each cascade has ordered tiers
(supply chain positions) with 3-6 tickers per tier. When a tier fires
(breadth thrust), the next tier is flagged as "NEXT TO WATCH".
"""

from src.cascade.config import (
    CascadeConfig,
    CascadeDef,
    TierDef,
    all_tickers,
    cross_cascade_map,
    load_cascades,
)
from src.cascade.report import (
    format_all_cascade_parts,
    format_cascade_report,
    format_cascade_report_parts,
    format_cross_cascade_summary,
)
from src.cascade.scanner import (
    CascadeResult,
    CascadeScanner,
    CascadeScanResult,
    StockSignals,
    TierResult,
)
from src.cascade.signals import (
    base_breakout,
    distance_from_52w_high,
    return_3m,
    volume_ratio,
)

__all__ = [
    "CascadeConfig",
    "CascadeDef",
    "CascadeResult",
    "CascadeScanner",
    "CascadeScanResult",
    "StockSignals",
    "TierDef",
    "TierResult",
    "all_tickers",
    "base_breakout",
    "cross_cascade_map",
    "distance_from_52w_high",
    "format_all_cascade_parts",
    "format_cascade_report",
    "format_cascade_report_parts",
    "format_cross_cascade_summary",
    "load_cascades",
    "return_3m",
    "volume_ratio",
]
