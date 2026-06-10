"""Shared types and utilities used by the scout/cascade/momentum/calculators modules.

Trimmed from the Valuation project — only types + extraction are carried over.
Re-add knowledge, calibration, config, dcf, etc. as those modules are built out here.
"""

from src.common.types import (
    Assumptions,
    AssumptionValue,
    CompanyData,
    CompanyProfile,
    IndustryData,
    MacroData,
    ModelRecommendation,
    SourceTag,
    TaggedValue,
    ValidationIssue,
)

__all__ = [
    "Assumptions",
    "AssumptionValue",
    "CompanyData",
    "CompanyProfile",
    "IndustryData",
    "MacroData",
    "ModelRecommendation",
    "SourceTag",
    "TaggedValue",
    "ValidationIssue",
]
