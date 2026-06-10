"""Core dataclasses used across all agent modules."""

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class SourceTag:
    """Provenance tag for every data point."""

    source: str  # e.g., "FMP", "Damodaran", "FRED"
    retrieved_at: str  # ISO datetime
    fiscal_period: str  # e.g., "FY2025", "Q3 2025", "latest"


@dataclass
class TaggedValue:
    """A single data point with provenance."""

    value: float | str | None
    tag: SourceTag
    note: str = ""  # e.g., "estimated", "cross-validated"


@dataclass
class EarningsSurprise:
    """Single quarter earnings surprise."""

    period: str  # e.g., "2025-Q4"
    eps_actual: float
    eps_estimate: float
    surprise_pct: float  # positive = beat


@dataclass
class ConsensusData:
    """Analyst consensus data from yfinance."""

    # Price targets
    target_mean: float | None = None
    target_median: float | None = None
    target_high: float | None = None
    target_low: float | None = None
    current_price: float | None = None

    # Analyst recommendations (current month)
    strong_buy: int = 0
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strong_sell: int = 0

    # Forward estimates
    eps_current_year: float | None = None
    eps_next_year: float | None = None
    revenue_current_year: float | None = None
    revenue_next_year: float | None = None
    revenue_growth_current_year: float | None = None
    revenue_growth_next_year: float | None = None

    # Earnings surprises (last 4 quarters)
    earnings_surprises: list[EarningsSurprise] = field(default_factory=list)

    # Metadata
    retrieved_at: str | None = None


@dataclass
class PeerData:
    """A comparable company with key valuation metrics for peer comparison."""

    ticker: str
    name: str
    market_cap: float | None = None
    pe_ratio: float | None = None
    ev_ebitda: float | None = None
    ev_revenue: float | None = None
    revenue_growth: float | None = None
    operating_margin: float | None = None


@dataclass
class CompanyData:
    """All fetched data for a single company."""

    ticker: str
    name: str
    industry: str
    market_cap: TaggedValue | None = None
    income_statement: pd.DataFrame | None = None  # 5yr history
    balance_sheet: pd.DataFrame | None = None
    cash_flow: pd.DataFrame | None = None
    key_metrics: dict[str, TaggedValue] = field(default_factory=dict)  # R&D, SBC, etc.
    consensus: ConsensusData | None = None  # Analyst consensus from yfinance
    peers: list[PeerData] = field(default_factory=list)
    observed_beta: float | None = None  # yfinance 5Y monthly regression beta
    reporting_currency: str = "USD"


@dataclass
class IndustryData:
    """Damodaran industry benchmarks."""

    industry_name: str
    unlevered_beta: TaggedValue | None = None
    equity_risk_premium: TaggedValue | None = None
    avg_operating_margin: TaggedValue | None = None
    avg_wacc: TaggedValue | None = None
    avg_tax_rate: TaggedValue | None = None
    datasets: dict[str, pd.DataFrame] = field(default_factory=dict)  # raw Damodaran datasets


@dataclass
class MacroSignal:
    """Single macro indicator with current value and historical percentile."""

    series_id: str  # e.g., "GS10", "VIXCLS"
    label: str  # e.g., "10Y Treasury Yield"
    current_value: float
    percentile_10y: float  # 0-100 percentile rank over 10 years
    tag: SourceTag


@dataclass
class MacroContext:
    """Macro environment snapshot for scenario generation."""

    signals: list[MacroSignal] = field(default_factory=list)
    environment_summary: str = ""  # LLM-generated 1-line summary
    retrieved_at: str = ""


@dataclass
class MacroData:
    """Macro-economic data from FRED and other sources."""

    risk_free_rate: TaggedValue | None = None
    gdp_growth_rate: TaggedValue | None = None
    inflation_rate: TaggedValue | None = None
    market_return: TaggedValue | None = None
    macro_context: MacroContext | None = None  # Extended signals for scenarios
    fx_rate_to_usd: TaggedValue | None = None  # multiply local currency by this to get USD


@dataclass
class PipelineData:
    """Bundle of all fetched data for a single ticker."""

    ticker: str
    company: CompanyData
    industry: IndustryData
    macro: MacroData


@dataclass
class InsiderHolder:
    """A single insider (officer/director) with ownership details."""

    name: str
    position: str  # e.g., "CEO", "CFO", "Director"
    shares_direct: int | None = None
    shares_indirect: int | None = None
    latest_transaction: str = ""  # "Sale", "Purchase"
    latest_transaction_date: str = ""  # ISO date


@dataclass
class InsiderSummary:
    """Insider ownership summary from yfinance major_holders."""

    insider_ownership_pct: float | None  # % held by insiders
    institution_ownership_pct: float | None  # % held by institutions
    top_insiders: list[InsiderHolder] = field(default_factory=list)
    tag: SourceTag | None = None


@dataclass
class InstitutionalHolder:
    """A single institutional holder entry."""

    holder: str  # "Vanguard Group Inc"
    shares: int | None = None
    value: float | None = None  # USD
    date_reported: str = ""  # ISO date
    tag: SourceTag | None = None


@dataclass
class Form4Transaction:
    """A single Form 4 insider transaction."""

    insider_name: str
    insider_position: str  # "CEO", "Director"
    transaction_type: str  # "Purchase" or "Sale"
    transaction_date: str  # ISO date
    shares: int | None = None
    price_per_share: float | None = None
    value: float | None = None
    source: str = "yfinance"  # "yfinance" or "edgar"


@dataclass
class HoldingsData:
    """Insider and institutional holdings data for a ticker."""

    ticker: str
    insider_summary: InsiderSummary | None = None
    institutional_holders: list[InstitutionalHolder] = field(default_factory=list)
    form4_transactions: list[Form4Transaction] = field(default_factory=list)
    retrieved_at: str = ""  # ISO datetime


@dataclass
class ModelRecommendation:
    """A recommended Damodaran valuation model."""

    model_name: str  # e.g., "FCFF"
    spreadsheet: str  # e.g., "fcffsimpleginzu.xlsx"
    rationale: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0-1


@dataclass
class CompanyProfile:
    """Classification of company characteristics for model selection."""

    ticker: str
    name: str
    industry: str
    is_financial_services: bool = False
    is_natural_resources: bool = False
    has_negative_earnings: bool = False
    is_high_growth: bool = False
    dividends_reflect_cash: bool = False
    stable_leverage: bool = False


@dataclass
class AssumptionValue:
    """A single assumption with value, rationale, and source."""

    value: float
    rationale: str
    source: str  # e.g., "Damodaran betas.xls", "FMP historical"


@dataclass
class DerivationStep:
    """Single step in a derivation chain."""

    label: str  # "Unlevered Beta"
    value: float | str | None
    source: str  # "Damodaran betas dataset"
    formula: str = ""  # "beta_U * (1 + (1-t) * D/E)"


@dataclass
class DerivationTrace:
    """Full derivation chain for an auditable calculated value."""

    calculator: str  # "BetaCalculator"
    result_label: str  # "Levered Beta"
    result_value: float | None
    steps: list[DerivationStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Assumptions:
    """Complete set of suggested assumptions for a valuation model."""

    model_name: str
    high_growth_period: AssumptionValue
    terminal_growth_rate: AssumptionValue
    revenue_cagr: AssumptionValue
    terminal_operating_margin: AssumptionValue
    tax_rate: AssumptionValue
    capex_pct_revenue: AssumptionValue
    nwc_pct_revenue: AssumptionValue
    target_de_ratio: AssumptionValue
    wacc: AssumptionValue | None = None
    revenue_growth_yr1: AssumptionValue | None = None
    r_and_d_capitalization: bool = False
    r_and_d_amortization_years: int = 4
    beta_trace: DerivationTrace | None = None
    cost_of_debt_trace: DerivationTrace | None = None
    wacc_trace: DerivationTrace | None = None
    lease_trace: DerivationTrace | None = None
    rd_trace: DerivationTrace | None = None
    terminal_sanity_trace: DerivationTrace | None = None


@dataclass
class ValidationIssue:
    """A data quality flag from the Reviewer."""

    severity: str  # "ERROR", "WARNING", "INFO"
    category: str  # "missing_data", "range_check", "cross_validation", "freshness"
    field: str
    message: str
    resolution: str = ""


@dataclass
class PostBuildCheck:
    """A single post-build validation check result."""

    check_name: str  # e.g., "terminal_value_pct"
    status: str  # "pass", "warning", "fail"
    message: str
    value: float | None  # the extracted value that was checked
    threshold: str  # human description of threshold, e.g., ">85%"
    severity: str = ""  # "HIGH", "MEDIUM", "LOW"


@dataclass
class PostBuildResult:
    """Result of post-build validation."""

    workbook_path: str
    extracted_values: dict[str, float | None]  # anchor name → value
    checks: list[PostBuildCheck]
    error_cells: list[tuple[str, str, str]]  # (sheet, cell_addr, error_type)
    formula_issues: list[tuple[str, str, str]]  # (sheet, cell_addr, label)
    extraction_method: str  # "named_ranges", "discovery", "mixed"


@dataclass
class EnrichmentMetric:
    """Single computed analytical metric with context."""

    value: float | None
    label: str
    rationale: str
    source: str


@dataclass
class WACCSensitivityRow:
    """One row in the WACC sensitivity table for implied growth."""

    wacc: float
    implied_growth: float | None  # None if solver fails


@dataclass
class EnrichmentData:
    """Computed analytical context for the guided discussion.

    All values derived from existing PipelineData — zero new API calls.
    """

    # A1: Reverse DCF implied growth
    implied_growth_rate: EnrichmentMetric | None = None
    wacc_sensitivity: list[WACCSensitivityRow] | None = None

    # A2: Margin convergence
    current_operating_margin: float | None = None
    industry_operating_margin: float | None = None
    margin_gap: float | None = None  # current - industry

    # A3: ROIC vs WACC
    roic: EnrichmentMetric | None = None
    roic_vs_wacc: str | None = None  # "creating value" / "destroying value"

    # A4: Earnings quality
    earnings_quality: EnrichmentMetric | None = None

    # A5: Historical stability
    revenue_growth_std: float | None = None
    margin_std: float | None = None
    stability_assessment: str | None = None  # "stable" / "volatile" / "mixed"

    # Metadata
    computed_at: str | None = None


@dataclass
class CriticFlag:
    """A single auto-critic finding."""

    check: str  # "fallback_detection", "market_disagreement", "sensitivity"
    severity: str  # "high", "medium", "low"
    assumption: str  # field name, e.g., "revenue_cagr"
    message: str  # human-readable flag description
    data_context: dict = field(default_factory=dict)  # supporting data


@dataclass
class ChangelogEntry:
    """Single entry in the CHANGELOG sheet."""

    version: str
    timestamp: str
    action: str
    details: str


@dataclass
class AssumptionSnapshot:
    """Frozen copy of assumptions at a pipeline checkpoint."""

    label: str  # "System Default", "User Override"
    assumptions: Assumptions  # deep copy of full Assumptions
    timestamp: str  # ISO datetime
    changed_by: str = ""  # "system" or "user"
    rationale: str = ""  # one-liner explaining the checkpoint


@dataclass
class IndicativeValue:
    """Simplified DCF output range — NOT a point-estimate fair value."""

    equity_low: float
    equity_mid: float
    equity_high: float
    per_share_low: float
    per_share_mid: float
    per_share_high: float
    current_price: float | None
    shares_outstanding: float
    label: str = "Indicative (simplified DCF)"
    disclaimer: str = "Approximate range — not a point-estimate fair value"


@dataclass
class MonteCarloHistogramBucket:
    """A single bucket in the Monte Carlo value distribution histogram."""

    low: float
    high: float
    count: int


@dataclass
class MonteCarloResult:
    """Percentile-based valuation from Monte Carlo simulation (Damodaran p30/p70)."""

    ticker: str
    n_simulations: int
    n_valid: int
    p10_per_share: float
    p30_per_share: float
    p50_per_share: float
    p70_per_share: float
    p90_per_share: float
    current_price: float | None
    buy_signal: bool
    sell_signal: bool
    margin_of_safety: float | None
    histogram: list[MonteCarloHistogramBucket]
    base_fcf_margin: float
    computed_at: str
    mean_per_share: float
    std_per_share: float
    skewness: float


@dataclass
class Scenario:
    """A single scenario (bull, base, or bear) with shifted assumptions."""

    label: str  # "bull", "base", "bear", or named narrative
    assumptions: Assumptions
    rationale: str  # 1-2 sentence narrative
    implied_value: IndicativeValue | None = None
    confidence_flags: list[CriticFlag] = field(default_factory=list)
    probability: float | None = None  # 0.0-1.0, None = equal weight
    narrative: str = ""  # Extended narrative description (beyond label)


@dataclass
class ScenarioSet:
    """Complete scenario comparison: bull/base/bear + macro context."""

    bull: Scenario
    base: Scenario
    bear: Scenario
    macro_context: MacroContext
    guardrail_warnings: list[str] = field(default_factory=list)
    weighted_scenarios: list[Scenario] = field(default_factory=list)
    composite_per_share: float | None = None


@dataclass
class OptionInput:
    """Black-Scholes input for a single real option (Damodaran expand.xls mapping)."""

    option_name: str  # "Robotaxi", "Energy Storage"
    underlying_value: float  # S — PV of project cash flows if exercised
    exercise_cost: float  # K — cost of expansion investment
    time_years: float  # t — time window before competitors close gap
    volatility: float  # sigma — variance in project cash flows (annualized)
    risk_free_rate: float  # r — risk-free rate (decimal)
    probability: float = 1.0  # probability option is exercisable (0-1)
    narrative: str = ""  # description of what this option represents


@dataclass
class OptionResult:
    """Black-Scholes output for a single real option."""

    option_name: str
    call_value: float  # raw Black-Scholes call value (total $)
    per_share_value: float  # call_value / shares_outstanding
    weighted_value: float  # per_share_value * probability
    delta: float  # N(d1) — sensitivity to underlying
    sensitivity: dict[str, float]  # {"underlying_value": +X, "volatility": +Y, ...}
    warnings: list[str]  # Damodaran warning flags
    trace: DerivationTrace


@dataclass
class OptionsOverlay:
    """Complete options overlay result for a ticker."""

    ticker: str
    options: list[OptionResult]
    total_overlay_per_share: float  # sum of weighted per-share values
    dcf_base_per_share: float  # from IndicativeValue.per_share_mid
    composite_per_share: float  # dcf_base + total_overlay
    current_price: float | None
    gap_explained_pct: float | None  # how much of market-DCF gap options explain
    computed_at: str  # ISO datetime
