"""SyntheticRating — interest coverage to bond rating to default spread.

Replicates Damodaran's ratings.xls logic:
    Coverage = EBIT / Interest Expense
    Rating = lookup from coverage table (large-cap vs small-cap)
    Pre-tax Kd = Risk-free rate + Default Spread
    After-tax Kd = Pre-tax Kd * (1 - marginal tax rate)
"""

import logging
from dataclasses import dataclass

from src.common.extraction import extract_value_multi, tagged_float
from src.common.types import (
    CompanyData,
    DerivationStep,
    DerivationTrace,
    IndustryData,
    MacroData,
)

logger = logging.getLogger(__name__)

# Market cap threshold for large-cap vs small-cap rating table
_LARGE_CAP_THRESHOLD = 5_000_000_000  # $5B (Damodaran's cutoff for rating tables)

# Damodaran's Interest Coverage -> Rating -> Default Spread tables
# Source: Damodaran, January 2024 update (pages.stern.nyu.edu/~adamodar/)
# Spreads in basis points, stored as decimals

# Large-cap (market cap > $5B)
_LARGE_CAP_TABLE: list[tuple[float, str, float]] = [
    (12.50, "AAA", 0.0063),
    (9.50, "AA", 0.0078),
    (7.50, "A+", 0.0098),
    (6.00, "A", 0.0108),
    (4.50, "A-", 0.0122),
    (4.00, "BBB", 0.0156),
    (3.50, "BB+", 0.0200),
    (3.00, "BB", 0.0240),
    (2.50, "B+", 0.0325),
    (2.00, "B", 0.0400),
    (1.50, "B-", 0.0500),
    (1.25, "CCC", 0.0600),
    (0.80, "CC", 0.0850),
    (0.50, "C", 0.1100),
    (-1e99, "D", 0.1500),  # Catch-all for coverage < 0.50
]

# Small-cap (market cap < $5B) — tighter thresholds
_SMALL_CAP_TABLE: list[tuple[float, str, float]] = [
    (12.50, "AAA", 0.0063),
    (9.50, "AA", 0.0078),
    (7.50, "A+", 0.0098),
    (6.00, "A", 0.0108),
    (4.50, "A-", 0.0122),
    (3.50, "BBB", 0.0175),
    (3.00, "BB+", 0.0225),
    (2.50, "BB", 0.0275),
    (2.00, "B+", 0.0375),
    (1.50, "B", 0.0450),
    (1.25, "B-", 0.0550),
    (0.80, "CCC", 0.0700),
    (0.50, "CC", 0.0900),
    (0.20, "C", 0.1200),
    (-1e99, "D", 0.1600),
]


@dataclass
class RatingResult:
    """Result of synthetic rating calculation."""

    interest_coverage: float
    rating: str
    default_spread: float  # decimal, e.g., 0.0098 for 98bps
    pre_tax_cost_of_debt: float
    after_tax_cost_of_debt: float
    is_large_cap: bool
    trace: DerivationTrace


class SyntheticRating:
    """Maps interest coverage to synthetic bond rating and cost of debt."""

    def calculate(
        self,
        company: CompanyData,
        industry: IndustryData,
        macro: MacroData,
    ) -> RatingResult | None:
        """Calculate synthetic rating and cost of debt.

        Returns None if EBIT or Interest Expense data is missing/zero.
        """
        # 1. EBIT (Operating Income)
        ebit = extract_value_multi(
            company.income_statement, ["Operating Income", "EBIT"]
        )
        if ebit is None:
            logger.warning("No EBIT data — cannot compute synthetic rating")
            return None

        # 2. Interest Expense
        interest = extract_value_multi(
            company.income_statement,
            ["Interest Expense", "Interest Expense Debt"],
        )
        if interest is None or interest == 0:
            logger.warning(
                "No interest expense (zero or missing) — cannot compute coverage ratio"
            )
            return None

        # Use absolute value of interest expense (may be negative in some data sources)
        interest = abs(interest)

        # 3. Interest Coverage
        coverage = ebit / interest

        # 4. Large-cap or small-cap table?
        market_cap = tagged_float(company.market_cap)
        is_large_cap = market_cap is not None and market_cap > _LARGE_CAP_THRESHOLD
        table = _LARGE_CAP_TABLE if is_large_cap else _SMALL_CAP_TABLE

        # 5. Lookup rating and spread
        rating, spread = self._lookup_rating(coverage, table)

        # 6. Risk-free rate
        rf = tagged_float(macro.risk_free_rate)
        if rf is None:
            logger.warning("No risk-free rate — cannot compute cost of debt")
            return None

        # 7. Pre-tax and after-tax cost of debt
        pre_tax_kd = rf + spread

        marginal_tax = tagged_float(industry.avg_tax_rate)
        if marginal_tax is None:
            marginal_tax = 0.25  # Conservative default
        after_tax_kd = pre_tax_kd * (1 - marginal_tax)

        trace = DerivationTrace(
            calculator="SyntheticRating",
            result_label="Cost of Debt (pre-tax)",
            result_value=pre_tax_kd,
            steps=[
                DerivationStep(
                    label="EBIT (Operating Income)",
                    value=ebit,
                    source="FMP income statement",
                ),
                DerivationStep(
                    label="Interest Expense",
                    value=interest,
                    source="FMP income statement",
                ),
                DerivationStep(
                    label="Interest Coverage Ratio",
                    value=coverage,
                    source="Calculated",
                    formula="EBIT / Interest Expense",
                ),
                DerivationStep(
                    label="Cap Size",
                    value="Large" if is_large_cap else "Small",
                    source="yfinance market cap",
                ),
                DerivationStep(
                    label="Synthetic Rating",
                    value=rating,
                    source="Damodaran ratings table (Jan 2024)",
                ),
                DerivationStep(
                    label="Default Spread",
                    value=spread,
                    source="Damodaran ratings table (Jan 2024)",
                ),
                DerivationStep(
                    label="Risk-Free Rate",
                    value=rf,
                    source="FRED 10Y Treasury",
                ),
                DerivationStep(
                    label="Pre-tax Cost of Debt",
                    value=pre_tax_kd,
                    source="Calculated",
                    formula="Risk-Free Rate + Default Spread",
                ),
                DerivationStep(
                    label="Marginal Tax Rate",
                    value=marginal_tax,
                    source="Damodaran tax rates",
                ),
                DerivationStep(
                    label="After-tax Cost of Debt",
                    value=after_tax_kd,
                    source="Calculated",
                    formula="Pre-tax Kd * (1 - marginal tax rate)",
                ),
            ],
        )

        return RatingResult(
            interest_coverage=coverage,
            rating=rating,
            default_spread=spread,
            pre_tax_cost_of_debt=pre_tax_kd,
            after_tax_cost_of_debt=after_tax_kd,
            is_large_cap=is_large_cap,
            trace=trace,
        )

    @staticmethod
    def _lookup_rating(
        coverage: float, table: list[tuple[float, str, float]]
    ) -> tuple[str, float]:
        """Look up rating and spread from coverage ratio.

        Table is sorted by coverage threshold descending. First match wins.
        """
        for threshold, rating, spread in table:
            if coverage > threshold:
                return rating, spread
        # Should never reach here due to -1e99 catch-all, but be safe
        return table[-1][1], table[-1][2]
