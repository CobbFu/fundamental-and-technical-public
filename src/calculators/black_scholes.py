"""BlackScholesCalculator — price real options using Damodaran's expand.xls mapping.

Uses standard Black-Scholes call pricing: C = S*N(d1) - K*e^(-rt)*N(d2)
where d1 = [ln(S/K) + (r + sigma^2/2)*t] / (sigma*sqrt(t))
      d2 = d1 - sigma*sqrt(t)
      N(x) = standard normal CDF
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import pandas as pd

from src.common.types import (
    Assumptions,
    DerivationStep,
    DerivationTrace,
    OptionInput,
    OptionResult,
    PipelineData,
)

logger = logging.getLogger(__name__)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class BlackScholesResult:
    call_value: float
    d1: float
    d2: float
    n_d1: float  # delta
    n_d2: float


class BlackScholesCalculator:
    """Prices real options via Black-Scholes with Damodaran warning flags."""

    def price_option(self, inp: OptionInput, shares_outstanding: float) -> OptionResult:
        """Price a single real option. Returns OptionResult with trace."""
        warnings = self._check_warnings(inp)

        # Handle edge case: expired or zero-vol option
        if inp.time_years <= 0:
            return self._expired_result(inp, shares_outstanding, warnings)

        bs = self._black_scholes(
            S=inp.underlying_value,
            K=inp.exercise_cost,
            t=inp.time_years,
            sigma=inp.volatility,
            r=inp.risk_free_rate,
        )

        per_share = bs.call_value / shares_outstanding if shares_outstanding > 0 else 0.0
        weighted = per_share * inp.probability

        # Sensitivity: +10% change in each input
        sensitivity = self._sensitivity(inp, shares_outstanding)

        trace = DerivationTrace(
            calculator="BlackScholesCalculator",
            result_label=f"Option: {inp.option_name}",
            result_value=bs.call_value,
            steps=[
                DerivationStep("S (Underlying Value)", inp.underlying_value, "User input", "PV of project cash flows"),
                DerivationStep("K (Exercise Cost)", inp.exercise_cost, "User input", "Cost of expansion"),
                DerivationStep("t (Time Years)", inp.time_years, "User input", "Window before competition closes"),
                DerivationStep("sigma (Volatility)", inp.volatility, "User input", "Project cash flow variance"),
                DerivationStep("r (Risk-Free Rate)", inp.risk_free_rate, "Market data"),
                DerivationStep("d1", bs.d1, "Calculated", "[ln(S/K) + (r + sigma^2/2)*t] / (sigma*sqrt(t))"),
                DerivationStep("d2", bs.d2, "Calculated", "d1 - sigma*sqrt(t)"),
                DerivationStep("N(d1)", bs.n_d1, "Calculated", "Standard normal CDF"),
                DerivationStep("N(d2)", bs.n_d2, "Calculated", "Standard normal CDF"),
                DerivationStep("Call Value", bs.call_value, "Calculated", "S*N(d1) - K*e^(-rt)*N(d2)"),
                DerivationStep("Per Share", per_share, "Calculated", "Call Value / Shares Outstanding"),
                DerivationStep("Weighted (probability-adjusted)", weighted, "Calculated", f"Per Share * {inp.probability}"),
            ],
            warnings=warnings,
        )

        return OptionResult(
            option_name=inp.option_name,
            call_value=bs.call_value,
            per_share_value=per_share,
            weighted_value=weighted,
            delta=bs.n_d1,
            sensitivity=sensitivity,
            warnings=warnings,
            trace=trace,
        )

    def price_all(
        self,
        options: list[OptionInput],
        shares_outstanding: float,
        dcf_base_per_share: float,
        current_price: float | None,
        ticker: str,
    ) -> "OptionsOverlay":
        """Price all options and build composite overlay."""
        from datetime import datetime, timezone

        from src.common.types import OptionsOverlay

        results = [self.price_option(inp, shares_outstanding) for inp in options]
        total_overlay = sum(r.weighted_value for r in results)
        composite = dcf_base_per_share + total_overlay

        gap_explained = None
        if current_price is not None and current_price > dcf_base_per_share:
            market_gap = current_price - dcf_base_per_share
            gap_explained = total_overlay / market_gap if market_gap > 0 else None

        return OptionsOverlay(
            ticker=ticker,
            options=results,
            total_overlay_per_share=total_overlay,
            dcf_base_per_share=dcf_base_per_share,
            composite_per_share=composite,
            current_price=current_price,
            gap_explained_pct=gap_explained,
            computed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _black_scholes(self, S: float, K: float, t: float, sigma: float, r: float) -> BlackScholesResult:
        """Core Black-Scholes call pricing."""
        if S <= 0:
            return BlackScholesResult(call_value=0.0, d1=float('-inf'), d2=float('-inf'), n_d1=0.0, n_d2=0.0)
        if K <= 0:
            # Strike is zero — option is worth the underlying
            return BlackScholesResult(call_value=S, d1=float('inf'), d2=float('inf'), n_d1=1.0, n_d2=1.0)
        if sigma <= 0:
            # Zero volatility: option value is max(S - K*e^(-rt), 0)
            intrinsic = max(S - K * math.exp(-r * t), 0.0)
            return BlackScholesResult(call_value=intrinsic, d1=float('inf'), d2=float('inf'), n_d1=1.0, n_d2=1.0)

        sqrt_t = math.sqrt(t)
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * t) / (sigma * sqrt_t)
        d2 = d1 - sigma * sqrt_t
        n_d1 = _norm_cdf(d1)
        n_d2 = _norm_cdf(d2)
        call_value = S * n_d1 - K * math.exp(-r * t) * n_d2
        return BlackScholesResult(call_value=call_value, d1=d1, d2=d2, n_d1=n_d1, n_d2=n_d2)

    def _sensitivity(self, inp: OptionInput, shares: float) -> dict[str, float]:
        """Compute sensitivity: change in per-share value for +10% in each input."""
        base = self._black_scholes(inp.underlying_value, inp.exercise_cost, inp.time_years, inp.volatility, inp.risk_free_rate)
        base_ps = base.call_value / shares if shares > 0 else 0.0
        result = {}
        for field_name, bump_pct in [("underlying_value", 0.10), ("exercise_cost", 0.10), ("time_years", 0.10), ("volatility", 0.10)]:
            bumped = OptionInput(**{**inp.__dict__, field_name: getattr(inp, field_name) * (1 + bump_pct)})
            bs = self._black_scholes(bumped.underlying_value, bumped.exercise_cost, bumped.time_years, bumped.volatility, bumped.risk_free_rate)
            bumped_ps = bs.call_value / shares if shares > 0 else 0.0
            result[field_name] = round(bumped_ps - base_ps, 4)
        return result

    def _check_warnings(self, inp: OptionInput) -> list[str]:
        """Damodaran warning flags for speculative inputs."""
        warnings = []
        if inp.volatility > 0.60:
            warnings.append(f"HIGH volatility ({inp.volatility:.0%}) — option value driven by uncertainty, not fundamentals")
        if inp.time_years > 10:
            warnings.append(f"Long time window ({inp.time_years}y) — competitive moat assumption may not hold")
        if inp.underlying_value > inp.exercise_cost * 5:
            warnings.append("S >> K — deep in-the-money, option value approaches NPV (less optionality value)")
        if inp.underlying_value < inp.exercise_cost * 0.2:
            warnings.append("S << K — deep out-of-the-money, option value is almost entirely time value")
        if inp.probability < 0.5:
            warnings.append(f"Low exercise probability ({inp.probability:.0%}) — heavily discounted")
        return warnings

    def _expired_result(self, inp: OptionInput, shares: float, warnings: list[str]) -> OptionResult:
        """Handle expired option (t <= 0)."""
        intrinsic = max(inp.underlying_value - inp.exercise_cost, 0.0)
        per_share = intrinsic / shares if shares > 0 else 0.0
        trace = DerivationTrace(
            calculator="BlackScholesCalculator",
            result_label=f"Option: {inp.option_name} (expired)",
            result_value=intrinsic,
            steps=[DerivationStep("Intrinsic Value", intrinsic, "Calculated", "max(S - K, 0)")],
            warnings=warnings + ["Option expired — intrinsic value only"],
        )
        return OptionResult(
            option_name=inp.option_name,
            call_value=intrinsic,
            per_share_value=per_share,
            weighted_value=per_share * inp.probability,
            delta=1.0 if intrinsic > 0 else 0.0,
            sensitivity={},
            warnings=trace.warnings,
            trace=trace,
        )


def detect_options(
    data: PipelineData,
    assumptions: Assumptions,
    dcf_per_share: float,
    shares_outstanding: float,
) -> list[OptionInput]:
    """Auto-detect growth options from company data.

    Uses market cap vs DCF gap, R&D intensity, and capex to generate
    candidate real options. Returns empty list when optionality is not
    warranted (market cap close to DCF value).
    """
    company = data.company
    risk_free = data.macro.risk_free_rate.value if data.macro.risk_free_rate else 0.04

    # Market cap and DCF gap
    market_cap = company.market_cap.value if company.market_cap else None
    if market_cap is None or dcf_per_share <= 0:
        return []

    dcf_total = dcf_per_share * shares_outstanding
    gap_ratio = market_cap / dcf_total if dcf_total > 0 else 1.0

    # Only generate options when market prices in optionality (market > DCF)
    if gap_ratio < 1.0:
        logger.info("Market cap / DCF ratio %.1fx — stock undervalued, no optionality to explain", gap_ratio)
        return []

    if gap_ratio < 2.0:
        logger.info("Market cap / DCF ratio %.1fx — modest optionality, generating basic options", gap_ratio)
    else:
        logger.info("Market cap / DCF ratio %.1fx — significant optionality detected", gap_ratio)

    optionality_gap = market_cap - dcf_total  # total $ the market prices beyond DCF

    # Extract financials
    revenue = _latest_value(company.income_statement, ["Revenue", "revenue", "Total Revenue"])
    rd_expense = _extract_rd(company)
    capex = abs(_latest_value(company.cash_flow, ["Capital Expenditure", "capital_expenditure"]))

    if revenue is None or revenue <= 0:
        return []

    rd_intensity = rd_expense / revenue if rd_expense and rd_expense > 0 else 0.0

    # Industry volatility proxy: unlevered beta as base, scaled up for growth options
    base_beta = data.industry.unlevered_beta.value if data.industry.unlevered_beta else 1.0
    # Growth project volatility is higher than firm-level — Damodaran uses 40-80% for real options
    project_volatility = min(max(base_beta * 0.40, 0.35), 0.80)

    options: list[OptionInput] = []

    # Option 1: R&D-driven growth (new products/markets from R&D pipeline)
    # S = PV of potential revenue from R&D (scaled from R&D spend and industry multiplier)
    # K = cumulative R&D + commercialization cost
    if rd_intensity > 0.03:  # >3% R&D intensity suggests innovation pipeline
        rd_revenue_multiple = 8.0  # PV of revenue per $ of R&D (conservative tech avg)
        s_value = rd_expense * rd_revenue_multiple
        k_value = rd_expense * 5  # 5 years of R&D + commercialization
        options.append(OptionInput(
            option_name="R&D / New Products",
            underlying_value=s_value,
            exercise_cost=k_value,
            time_years=5.0,
            volatility=project_volatility,
            risk_free_rate=risk_free,
            probability=0.6,
            narrative=(
                f"Option to commercialize R&D pipeline. R&D intensity {rd_intensity:.1%} "
                f"of revenue (${rd_expense / 1e9:.1f}B). S based on {rd_revenue_multiple}x "
                f"R&D spend as PV of project cash flows."
            ),
        ))

    # Option 2: Market expansion (scaling existing business into adjacent TAMs)
    # Generate for any gap > 1.0 (market > DCF)
    if capex > 0 and gap_ratio > 1.0:
        # The market sees something beyond current operations
        # Use a fraction of the gap as the addressable opportunity
        expansion_s = optionality_gap * 0.30  # 30% of gap = identifiable expansion
        expansion_k = capex * 5  # 5 years of current capex rate
        options.append(OptionInput(
            option_name="Market Expansion",
            underlying_value=expansion_s,
            exercise_cost=expansion_k,
            time_years=7.0,
            volatility=min(project_volatility + 0.10, 0.80),
            risk_free_rate=risk_free,
            probability=0.5 if gap_ratio < 2.0 else 0.3,  # Higher prob for smaller gaps
            narrative=(
                f"Option to expand into adjacent markets. Market prices "
                f"{gap_ratio:.0f}x DCF value (${optionality_gap / 1e9:.0f}B gap). "
                f"S = 30% of gap, K = 5yr capex at current rate "
                f"(${capex / 1e9:.1f}B/yr)."
            ),
        ))

    # Option 3: Platform/ecosystem optionality (for large-cap tech with high gap)
    # Lower threshold to 2.0 for more inclusion
    if gap_ratio > 2.0 and revenue > 20e9:
        platform_s = optionality_gap * 0.20
        platform_k = revenue * 0.5  # half a year's revenue as investment
        options.append(OptionInput(
            option_name="Platform / Ecosystem",
            underlying_value=platform_s,
            exercise_cost=platform_k,
            time_years=10.0,
            volatility=0.70,  # high — speculative by nature
            risk_free_rate=risk_free,
            probability=0.15,
            narrative=(
                f"Option on platform/ecosystem value beyond current business. "
                f"Highly speculative — {gap_ratio:.0f}x DCF gap suggests market "
                f"prices in transformative optionality."
            ),
        ))

    if options:
        logger.info(
            "Auto-detected %d growth option(s) for %s (market/DCF ratio: %.1fx)",
            len(options), data.ticker, gap_ratio,
        )

    return options


def _latest_value(df: pd.DataFrame | None, labels: list[str]) -> float | None:
    """Extract latest non-zero value from a DataFrame row."""
    if df is None or df.empty:
        return None
    for label in labels:
        if label in df.index:
            series = df.loc[label].dropna().sort_index()
            # Skip trailing zeros (missing data)
            for val in reversed(series.values):
                v = float(val)
                if v != 0.0:
                    return v
    return None


def _extract_rd(company) -> float | None:
    """Extract R&D expense from key_metrics or income statement."""
    # Try key_metrics first (pre-extracted)
    for key in ["Research and Development Expenses", "research_and_development_expenses"]:
        if key in company.key_metrics:
            val = company.key_metrics[key].value
            if val and float(val) > 0:
                return float(val)
    # Fall back to income statement
    return _latest_value(
        company.income_statement,
        ["Research And Development Expenses", "research_and_development_expenses", "R&D Expenses"],
    )
