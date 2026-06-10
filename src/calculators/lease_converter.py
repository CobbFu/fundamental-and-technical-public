"""LeaseConverter — convert operating leases to debt equivalent.

Replicates Damodaran's oplease.xls logic. Post-ASC 842, FMP provides
"Capital Lease Obligations" as the PV of lease commitments directly.
We use this value instead of discounting individual year commitments.
"""

import logging
from dataclasses import dataclass

from src.common.extraction import extract_value, extract_value_multi
from src.common.types import (
    CompanyData,
    DerivationStep,
    DerivationTrace,
    IndustryData,
)

logger = logging.getLogger(__name__)


@dataclass
class LeaseResult:
    """Result of operating lease conversion."""

    lease_debt: float  # PV of lease commitments
    adjusted_ebit: float  # EBIT + lease expense - depreciation of lease asset
    depreciation_of_lease: float
    total_debt_adjusted: float  # Book debt + lease debt
    trace: DerivationTrace


class LeaseConverter:
    """Converts operating lease commitments to debt equivalent and adjusts EBIT."""

    def calculate(
        self,
        company: CompanyData,
        industry: IndustryData,
        kd_pretax: float | None = None,
    ) -> LeaseResult | None:
        """Calculate lease debt and adjusted EBIT.

        Returns None if no material lease obligations exist.
        """
        # 1. Lease debt from balance sheet (ASC 842 — already PV)
        lease_debt = extract_value(company.balance_sheet, "Capital Lease Obligations")
        if lease_debt is None or lease_debt <= 0:
            return None

        # 2. EBIT
        ebit = extract_value_multi(
            company.income_statement, ["Operating Income", "EBIT"]
        )
        if ebit is None:
            logger.warning("No EBIT data — cannot adjust for leases")
            return None

        # 3. Depreciation of lease asset
        # Simplified: lease_debt / average remaining lease life
        # ASC 842 typical remaining life ~5-7 years for tech companies
        remaining_life = 6.0  # Conservative estimate
        depreciation = lease_debt / remaining_life

        # 4. Implicit lease expense (interest component)
        # Interest on lease debt = lease_debt * pre-tax Kd
        rate = kd_pretax if kd_pretax is not None else 0.05  # Default 5%
        interest_on_lease = lease_debt * rate

        # 5. Adjusted EBIT = Reported EBIT + implicit lease interest - depreciation
        # (Under ASC 842, the lease expense is already split into interest + depreciation
        #  in the financials. But for Damodaran's framework, we add back the implicit
        #  interest component since it's now treated as a financing cost.)
        adjusted_ebit = ebit + interest_on_lease - depreciation

        # 6. Total debt adjusted
        book_debt = extract_value_multi(
            company.balance_sheet, ["Total Debt", "Long Term Debt"]
        ) or 0.0
        total_debt_adjusted = book_debt + lease_debt

        trace = DerivationTrace(
            calculator="LeaseConverter",
            result_label="Lease-Adjusted Debt & EBIT",
            result_value=total_debt_adjusted,
            steps=[
                DerivationStep(
                    label="Capital Lease Obligations (PV)",
                    value=lease_debt,
                    source="FMP balance sheet (ASC 842)",
                ),
                DerivationStep(
                    label="Remaining Lease Life (est.)",
                    value=remaining_life,
                    source="Default estimate",
                ),
                DerivationStep(
                    label="Depreciation of Lease Asset",
                    value=depreciation,
                    source="Calculated",
                    formula="Lease Debt / Remaining Life",
                ),
                DerivationStep(
                    label="Pre-tax Kd (for lease interest)",
                    value=rate,
                    source="SyntheticRating" if kd_pretax else "Default 5%",
                ),
                DerivationStep(
                    label="Implicit Lease Interest",
                    value=interest_on_lease,
                    source="Calculated",
                    formula="Lease Debt * Pre-tax Kd",
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
                    formula="EBIT + Lease Interest - Depreciation",
                ),
                DerivationStep(
                    label="Book Debt",
                    value=book_debt,
                    source="FMP balance sheet",
                ),
                DerivationStep(
                    label="Total Debt (adjusted)",
                    value=total_debt_adjusted,
                    source="Calculated",
                    formula="Book Debt + Lease Debt",
                ),
            ],
        )

        return LeaseResult(
            lease_debt=lease_debt,
            adjusted_ebit=adjusted_ebit,
            depreciation_of_lease=depreciation,
            total_debt_adjusted=total_debt_adjusted,
            trace=trace,
        )
