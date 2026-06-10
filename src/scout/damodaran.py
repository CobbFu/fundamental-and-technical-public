"""Wrapper around compdata for Damodaran industry datasets.

compdata's Industry.get_*() methods return a pandas **Series** (not DataFrame)
with lowercase index labels and string values (e.g., '1.23', '5.51%', '$210,887').
This module handles parsing, type conversion, and normalization.
"""

import logging
from datetime import datetime, timezone

import pandas as pd
from compdata.comp_data import Industry, Market, industry_name_list

from src.common.types import IndustryData, SourceTag, TaggedValue

logger = logging.getLogger(__name__)

AVAILABLE_DATASETS = [
    "betas",
    "cost_of_capital",
    "margins",
    "industry_tax_rates",
    "ev_multiples",
    "revenue_multiples",
    "price_earnings",
    "price_book",
    "roe",
    "dividends_fcfe",
    "debt_fundamentals",
    "debt_details",
    "capital_expenditures",
    "working_capital",
    "ebit_growth",
    "eps_growth",
    "historical_growth",
    "eva",
    "standard_deviation",
    "total_betas",
    "leases",
    "holdings",
]


def _parse_value(raw: object) -> float | None:
    """Parse a compdata string value into a float.

    Handles: '1.23', '5.51%', '$210,887.43', '\xa0$\xa0\xa0210,887.43\xa0',
    and plain numeric types.

    Percentages are converted to decimals (e.g., '5.51%' → 0.0551).
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)

    s = str(raw).strip()
    if not s or s.lower() in ("na", "n/a", "-", ""):
        return None

    is_pct = "%" in s

    # Strip currency symbols, whitespace variants, commas
    s = s.replace("\xa0", "").replace("$", "").replace(",", "").replace("%", "").strip()

    # Handle parenthetical negatives: (123.45) → -123.45
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]

    try:
        val = float(s)
    except (TypeError, ValueError):
        return None

    if is_pct:
        val = val / 100.0

    return val


def _series_get(series: pd.Series, key: str) -> float | None:
    """Look up a key in a compdata Series (case-insensitive, \xa0-tolerant).

    Handles duplicate index entries by using positional access (.iloc).
    Returns the first matching value that parses successfully.
    """
    key_lower = key.lower().strip()
    for i, idx in enumerate(series.index):
        idx_clean = str(idx).replace("\xa0", " ").strip().lower()
        if idx_clean == key_lower:
            raw = series.iloc[i]  # positional — safe with duplicate indices
            val = _parse_value(raw)
            if val is not None:
                return val
    return None


def _series_to_dataframe(series: pd.Series) -> pd.DataFrame:
    """Convert a compdata Series to a single-row DataFrame.

    Handles duplicate index entries by deduplicating with suffix.
    """
    # Deduplicate index entries
    seen: dict[str, int] = {}
    new_index = []
    for idx in series.index:
        key = str(idx)
        if key in seen:
            seen[key] += 1
            new_index.append(f"{key}_{seen[key]}")
        else:
            seen[key] = 0
            new_index.append(key)
    series_copy = series.copy()
    series_copy.index = pd.Index(new_index)
    return pd.DataFrame([series_copy])


class DamodaranFetcher:
    """Fetches Damodaran industry datasets via compdata."""

    def _source_tag(self, fiscal_period: str = "latest") -> SourceTag:
        return SourceTag(
            source="Damodaran",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            fiscal_period=fiscal_period,
        )

    def list_available_datasets(self) -> list[str]:
        return list(AVAILABLE_DATASETS)

    def list_industries(self) -> list[str]:
        return list(industry_name_list)

    def get_industry_betas(self) -> pd.Series:
        try:
            ind = Industry(industry_name_list[0])
            return ind.get_betas()  # type: ignore[no-any-return]
        except Exception:
            logger.exception("Failed to fetch betas from Damodaran")
            raise

    def get_cost_of_capital(self) -> pd.Series:
        try:
            ind = Industry(industry_name_list[0])
            return ind.get_cost_of_capital()  # type: ignore[no-any-return]
        except Exception:
            logger.exception("Failed to fetch cost of capital from Damodaran")
            raise

    def get_equity_risk_premium(self) -> pd.DataFrame:
        try:
            mkt = Market()
            return mkt.get_risk_premiums_US()  # type: ignore[no-any-return]
        except Exception:
            logger.exception("Failed to fetch ERP from Damodaran")
            raise

    def get_operating_margins(self) -> pd.Series:
        try:
            ind = Industry(industry_name_list[0])
            return ind.get_margins()  # type: ignore[no-any-return]
        except Exception:
            logger.exception("Failed to fetch margins from Damodaran")
            raise

    def get_tax_rates(self) -> pd.Series:
        try:
            ind = Industry(industry_name_list[0])
            return ind.get_industry_tax_rates()  # type: ignore[no-any-return]
        except Exception:
            logger.exception("Failed to fetch tax rates from Damodaran")
            raise

    def get_industry_data(self, industry: str) -> IndustryData:
        """Fetch all available data for a specific industry.

        Args:
            industry: Damodaran industry name (e.g., "Software (System & Application)")
        """
        if industry not in industry_name_list:
            raise ValueError(
                f"Unknown industry: {industry}. "
                f"Use list_industries() for valid names."
            )

        tag = self._source_tag()
        ind = Industry(industry)

        datasets: dict[str, pd.DataFrame] = {}
        unlevered_beta: TaggedValue | None = None
        equity_risk_premium: TaggedValue | None = None
        avg_wacc: TaggedValue | None = None
        avg_operating_margin: TaggedValue | None = None
        avg_tax_rate: TaggedValue | None = None

        # Fetch betas (returns Series)
        try:
            betas_series = ind.get_betas()
            datasets["betas"] = _series_to_dataframe(betas_series)
            val = _series_get(betas_series, "unlevered beta")
            if val is not None:
                unlevered_beta = TaggedValue(value=val, tag=tag)
                logger.info("Unlevered beta for %s: %.2f", industry, val)
        except Exception:
            logger.warning("Failed to fetch betas for %s", industry)

        # Fetch cost of capital (returns Series)
        try:
            coc_series = ind.get_cost_of_capital()
            datasets["cost_of_capital"] = _series_to_dataframe(coc_series)
            val = _series_get(coc_series, "cost of capital")
            if val is not None:
                avg_wacc = TaggedValue(value=val, tag=tag)
                logger.info("WACC for %s: %.2f%%", industry, val * 100)
        except Exception:
            logger.warning("Failed to fetch cost of capital for %s", industry)

        # Fetch margins (returns Series)
        try:
            margins_series = ind.get_margins()
            datasets["margins"] = _series_to_dataframe(margins_series)
            val = _series_get(
                margins_series, "pre-tax, pre-stock compensation operating margin"
            )
            if val is not None:
                avg_operating_margin = TaggedValue(
                    value=val, tag=tag,
                    note="Pre-tax, pre-stock compensation operating margin",
                )
                logger.info("Operating margin for %s: %.2f%%", industry, val * 100)
        except Exception:
            logger.warning("Failed to fetch margins for %s", industry)

        # Fetch tax rates (returns Series — has duplicate index entries)
        try:
            tax_series = ind.get_industry_tax_rates()
            datasets["tax_rates"] = _series_to_dataframe(tax_series)
            # Use "aggregate tax rate" (last occurrence = cash-based)
            # or "average across only money-making companies" as preferred measure
            val = _series_get(tax_series, "aggregate tax rate")
            if val is not None:
                avg_tax_rate = TaggedValue(
                    value=val, tag=tag,
                    note="Aggregate tax rate",
                )
                logger.info("Tax rate for %s: %.2f%%", industry, val * 100)
        except Exception:
            logger.warning("Failed to fetch tax rates for %s", industry)

        # Fetch equity risk premium from Market data (returns DataFrame)
        try:
            mkt = Market()
            erp_df = mkt.get_risk_premiums_US()
            if isinstance(erp_df, pd.DataFrame) and not erp_df.empty:
                datasets["equity_risk_premium"] = erp_df
                # Find implied ERP column
                erp_col = None
                for col in erp_df.columns:
                    if "implied" in col.lower() and "erp" in col.lower():
                        erp_col = col
                        break
                if erp_col is not None:
                    # Walk backwards to find latest row with actual data
                    # (last row is often empty padding)
                    for i in range(len(erp_df) - 1, -1, -1):
                        val = _parse_value(erp_df.iloc[i][erp_col])
                        if val is not None:
                            equity_risk_premium = TaggedValue(
                                value=val, tag=tag,
                                note=f"Implied ERP (FCFE), {erp_df.index[i]}",
                            )
                            logger.info("Equity risk premium: %.2f%%", val * 100)
                            break
        except Exception:
            logger.warning("Failed to fetch equity risk premium")

        # Fetch additional datasets for downstream use
        for ds_name, method_name in [
            ("debt_fundamentals", "get_debt_fundamentals"),
            ("working_capital", "get_working_capital"),
            ("capital_expenditures", "get_capital_expenditures"),
        ]:
            try:
                method = getattr(ind, method_name)
                result = method()
                if isinstance(result, pd.Series):
                    datasets[ds_name] = _series_to_dataframe(result)
                else:
                    datasets[ds_name] = result
            except Exception:
                logger.warning("Failed to fetch %s for %s", ds_name, industry)

        return IndustryData(
            industry_name=industry,
            unlevered_beta=unlevered_beta,
            equity_risk_premium=equity_risk_premium,
            avg_wacc=avg_wacc,
            avg_operating_margin=avg_operating_margin,
            avg_tax_rate=avg_tax_rate,
            datasets=datasets,
        )
