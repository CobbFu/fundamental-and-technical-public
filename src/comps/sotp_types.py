"""Dataclasses for Sum-of-Parts (SOTP) segment valuation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SegmentFinancials:
    """Financial data for a single business segment."""

    revenue: float | None = None
    operating_income: float | None = None
    operating_margin: float | None = None  # Derived: OI / revenue
    revenue_prior: float | None = None  # Prior year (for growth calc)
    revenue_growth: float | None = None  # YoY growth
    capex: float | None = None
    depreciation: float | None = None


@dataclass
class SegmentData:
    """A single business segment with its financials and valuation context."""

    name: str  # "Intelligent Cloud", "Automotive"
    source: str  # "edgar" or "user_override"
    industry: str = ""  # Mapped Damodaran industry
    financials: SegmentFinancials = field(default_factory=SegmentFinancials)
    fiscal_year: int | None = None
    # Valuation outputs (filled by SOTPEngine)
    ev_revenue_multiple: float | None = None
    ev_ebitda_multiple: float | None = None
    implied_ev: float | None = None
    weight_pct: float | None = None  # % of total SOTP value


@dataclass
class SOTPFlag:
    """A critic flag from SOTP analysis."""

    severity: str  # "HIGH", "MEDIUM", "LOW"
    category: str  # "discount_divergence", "missing_segment_data", "no_peers"
    segment: str  # segment name or "aggregate"
    message: str
    data_context: dict = field(default_factory=dict)


@dataclass
class SOTPResult:
    """Complete SOTP valuation result."""

    ticker: str
    segments: list[SegmentData]
    total_segment_ev: float | None = None  # Sum of segment implied EVs
    net_debt: float | None = None
    equity_value: float | None = None  # total_segment_ev - net_debt
    equity_per_share: float | None = None
    market_cap: float | None = None
    implied_discount: float | None = None  # (market_cap - total_ev) / total_ev
    user_discount: float = 0.0  # User-set assumption
    flags: list[SOTPFlag] = field(default_factory=list)
    retrieved_at: str = ""
