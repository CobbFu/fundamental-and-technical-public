"""TerminalSanityCheck — validate terminal value assumptions.

Replicates Damodaran's ImpliedROCROE.xls logic:
    Implied ROC = Terminal Growth / Reinvestment Rate
    If implied ROC > 2x WACC or < cost of capital, flag as unreasonable.
"""

import logging
from dataclasses import dataclass

from src.common.extraction import extract_value, extract_value_multi
from src.common.types import (
    Assumptions,
    CompanyData,
    DerivationStep,
    DerivationTrace,
)

logger = logging.getLogger(__name__)


@dataclass
class SanityResult:
    """Result of terminal value sanity check."""

    implied_roc: float | None
    implied_roe: float | None
    reinvestment_rate: float | None
    is_reasonable: bool
    warnings: list[str]
    trace: DerivationTrace


class TerminalSanityCheck:
    """Checks whether terminal value assumptions imply economically reasonable returns."""

    def check(
        self,
        assumptions: Assumptions,
        company: CompanyData,
        wacc: float | None = None,
    ) -> SanityResult:
        """Check terminal value sanity.

        Always returns a result (never None) — the check itself is informational.
        """
        warnings: list[str] = []
        steps: list[DerivationStep] = []

        terminal_g = assumptions.terminal_growth_rate.value
        steps.append(DerivationStep(
            label="Terminal Growth Rate",
            value=terminal_g,
            source=assumptions.terminal_growth_rate.source,
        ))

        # Use provided WACC or fall back to assumption
        effective_wacc = wacc
        if effective_wacc is None and assumptions.wacc is not None:
            effective_wacc = assumptions.wacc.value
        if effective_wacc is not None:
            steps.append(DerivationStep(
                label="WACC",
                value=effective_wacc,
                source="WACCBuilder" if wacc else assumptions.wacc.source if assumptions.wacc else "default",
            ))

        # Reinvestment rate from assumptions
        capex_pct = assumptions.capex_pct_revenue.value
        nwc_pct = assumptions.nwc_pct_revenue.value

        # Estimate reinvestment rate from operating margin and capex/nwc assumptions
        margin = assumptions.terminal_operating_margin.value
        tax = assumptions.tax_rate.value

        # Reinvestment rate = (CapEx - D&A + delta NWC) / NOPAT
        # Approximate from assumptions: (capex_pct + nwc_pct * terminal_g) / (margin * (1-tax))
        # Simplified: use capex_pct as reinvestment proxy relative to revenue
        nopat_margin = margin * (1 - tax) if margin > 0 else None

        reinvestment_rate: float | None = None
        if nopat_margin is not None and nopat_margin > 0:
            # Net reinvestment as % of revenue ≈ capex_pct (net of depreciation proxy)
            # Use actual D&A if available
            da = extract_value_multi(
                company.cash_flow,
                ["Depreciation and Amortization"],
            )
            revenue = extract_value(company.income_statement, "Revenue")
            capex = extract_value(company.cash_flow, "Capital Expenditure")

            if revenue and revenue > 0 and capex is not None and da is not None:
                net_capex = abs(capex) - da
                delta_nwc = nwc_pct * revenue * terminal_g  # Approximate
                nopat = revenue * nopat_margin
                if nopat > 0:
                    reinvestment_rate = (net_capex + delta_nwc) / nopat
                    steps.append(DerivationStep(
                        label="Net CapEx",
                        value=net_capex,
                        source="FMP cash flow",
                        formula="|CapEx| - D&A",
                    ))
                    steps.append(DerivationStep(
                        label="NOPAT",
                        value=nopat,
                        source="Calculated",
                        formula="Revenue * Margin * (1 - Tax)",
                    ))
                    steps.append(DerivationStep(
                        label="Reinvestment Rate",
                        value=reinvestment_rate,
                        source="Calculated",
                        formula="(Net CapEx + delta NWC) / NOPAT",
                    ))

        # Implied ROC = terminal_g / reinvestment_rate
        implied_roc: float | None = None
        if reinvestment_rate is not None and reinvestment_rate > 0:
            implied_roc = terminal_g / reinvestment_rate
            steps.append(DerivationStep(
                label="Implied ROC",
                value=implied_roc,
                source="Calculated",
                formula="Terminal Growth / Reinvestment Rate",
            ))
        elif reinvestment_rate is not None and reinvestment_rate <= 0:
            warnings.append(
                f"Negative reinvestment rate ({reinvestment_rate:.2%}) — "
                "implies company can grow without investing (very high implied ROC)"
            )

        # Implied ROE (for equity models) — simplified
        implied_roe: float | None = None
        payout_ratio = 1 - (capex_pct / margin) if margin > 0 else None
        if payout_ratio is not None and payout_ratio < 1 and payout_ratio > 0:
            retention = 1 - payout_ratio
            implied_roe = terminal_g / retention
            steps.append(DerivationStep(
                label="Implied ROE",
                value=implied_roe,
                source="Calculated",
                formula="Terminal Growth / (1 - Payout Ratio)",
            ))

        # Reasonableness checks
        is_reasonable = True

        if implied_roc is not None and effective_wacc is not None:
            if implied_roc > 2 * effective_wacc:
                is_reasonable = False
                warnings.append(
                    f"Implied ROC ({implied_roc:.1%}) exceeds 2x WACC ({2 * effective_wacc:.1%}) — "
                    "terminal value may be overstated"
                )
            elif implied_roc < effective_wacc * 0.5:
                warnings.append(
                    f"Implied ROC ({implied_roc:.1%}) is below 50% of WACC ({effective_wacc:.1%}) — "
                    "consider whether the company can sustain growth with such low returns"
                )

        if terminal_g > 0.05:
            is_reasonable = False
            warnings.append(
                f"Terminal growth rate ({terminal_g:.1%}) exceeds 5% — "
                "no company can grow faster than the economy perpetually"
            )

        trace = DerivationTrace(
            calculator="TerminalSanityCheck",
            result_label="Terminal Value Sanity",
            result_value=implied_roc,
            steps=steps,
            warnings=warnings,
        )

        return SanityResult(
            implied_roc=implied_roc,
            implied_roe=implied_roe,
            reinvestment_rate=reinvestment_rate,
            is_reasonable=is_reasonable,
            warnings=warnings,
            trace=trace,
        )
