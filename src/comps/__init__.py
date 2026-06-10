"""Comps types used by scout/segments — trimmed to sotp_types only.

The full comps module (multiples, peer selection, reconciliation, sotp engines)
lives in the Valuation project. Only the SOTP types are carried over here
because scout/segments depends on them.
"""

from src.comps.sotp_types import SegmentData, SegmentFinancials, SOTPFlag, SOTPResult

__all__ = [
    "SegmentData",
    "SegmentFinancials",
    "SOTPFlag",
    "SOTPResult",
]
