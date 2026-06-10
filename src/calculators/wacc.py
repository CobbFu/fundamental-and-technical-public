"""WACCBuilder — build company-specific WACC from components.

Replicates Damodaran's wacccalc.xls logic:
    Ke = Rf + Beta_L * ERP
    After-tax Kd from SyntheticRating
    WACC = Ke * We + After-tax Kd * Wd
    Weights use MARKET value of equity (not book value).
"""

import logging
from dataclasses import dataclass

from src.calculators.beta import BetaCalculator, BetaResult
from src.calculators.synthetic_rating import RatingResult, SyntheticRating
from src.common.extraction import extract_value_multi, tagged_float
from src.common.types import (
    CompanyData,
    DerivationStep,
    DerivationTrace,
    IndustryData,
    MacroData,
)

logger = logging.getLogger(__name__)


@dataclass
class WACCResult:
    """Result of WACC calculation."""

    wacc: float
    cost_of_equity: float
    cost_of_debt_pretax: float
    cost_of_debt_aftertax: float
    weight_equity: float
    weight_debt: float
    levered_beta: float
    erp: float
    risk_free_rate: float
    beta_result: BetaResult
    rating_result: RatingResult
    trace: DerivationTrace


class WACCBuilder:
    """Builds company-specific WACC from BetaCalculator + SyntheticRating."""

    def __init__(
        self,
        beta_calc: BetaCalculator,
        rating_calc: SyntheticRating,
    ):
        self._beta_calc = beta_calc
        self._rating_calc = rating_calc

    def calculate(
        self,
        company: CompanyData,
        industry: IndustryData,
        macro: MacroData,
    ) -> WACCResult | None:
        """Calculate company-specific WACC.

        Returns None if BetaCalculator or SyntheticRating fails.
        """
        # 1. Beta
        beta_result = self._beta_calc.calculate(
            company, industry, observed_beta=company.observed_beta,
        )
        if beta_result is None:
            logger.warning("BetaCalculator returned None — cannot build WACC")
            return None

        # 2. Cost of Debt
        rating_result = self._rating_calc.calculate(company, industry, macro)
        if rating_result is None:
            logger.warning("SyntheticRating returned None — cannot build WACC")
            return None

        # 3. ERP and Risk-free rate
        erp = tagged_float(industry.equity_risk_premium)
        if erp is None:
            logger.warning("No ERP available — cannot build WACC")
            return None

        rf = tagged_float(macro.risk_free_rate)
        if rf is None:
            logger.warning("No risk-free rate — cannot build WACC")
            return None

        # 4. Cost of Equity: Ke = Rf + Beta_L * ERP
        ke = rf + beta_result.levered_beta * erp

        # 5. Market-value weights
        market_cap = tagged_float(company.market_cap)
        if market_cap is None or market_cap <= 0:
            logger.warning("No market cap — cannot compute WACC weights")
            return None

        total_debt = extract_value_multi(
            company.balance_sheet, ["Total Debt", "Long Term Debt"]
        )
        if total_debt is None:
            total_debt = 0.0

        total_capital = market_cap + total_debt
        we = market_cap / total_capital
        wd = total_debt / total_capital

        # 6. WACC = Ke * We + After-tax Kd * Wd
        wacc = ke * we + rating_result.after_tax_cost_of_debt * wd

        trace = DerivationTrace(
            calculator="WACCBuilder",
            result_label="WACC",
            result_value=wacc,
            steps=[
                DerivationStep(
                    label="Risk-Free Rate",
                    value=rf,
                    source="FRED 10Y Treasury",
                ),
                DerivationStep(
                    label="Levered Beta",
                    value=beta_result.levered_beta,
                    source="BetaCalculator",
                    formula="beta_U * (1 + (1-t) * D/E)",
                ),
                DerivationStep(
                    label="Equity Risk Premium",
                    value=erp,
                    source="Damodaran implied ERP",
                ),
                DerivationStep(
                    label="Cost of Equity (Ke)",
                    value=ke,
                    source="Calculated",
                    formula="Rf + Beta_L * ERP",
                ),
                DerivationStep(
                    label="Pre-tax Cost of Debt (Kd)",
                    value=rating_result.pre_tax_cost_of_debt,
                    source="SyntheticRating",
                    formula="Rf + Default Spread",
                ),
                DerivationStep(
                    label="After-tax Cost of Debt",
                    value=rating_result.after_tax_cost_of_debt,
                    source="SyntheticRating",
                    formula="Kd * (1 - marginal tax rate)",
                ),
                DerivationStep(
                    label="Market Cap (Equity)",
                    value=market_cap,
                    source="yfinance",
                ),
                DerivationStep(
                    label="Total Debt",
                    value=total_debt,
                    source="FMP balance sheet",
                ),
                DerivationStep(
                    label="Weight of Equity",
                    value=we,
                    source="Calculated",
                    formula="Market Cap / (Market Cap + Total Debt)",
                ),
                DerivationStep(
                    label="Weight of Debt",
                    value=wd,
                    source="Calculated",
                    formula="Total Debt / (Market Cap + Total Debt)",
                ),
                DerivationStep(
                    label="WACC",
                    value=wacc,
                    source="Calculated",
                    formula="Ke * We + After-tax Kd * Wd",
                ),
            ],
        )

        return WACCResult(
            wacc=wacc,
            cost_of_equity=ke,
            cost_of_debt_pretax=rating_result.pre_tax_cost_of_debt,
            cost_of_debt_aftertax=rating_result.after_tax_cost_of_debt,
            weight_equity=we,
            weight_debt=wd,
            levered_beta=beta_result.levered_beta,
            erp=erp,
            risk_free_rate=rf,
            beta_result=beta_result,
            rating_result=rating_result,
            trace=trace,
        )
