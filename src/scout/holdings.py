"""Fetch insider and institutional holdings data from yfinance + edgartools."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.common.types import (
    Form4Transaction,
    HoldingsData,
    InsiderHolder,
    InsiderSummary,
    InstitutionalHolder,
)

logger = logging.getLogger(__name__)


class HoldingsFetcher:
    """Fetches insider ownership, institutional holders, and Form 4 transactions."""

    def __init__(self, user_agent: str) -> None:
        self._user_agent = user_agent

    def fetch_all(self, ticker: str) -> HoldingsData:
        """Fetch insider, institutional, and Form 4 data. Soft-fails per source."""
        insider = self._fetch_insider_summary(ticker)
        institutional = self._fetch_institutional_holders(ticker)
        form4 = self._fetch_form4_activity(ticker)
        return HoldingsData(
            ticker=ticker,
            insider_summary=insider,
            institutional_holders=institutional,
            form4_transactions=form4,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
        )

    def _fetch_insider_summary(self, ticker: str) -> InsiderSummary | None:
        """yfinance: major_holders + insider_roster_holders."""
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)

            # Parse major_holders for ownership percentages
            insider_pct: float | None = None
            institution_pct: float | None = None
            mh = t.major_holders
            if mh is not None and not mh.empty:
                for idx_label, row in mh.iterrows():
                    label = str(idx_label).lower()
                    val = row.iloc[0] if len(row) > 0 else row.get("Value")
                    if val is None:
                        continue
                    try:
                        numeric_val = float(val)
                    except (TypeError, ValueError):
                        continue
                    # Match "% of Shares Held by ..." rows only
                    # Skip "% of Float" and count rows
                    if "% of shares held" not in label:
                        continue
                    if "insider" in label:
                        insider_pct = numeric_val
                    elif "institution" in label:
                        institution_pct = numeric_val

            # Parse insider_roster_holders for top insiders
            top_insiders: list[InsiderHolder] = []
            roster = t.insider_roster_holders
            if roster is not None and not roster.empty:
                for _, row in roster.head(10).iterrows():
                    name = str(row.get("Name", ""))
                    if not name or name == "nan":
                        continue
                    shares_direct = _safe_int(row.get("Shares Owned Directly"))
                    shares_indirect = _safe_int(row.get("Shares Owned Indirectly"))
                    latest_txn = str(row.get("Most Recent Transaction", ""))
                    latest_date = _safe_date(row.get("Latest Transaction Date"))
                    top_insiders.append(InsiderHolder(
                        name=name,
                        position=str(row.get("Position", "")),
                        shares_direct=shares_direct,
                        shares_indirect=shares_indirect,
                        latest_transaction=latest_txn if latest_txn != "nan" else "",
                        latest_transaction_date=latest_date,
                    ))

            return InsiderSummary(
                insider_ownership_pct=insider_pct,
                institution_ownership_pct=institution_pct,
                top_insiders=top_insiders,
            )
        except Exception:
            logger.warning("Failed to fetch insider summary for %s", ticker, exc_info=True)
            return None

    def _fetch_institutional_holders(self, ticker: str) -> list[InstitutionalHolder]:
        """yfinance: institutional_holders (top 10)."""
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)
            ih = t.institutional_holders
            if ih is None or ih.empty:
                return []

            logger.info(
                "Institutional holder data may have known accuracy issues "
                "(yfinance #2242) — use for directional signals only",
            )

            holders: list[InstitutionalHolder] = []
            for _, row in ih.head(10).iterrows():
                holder_name = str(row.get("Holder", ""))
                if not holder_name or holder_name == "nan":
                    continue
                holders.append(InstitutionalHolder(
                    holder=holder_name,
                    shares=_safe_int(row.get("Shares")),
                    value=_safe_float(row.get("Value")),
                    date_reported=_safe_date(row.get("Date Reported")),
                ))
            return holders
        except Exception:
            logger.warning(
                "Failed to fetch institutional holders for %s", ticker, exc_info=True,
            )
            return []

    def _fetch_form4_activity(
        self, ticker: str, limit: int = 20,
    ) -> list[Form4Transaction]:
        """Fetch Form 4 transactions from yfinance (primary) + edgartools (enrichment)."""
        transactions: list[Form4Transaction] = []

        # Primary: yfinance insider_transactions
        transactions.extend(self._fetch_yfinance_transactions(ticker, limit))

        # Enrichment: edgartools Form 4 filings
        edgar_txns = self._fetch_edgar_form4(ticker, limit)
        # Append unique edgar transactions (avoid duplicates by date+name)
        existing_keys = {
            (t.insider_name.lower(), t.transaction_date)
            for t in transactions
        }
        for et in edgar_txns:
            key = (et.insider_name.lower(), et.transaction_date)
            if key not in existing_keys:
                transactions.append(et)
                existing_keys.add(key)

        return transactions[:limit]

    def _fetch_yfinance_transactions(
        self, ticker: str, limit: int,
    ) -> list[Form4Transaction]:
        """Pull insider transactions from yfinance."""
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)
            it = t.insider_transactions
            if it is None or (hasattr(it, "empty") and it.empty):
                return []

            txns: list[Form4Transaction] = []
            for _, row in it.head(limit).iterrows():
                insider_name = str(row.get("Insider", row.get("insider", "")))
                if not insider_name or insider_name == "nan":
                    continue
                txn_text = str(row.get("Transaction", row.get("Text", "")))
                txn_type = _classify_transaction(txn_text)
                txns.append(Form4Transaction(
                    insider_name=insider_name,
                    insider_position=str(row.get("Position", "")),
                    transaction_type=txn_type,
                    transaction_date=_safe_date(row.get("Start Date")),
                    shares=_safe_int(row.get("Shares")),
                    price_per_share=_safe_float(row.get("Value")),
                    value=None,  # yfinance doesn't always provide total value
                    source="yfinance",
                ))
            return txns
        except Exception:
            logger.warning(
                "Failed to fetch yfinance transactions for %s", ticker, exc_info=True,
            )
            return []

    def _fetch_edgar_form4(
        self, ticker: str, limit: int,
    ) -> list[Form4Transaction]:
        """Pull Form 4 filings from edgartools."""
        try:
            from edgar import Company, set_identity

            set_identity(self._user_agent)
            company = Company(ticker)
            filings = company.get_filings(form="4")

            txns: list[Form4Transaction] = []
            for filing in filings[:limit]:
                try:
                    form4 = filing.obj()
                    if form4 is None:
                        continue

                    # Try to extract reporting owner info
                    owner_name = ""
                    owner_position = ""
                    if hasattr(form4, "reporting_owner"):
                        ro = form4.reporting_owner
                        owner_name = str(getattr(ro, "name", ""))
                        owner_position = str(getattr(ro, "title", ""))

                    # Try to get transaction details from DataFrame
                    df = None
                    if hasattr(form4, "to_dataframe"):
                        df = form4.to_dataframe()
                    if df is not None and not df.empty:
                        for _, row in df.iterrows():
                            txn_code = str(row.get("transaction_code", ""))
                            txn_type = "Purchase" if txn_code in ("P", "A") else "Sale"
                            txns.append(Form4Transaction(
                                insider_name=owner_name or str(row.get("reporting_owner", "")),
                                insider_position=owner_position,
                                transaction_type=txn_type,
                                transaction_date=_safe_date(row.get("transaction_date")),
                                shares=_safe_int(row.get("shares")),
                                price_per_share=_safe_float(row.get("price_per_share")),
                                value=_safe_float(row.get("value")),
                                source="edgar",
                            ))
                    elif hasattr(form4, "get_ownership_summary"):
                        summary = form4.get_ownership_summary()
                        if summary:
                            activity = str(getattr(summary, "primary_activity", ""))
                            txn_type = "Purchase" if "acqui" in activity.lower() else "Sale"
                            txns.append(Form4Transaction(
                                insider_name=getattr(summary, "insider_name", owner_name),
                                insider_position=owner_position,
                                transaction_type=txn_type,
                                transaction_date=str(getattr(filing, "filing_date", "")),
                                shares=_safe_int(getattr(summary, "net_change", None)),
                                source="edgar",
                            ))
                except Exception:
                    logger.debug(
                        "Failed to parse Form 4 filing for %s", ticker, exc_info=True,
                    )
                    continue

            return txns
        except Exception:
            logger.warning(
                "Failed to fetch edgartools Form 4 for %s", ticker, exc_info=True,
            )
            return []


def _safe_int(val: object) -> int | None:
    """Safely convert to int, returning None on failure."""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        if math.isnan(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _safe_float(val: object) -> float | None:
    """Safely convert to float, returning None on failure."""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _safe_date(val: object) -> str:
    """Convert a date-like value to ISO date string."""
    if val is None:
        return ""
    try:
        import pandas as pd
        if isinstance(val, pd.Timestamp):
            return val.strftime("%Y-%m-%d")
    except Exception:
        pass
    s = str(val)
    return "" if s == "nan" or s == "NaT" else s


def _classify_transaction(text: str) -> str:
    """Classify a transaction description as Purchase or Sale."""
    lower = text.lower()
    if "purchase" in lower or "buy" in lower or "acquisition" in lower:
        return "Purchase"
    if "sale" in lower or "sell" in lower or "disposition" in lower:
        return "Sale"
    return text
