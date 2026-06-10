"""RDCapitalizer — capitalize R&D expenses into an asset.

Replicates Damodaran's R&DConv.xls logic:
    R&D Asset = Sum of unamortized portions of past R&D expenses
    Amortization = sum of per-year amortization charges
    Adjusted EBIT = Reported EBIT + Current R&D - Amortization
"""

import logging
from dataclasses import dataclass

from src.common.extraction import extract_series_multi, extract_value
from src.common.types import CompanyData, DerivationStep, DerivationTrace

logger = logging.getLogger(__name__)

# Damodaran rule: capitalize R&D when R&D/Revenue > 5%
_RD_CAPITALIZATION_THRESHOLD = 0.05


@dataclass
class RDResult:
    """Result of R&D capitalization calculation."""

    should_capitalize: bool
    rd_revenue_ratio: float
    rd_asset: float  # Sum of unamortized R&D
    amortization: float  # Annual amortization of R&D asset
    adjusted_ebit: float  # EBIT + current R&D - amortization
    current_rd: float
    historical_rd: list[float]  # Past N years of R&D expense
    trace: DerivationTrace


class RDCapitalizer:
    """Determines whether to capitalize R&D and computes the adjustment."""

    def calculate(
        self, company: CompanyData, amort_years: int = 4
    ) -> RDResult | None:
        """Calculate R&D capitalization adjustment.

        Returns None if R&D or revenue data is missing.
        """
        # 1. Get R&D series
        rd_series = extract_series_multi(
            company.income_statement,
            [
                "Research and Development Expenses",
                "Research And Development Expenses",
                "R&D Expenses",
                "Research & Development",
            ],
        )
        if rd_series is None:
            return None

        # 2. Revenue for materiality check
        revenue = extract_value(company.income_statement, "Revenue")
        if revenue is None or revenue == 0:
            return None

        sorted_rd = rd_series.sort_index()
        current_rd = abs(float(sorted_rd.iloc[-1]))
        rd_ratio = current_rd / abs(revenue)

        # 3. Materiality check
        should_capitalize = rd_ratio > _RD_CAPITALIZATION_THRESHOLD

        # 4. Historical R&D (excluding current year)
        historical_rd = [abs(float(v)) for v in sorted_rd.iloc[:-1]]

        # 5. R&D Asset = sum of unamortized portions
        # For each year i (1 to amort_life): unamortized_i = R&D_i * (1 - i/amort_life)
        rd_asset = 0.0
        amortization = 0.0

        for i, rd_val in enumerate(reversed(historical_rd)):
            year_offset = i + 1  # 1 = most recent prior year
            if year_offset <= amort_years:
                unamortized_fraction = 1 - year_offset / amort_years
                unamortized = rd_val * unamortized_fraction
                year_amort = rd_val / amort_years
                rd_asset += unamortized
                amortization += year_amort

        # 6. Adjusted EBIT
        ebit = extract_value(company.income_statement, "Operating Income")
        if ebit is None:
            ebit = 0.0
        adjusted_ebit = ebit + current_rd - amortization

        trace = DerivationTrace(
            calculator="RDCapitalizer",
            result_label="R&D Capitalization",
            result_value=rd_asset,
            steps=[
                DerivationStep(
                    label="Current R&D Expense",
                    value=current_rd,
                    source="FMP income statement",
                ),
                DerivationStep(
                    label="Revenue",
                    value=revenue,
                    source="FMP income statement",
                ),
                DerivationStep(
                    label="R&D/Revenue Ratio",
                    value=rd_ratio,
                    source="Calculated",
                    formula="Current R&D / Revenue",
                ),
                DerivationStep(
                    label="Should Capitalize?",
                    value="Yes" if should_capitalize else "No",
                    source="Damodaran rule",
                    formula=f"R&D/Revenue > {_RD_CAPITALIZATION_THRESHOLD:.0%}",
                ),
                DerivationStep(
                    label="Amortization Life",
                    value=amort_years,
                    source="Default (software/tech)",
                ),
                DerivationStep(
                    label="R&D Asset (unamortized)",
                    value=rd_asset,
                    source="Calculated",
                    formula="Sum of R&D_i * (1 - i/amort_life)",
                ),
                DerivationStep(
                    label="Annual Amortization",
                    value=amortization,
                    source="Calculated",
                    formula="Sum of R&D_i / amort_life",
                ),
                DerivationStep(
                    label="Reported EBIT",
                    value=ebit,
                    source="FMP income statement",
                ),
                DerivationStep(
                    label="Adjusted EBIT",
                    value=adjusted_ebit,
                    source="Calculated",
                    formula="EBIT + Current R&D - Amortization",
                ),
            ],
        )

        return RDResult(
            should_capitalize=should_capitalize,
            rd_revenue_ratio=rd_ratio,
            rd_asset=rd_asset,
            amortization=amortization,
            adjusted_ebit=adjusted_ebit,
            current_rd=current_rd,
            historical_rd=historical_rd,
            trace=trace,
        )
