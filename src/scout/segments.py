"""Segment extraction from EDGAR 10-K filings via edgartools XBRL."""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

from src.comps.sotp_types import SegmentData, SegmentFinancials

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


class SegmentExtractionError(Exception):
    """Raised when segment data cannot be extracted from EDGAR."""


# Revenue concept fallback chain
_REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenue",
    "Revenues",
]

# Operating income concept fallback chain
_OI_CONCEPTS = [
    "OperatingIncomeLoss",
    "OperatingIncome",
]

# Segment dimension axis
_SEGMENT_AXIS = "StatementBusinessSegmentsAxis"


class SegmentFetcher:
    """Extracts business segments from the latest 10-K via edgartools XBRL."""

    def __init__(self, user_agent: str) -> None:
        self._user_agent = user_agent

    def fetch_segments(self, ticker: str) -> list[SegmentData]:
        """Extract business segments from the latest 10-K filing.

        Returns:
            List of SegmentData with revenue, operating income, and derived metrics.

        Raises:
            SegmentExtractionError: If no 10-K found or no segment data available.
        """
        import edgar

        edgar.set_identity(self._user_agent)

        try:
            company = edgar.Company(ticker)
        except Exception as e:
            raise SegmentExtractionError(
                f"Cannot find company '{ticker}' in EDGAR: {e}",
            ) from e

        try:
            tenk = company.latest_tenk
        except Exception as e:
            raise SegmentExtractionError(
                f"No 10-K filing found for '{ticker}': {e}",
            ) from e

        if tenk is None:
            raise SegmentExtractionError(
                f"No 10-K filing available for '{ticker}'",
            )

        try:
            filing = tenk._filing  # noqa: SLF001
            xbrl = filing.xbrl()
        except Exception as e:
            raise SegmentExtractionError(
                f"Cannot access XBRL data for '{ticker}' 10-K: {e}",
            ) from e

        if xbrl is None:
            raise SegmentExtractionError(
                f"No XBRL data in '{ticker}' 10-K filing",
            )

        # Extract revenue by segment
        rev_df = self._query_concept(xbrl, _REVENUE_CONCEPTS)
        if rev_df is None or rev_df.empty:
            raise SegmentExtractionError(
                f"Segment revenue data not available via EDGAR for '{ticker}'",
            )

        # Extract operating income by segment (optional — not all filers have it)
        oi_df = self._query_concept(xbrl, _OI_CONCEPTS)

        # Build segment list from revenue data
        segments = self._build_segments(rev_df, oi_df)

        if not segments:
            raise SegmentExtractionError(
                f"No segment data could be parsed from '{ticker}' 10-K XBRL",
            )

        logger.info(
            "Extracted %d segments for %s from EDGAR 10-K",
            len(segments), ticker,
        )
        return segments

    def _query_concept(self, xbrl: object, concepts: list[str]) -> pd.DataFrame | None:
        """Try each concept in the fallback chain, return first successful result."""
        for concept in concepts:
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore", message=".*include_dimensions.*deprecated.*",
                    )
                    df = (
                        xbrl.query(include_dimensions=True)  # type: ignore[union-attr]
                        .by_concept(concept, exact=False)
                        .by_dimension(_SEGMENT_AXIS)
                        .to_dataframe()
                    )
                if df is not None and not df.empty:
                    return df
            except Exception:
                continue
        return None

    def _build_segments(
        self,
        rev_df: pd.DataFrame,
        oi_df: pd.DataFrame | None,
    ) -> list[SegmentData]:
        """Build SegmentData list from revenue and operating income DataFrames."""
        # Identify the segment name column
        seg_col = "dimension_member_label"
        if seg_col not in rev_df.columns:
            logger.warning("Expected column '%s' not found in XBRL output", seg_col)
            return []

        # Identify fiscal year column
        fy_col = "fiscal_year" if "fiscal_year" in rev_df.columns else None

        # Get unique segments
        segment_names = rev_df[seg_col].unique()

        segments: list[SegmentData] = []
        for name in segment_names:
            seg_rev = rev_df[rev_df[seg_col] == name].copy()
            if seg_rev.empty:
                continue

            # Sort by fiscal year to get latest and prior
            if fy_col and fy_col in seg_rev.columns:
                seg_rev = seg_rev.sort_values(fy_col, ascending=False)

            # Latest year revenue
            revenue = float(seg_rev.iloc[0]["numeric_value"])
            fiscal_year = int(seg_rev.iloc[0][fy_col]) if fy_col else None

            # Prior year revenue (for growth calc)
            revenue_prior = None
            revenue_growth = None
            if len(seg_rev) >= 2:
                revenue_prior = float(seg_rev.iloc[1]["numeric_value"])
                if revenue_prior and revenue_prior != 0:
                    revenue_growth = (revenue - revenue_prior) / abs(revenue_prior)

            # Operating income for this segment
            operating_income = None
            operating_margin = None
            if oi_df is not None and not oi_df.empty and seg_col in oi_df.columns:
                seg_oi = oi_df[oi_df[seg_col] == name]
                if fy_col and fy_col in seg_oi.columns:
                    seg_oi = seg_oi.sort_values(fy_col, ascending=False)
                if not seg_oi.empty:
                    operating_income = float(seg_oi.iloc[0]["numeric_value"])
                    if revenue and revenue != 0:
                        operating_margin = operating_income / revenue

            financials = SegmentFinancials(
                revenue=revenue,
                operating_income=operating_income,
                operating_margin=operating_margin,
                revenue_prior=revenue_prior,
                revenue_growth=revenue_growth,
            )

            segments.append(SegmentData(
                name=str(name),
                source="edgar",
                financials=financials,
                fiscal_year=fiscal_year,
            ))

        return segments

    def merge_overrides(
        self,
        edgar_segments: list[SegmentData],
        overrides: list[dict],
    ) -> list[SegmentData]:
        """Merge user-defined analytical segments into EDGAR segments.

        Override replaces by name match; new names are appended.
        """
        result = list(edgar_segments)
        existing_names = {s.name.lower(): i for i, s in enumerate(result)}

        for override in overrides:
            name = override.get("name", "")
            financials = SegmentFinancials(
                revenue=override.get("revenue"),
                operating_income=override.get("operating_income"),
                operating_margin=override.get("operating_margin"),
                revenue_prior=override.get("revenue_prior"),
                revenue_growth=override.get("revenue_growth"),
                capex=override.get("capex"),
                depreciation=override.get("depreciation"),
            )
            seg = SegmentData(
                name=name,
                source="user_override",
                industry=override.get("industry", ""),
                financials=financials,
                fiscal_year=override.get("fiscal_year"),
            )

            key = name.lower()
            if key in existing_names:
                result[existing_names[key]] = seg
            else:
                result.append(seg)

        return result
