"""BetaCalculator — relever industry unlevered beta to company's D/E.

Replicates Damodaran's levbeta.xls logic:
    beta_L = beta_U * (1 + (1 - tax_rate) * (D/E))

Cross-checks against observed (regression) beta from yfinance when available.
If Hamada result diverges >50% from observed, blends 60/40 (bottom-up/observed).
"""

import logging
from dataclasses import dataclass, field

from src.common.extraction import extract_value, extract_value_multi, tagged_float
from src.common.types import (
    CompanyData,
    DerivationStep,
    DerivationTrace,
    IndustryData,
)

logger = logging.getLogger(__name__)

# Divergence threshold for blending observed beta
_BLEND_DIVERGENCE_THRESHOLD = 0.50  # 50%
_BLEND_WEIGHT_BOTTOMUP = 0.60
_BLEND_WEIGHT_OBSERVED = 0.40


@dataclass
class BetaResult:
    """Result of beta relevering calculation."""

    levered_beta: float
    unlevered_beta: float
    de_ratio: float
    tax_rate_used: float
    trace: DerivationTrace
    observed_beta: float | None = None
    blend_applied: bool = False
    hamada_beta: float | None = None  # raw Hamada before any blend


class BetaCalculator:
    """Releveres industry unlevered beta to company-specific D/E ratio."""

    def calculate(
        self,
        company: CompanyData,
        industry: IndustryData,
        observed_beta: float | None = None,
    ) -> BetaResult | None:
        """Calculate company-specific levered beta.

        Args:
            observed_beta: yfinance 5Y monthly regression beta for cross-check.
                If divergence with Hamada exceeds 50%, blends 60/40.

        Returns None if critical inputs (unlevered beta, equity) are missing.
        """
        # 1. Unlevered beta from industry
        beta_u = tagged_float(industry.unlevered_beta)
        if beta_u is None:
            logger.warning("No unlevered beta available — cannot calculate levered beta")
            return None

        # 2. Company D/E ratio from balance sheet
        total_debt = extract_value_multi(
            company.balance_sheet, ["Total Debt", "Long Term Debt"]
        )
        total_equity = extract_value_multi(
            company.balance_sheet,
            ["Total Shareholder Equity", "Total Stockholders Equity", "Total Equity"],
        )

        if total_equity is None or total_equity <= 0:
            logger.warning(
                "Equity is None or non-positive (%s) — cannot compute D/E",
                total_equity,
            )
            return None

        if total_debt is None:
            total_debt = 0.0

        de_ratio = total_debt / total_equity

        # 3. Tax rate — effective from financials, fallback to industry
        tax_rate = self._effective_tax_rate(company, industry)

        # 4. Relever: beta_L = beta_U * (1 + (1 - t) * D/E)
        hamada_beta = beta_u * (1 + (1 - tax_rate) * de_ratio)

        # 5. Cross-check against observed beta
        final_beta = hamada_beta
        blend_applied = False

        if observed_beta is not None and observed_beta > 0:
            divergence = abs(hamada_beta - observed_beta) / observed_beta
            if divergence > _BLEND_DIVERGENCE_THRESHOLD:
                final_beta = (
                    _BLEND_WEIGHT_BOTTOMUP * hamada_beta
                    + _BLEND_WEIGHT_OBSERVED * observed_beta
                )
                blend_applied = True
                logger.info(
                    "Beta blend applied: Hamada=%.2f, observed=%.2f, "
                    "divergence=%.0f%%, blended=%.2f",
                    hamada_beta, observed_beta, divergence * 100, final_beta,
                )

        steps = [
            DerivationStep(
                label="Unlevered Beta (industry)",
                value=beta_u,
                source="Damodaran betas dataset",
            ),
            DerivationStep(
                label="Total Debt",
                value=total_debt,
                source="FMP balance sheet",
            ),
            DerivationStep(
                label="Total Equity",
                value=total_equity,
                source="FMP balance sheet",
            ),
            DerivationStep(
                label="D/E Ratio",
                value=de_ratio,
                source="Calculated",
                formula="Total Debt / Total Equity",
            ),
            DerivationStep(
                label="Tax Rate",
                value=tax_rate,
                source="FMP income statement",
            ),
            DerivationStep(
                label="Hamada Levered Beta",
                value=hamada_beta,
                source="Calculated",
                formula="beta_U * (1 + (1 - t) * D/E)",
            ),
        ]

        # Add observed beta step if available
        if observed_beta is not None:
            steps.append(DerivationStep(
                label="Observed Beta (yfinance 5Y regression)",
                value=observed_beta,
                source="yfinance",
            ))
            if blend_applied:
                steps.append(DerivationStep(
                    label="Blended Levered Beta",
                    value=final_beta,
                    source="Calculated",
                    formula=(
                        f"{_BLEND_WEIGHT_BOTTOMUP:.0%} Hamada + "
                        f"{_BLEND_WEIGHT_OBSERVED:.0%} Observed "
                        f"(divergence > {_BLEND_DIVERGENCE_THRESHOLD:.0%})"
                    ),
                ))

        trace = DerivationTrace(
            calculator="BetaCalculator",
            result_label="Levered Beta",
            result_value=final_beta,
            steps=steps,
        )

        return BetaResult(
            levered_beta=final_beta,
            unlevered_beta=beta_u,
            de_ratio=de_ratio,
            tax_rate_used=tax_rate,
            trace=trace,
            observed_beta=observed_beta,
            blend_applied=blend_applied,
            hamada_beta=hamada_beta,
        )

    @staticmethod
    def _effective_tax_rate(
        company: CompanyData, industry: IndustryData
    ) -> float:
        """Compute effective tax rate from income statement, fallback to industry."""
        tax_expense = extract_value(company.income_statement, "Income Tax Expense")
        net_income = extract_value(company.income_statement, "Net Income")

        if (
            tax_expense is not None
            and net_income is not None
            and (tax_expense + net_income) > 0
        ):
            pre_tax = tax_expense + net_income
            return tax_expense / pre_tax

        # Fallback to industry average
        industry_tax = tagged_float(industry.avg_tax_rate)
        if industry_tax is not None:
            return industry_tax

        return 0.25  # Conservative default
