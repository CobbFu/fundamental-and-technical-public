"""Wrapper around FinanceToolkit (FMP) and edgartools (SEC EDGAR) for company financials."""

import logging
from datetime import datetime, timezone

import pandas as pd
import requests
from financetoolkit import Toolkit

from src.common.types import (
    CompanyData,
    ConsensusData,
    EarningsSurprise,
    PeerData,
    SourceTag,
    TaggedValue,
)

logger = logging.getLogger(__name__)


def _safe_float(val: object) -> float | None:
    """Convert a value to float, returning None for NaN/None/invalid."""
    if val is None:
        return None
    try:
        if pd.isna(val):  # type: ignore[call-overload]
            return None
    except (TypeError, ValueError):
        pass
    try:
        result = float(val)  # type: ignore[arg-type]
        return result
    except (TypeError, ValueError):
        return None


class CompanyFetcher:
    """Fetches company financials. Primary: FMP via FinanceToolkit. Fallback: SEC via edgartools."""

    def __init__(self, api_key: str, user_agent: str) -> None:
        self._api_key = api_key
        self._user_agent = user_agent

    def fetch_financials(self, ticker: str) -> CompanyData:
        """Fetch company financials, trying FMP first, falling back to EDGAR."""
        try:
            return self._fetch_via_fmp(ticker)
        except Exception:
            logger.warning("FMP fetch failed for %s, falling back to EDGAR", ticker)
            return self._fetch_via_edgar(ticker)

    def _fetch_via_fmp(self, ticker: str) -> CompanyData:
        tag = SourceTag(
            source="FMP",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            fiscal_period="TTM",
        )

        toolkit = Toolkit(
            tickers=[ticker],
            api_key=self._api_key,
            start_date="2019-01-01",
        )

        income_stmt: pd.DataFrame | None = None
        balance_sheet: pd.DataFrame | None = None
        cash_flow: pd.DataFrame | None = None
        key_metrics: dict[str, TaggedValue] = {}

        try:
            income_stmt = toolkit.get_income_statement()
            logger.info("Fetched income statement for %s via FMP", ticker)
        except Exception:
            logger.warning("Failed to fetch income statement for %s", ticker)

        try:
            balance_sheet = toolkit.get_balance_sheet_statement()
            logger.info("Fetched balance sheet for %s via FMP", ticker)
        except Exception:
            logger.warning("Failed to fetch balance sheet for %s", ticker)

        try:
            cash_flow = toolkit.get_cash_flow_statement()
            logger.info("Fetched cash flow for %s via FMP", ticker)
        except Exception:
            logger.warning("Failed to fetch cash flow for %s", ticker)

        # Compute EPS from Net Income / Shares when FMP returns zeros
        # (some FMP plans don't include per-share data)
        if income_stmt is not None:
            self._fix_eps(income_stmt)

        # Extract key metrics from income statement
        if income_stmt is not None:
            latest_col = income_stmt.columns[-1] if len(income_stmt.columns) > 0 else None
            if latest_col is not None:
                for metric in ["Research and Development Expenses", "Revenue"]:
                    if metric in income_stmt.index:
                        raw_val = income_stmt.loc[metric, latest_col]
                        if pd.notna(raw_val):
                            key_metrics[metric] = TaggedValue(
                                value=float(raw_val),  # type: ignore[arg-type]
                                tag=tag,
                            )

        # Determine company name and industry from the toolkit profile
        name = ticker
        industry = "Unknown"
        try:
            profile = toolkit.get_profile()
            if isinstance(profile, pd.DataFrame) and not profile.empty:
                if "Company Name" in profile.index:
                    name = str(profile.loc["Company Name"].iloc[0])
                if "Industry" in profile.index:
                    industry = str(profile.loc["Industry"].iloc[0])
        except Exception:
            logger.warning("Failed to fetch profile for %s", ticker)

        # yfinance for company name, industry, reporting currency, and observed beta
        reporting_currency = "USD"
        observed_beta: float | None = None
        try:
            import yfinance as yf
            yf_info = yf.Ticker(ticker).info or {}
            if name == ticker:
                name = str(yf_info.get("longName", yf_info.get("shortName", ticker)))
            if industry == "Unknown":
                yf_industry = yf_info.get("industry", "")
                if yf_industry:
                    industry = yf_industry
                    logger.info("Industry from yfinance: %s", industry)
            reporting_currency = str(
                yf_info.get("financialCurrency", "USD") or "USD"
            ).upper()
            logger.info("Reporting currency for %s: %s", ticker, reporting_currency)
            raw_beta = yf_info.get("beta")
            observed_beta = float(raw_beta) if raw_beta is not None else None
            if observed_beta is not None:
                logger.info("Observed beta for %s: %.2f", ticker, observed_beta)
        except Exception:
            logger.warning("yfinance profile fallback failed for %s", ticker)

        consensus = self._fetch_consensus(ticker)

        return CompanyData(
            ticker=ticker,
            name=name,
            industry=industry,
            income_statement=income_stmt,
            balance_sheet=balance_sheet,
            cash_flow=cash_flow,
            key_metrics=key_metrics,
            consensus=consensus,
            observed_beta=observed_beta,
            reporting_currency=reporting_currency,
        )

    @staticmethod
    def _fix_eps(income_stmt: pd.DataFrame) -> None:
        """Compute EPS Diluted from Net Income / Shares if FMP returned zeros."""
        if (
            "EPS Diluted" not in income_stmt.index
            or "Net Income" not in income_stmt.index
            or "Weighted Average Shares Diluted" not in income_stmt.index
        ):
            return
        eps_row = income_stmt.loc["EPS Diluted"]
        if isinstance(eps_row, pd.DataFrame):
            eps_row = eps_row.iloc[0]
        # Only fix if ALL values are zero (not just some)
        if not (eps_row == 0).all():
            return
        net_income = income_stmt.loc["Net Income"]
        shares = income_stmt.loc["Weighted Average Shares Diluted"]
        if isinstance(net_income, pd.DataFrame):
            net_income = net_income.iloc[0]
        if isinstance(shares, pd.DataFrame):
            shares = shares.iloc[0]
        for col in income_stmt.columns:
            ni = net_income.get(col)
            sh = shares.get(col)
            if pd.notna(ni) and pd.notna(sh) and float(sh) != 0:
                income_stmt.at["EPS Diluted", col] = float(ni) / float(sh)
        logger.info("Computed EPS Diluted from Net Income / Shares (FMP returned zeros)")

    def _fetch_consensus(self, ticker: str) -> ConsensusData | None:
        """Fetch analyst consensus data from yfinance. Returns None on failure."""
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)

            # Price targets
            pt = t.analyst_price_targets or {}
            target_mean = pt.get("mean") if isinstance(pt, dict) else None
            target_median = pt.get("median") if isinstance(pt, dict) else None
            target_high = pt.get("high") if isinstance(pt, dict) else None
            target_low = pt.get("low") if isinstance(pt, dict) else None
            current_price = pt.get("current") if isinstance(pt, dict) else None

            # Recommendations (current month)
            recs = t.recommendations
            strong_buy = buy = hold = sell = strong_sell = 0
            if recs is not None and not recs.empty:
                row = recs.iloc[0]  # current month
                strong_buy = int(row.get("strongBuy", 0))
                buy = int(row.get("buy", 0))
                hold = int(row.get("hold", 0))
                sell = int(row.get("sell", 0))
                strong_sell = int(row.get("strongSell", 0))

            # Earnings estimates
            ee = t.earnings_estimate
            eps_cy = eps_ny = None
            if ee is not None and not ee.empty:
                if "0y" in ee.index:
                    eps_cy = _safe_float(ee.loc["0y", "avg"])
                if "+1y" in ee.index:
                    eps_ny = _safe_float(ee.loc["+1y", "avg"])

            # Revenue estimates
            rev_est = t.revenue_estimate
            rev_cy = rev_ny = rev_g_cy = rev_g_ny = None
            if rev_est is not None and not rev_est.empty:
                if "0y" in rev_est.index:
                    rev_cy = _safe_float(rev_est.loc["0y", "avg"])
                    rev_g_cy = _safe_float(rev_est.loc["0y", "growth"])
                if "+1y" in rev_est.index:
                    rev_ny = _safe_float(rev_est.loc["+1y", "avg"])
                    rev_g_ny = _safe_float(rev_est.loc["+1y", "growth"])

            # Earnings surprises (last 4 quarters)
            eh = t.earnings_history
            surprises: list[EarningsSurprise] = []
            if eh is not None and not eh.empty:
                for idx, row in eh.iterrows():
                    # Manual quarter calculation (Timestamp index doesn't support %q)
                    if hasattr(idx, "year") and hasattr(idx, "month"):
                        period_str = f"{idx.year}-Q{(idx.month - 1) // 3 + 1}"
                    else:
                        period_str = str(idx)
                    eps_actual = _safe_float(row.get("epsActual"))
                    eps_estimate = _safe_float(row.get("epsEstimate"))
                    if eps_actual is None or eps_estimate is None:
                        continue  # skip incomplete quarters
                    surprises.append(EarningsSurprise(
                        period=period_str,
                        eps_actual=eps_actual,
                        eps_estimate=eps_estimate,
                        surprise_pct=_safe_float(row.get("surprisePercent")) or 0.0,
                    ))

            return ConsensusData(
                target_mean=_safe_float(target_mean),
                target_median=_safe_float(target_median),
                target_high=_safe_float(target_high),
                target_low=_safe_float(target_low),
                current_price=_safe_float(current_price),
                strong_buy=strong_buy,
                buy=buy,
                hold=hold,
                sell=sell,
                strong_sell=strong_sell,
                eps_current_year=eps_cy,
                eps_next_year=eps_ny,
                revenue_current_year=rev_cy,
                revenue_next_year=rev_ny,
                revenue_growth_current_year=rev_g_cy,
                revenue_growth_next_year=rev_g_ny,
                earnings_surprises=surprises,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception:
            logger.warning("Failed to fetch consensus data for %s", ticker)
            return None

    def fetch_peers(self, ticker: str) -> list[PeerData]:
        """Fetch comparable companies from FMP. Returns empty list on failure."""
        try:
            return self._fetch_peers_fmp(ticker)
        except Exception:
            logger.warning("Peer fetch failed for %s, returning empty list", ticker)
            return []

    def _fetch_peers_fmp(self, ticker: str) -> list[PeerData]:
        """Fetch peer list from FMP stable API, then enrich with FinanceToolkit ratios."""
        resp = requests.get(
            "https://financialmodelingprep.com/stable/stock-peers",
            params={"symbol": ticker, "apikey": self._api_key},
            timeout=30,
        )
        resp.raise_for_status()
        peer_data = resp.json()

        # FMP returns a list with one dict containing peersList
        if not peer_data or not isinstance(peer_data, list):
            return []
        peer_symbols: list[str] = peer_data[0].get("peersList", [])
        if not peer_symbols:
            return []

        # Cap at 5 peers
        peer_symbols = peer_symbols[:5]

        # Build basic PeerData from peer list
        peers: list[PeerData] = [
            PeerData(ticker=sym, name=sym) for sym in peer_symbols
        ]

        # Enrich with FinanceToolkit ratios
        try:
            toolkit = Toolkit(
                tickers=peer_symbols,
                api_key=self._api_key,
                start_date="2024-01-01",
            )

            # Fetch valuation ratios
            val_ratios = None
            try:
                val_ratios = toolkit.ratios.get_valuation_ratios()
            except Exception:
                logger.warning("Failed to fetch valuation ratios for peers")

            # Fetch profitability ratios
            prof_ratios = None
            try:
                prof_ratios = toolkit.ratios.get_profitability_ratios()
            except Exception:
                logger.warning("Failed to fetch profitability ratios for peers")

            # Fetch income statements for revenue growth
            income_stmts = None
            try:
                income_stmts = toolkit.get_income_statement()
            except Exception:
                logger.warning("Failed to fetch income statements for peers")

            for peer in peers:
                sym = peer.ticker
                try:
                    if val_ratios is not None:
                        peer.pe_ratio = self._extract_latest_metric(
                            val_ratios, sym, "Price-to-Earnings (PE)"
                        )
                        peer.ev_ebitda = self._extract_latest_metric(
                            val_ratios, sym, "Enterprise Value over EBITDA"
                        )
                        peer.ev_revenue = self._extract_latest_metric(
                            val_ratios, sym, "Enterprise Value over Revenue"
                        )
                    if prof_ratios is not None:
                        peer.operating_margin = self._extract_latest_metric(
                            prof_ratios, sym, "Operating Margin"
                        )
                    if income_stmts is not None:
                        peer.revenue_growth = self._compute_revenue_growth(
                            income_stmts, sym
                        )
                except Exception:
                    logger.warning("Failed to enrich peer %s", sym)

        except Exception:
            logger.warning("FinanceToolkit multi-ticker failed, returning peers without metrics")

        return peers

    @staticmethod
    def _extract_latest_metric(
        df: pd.DataFrame, ticker: str, metric: str,
    ) -> float | None:
        """Extract the latest non-NaN value for a ticker/metric from a FinanceToolkit DataFrame."""
        try:
            if isinstance(df.columns, pd.MultiIndex):
                # Multi-ticker: columns are (ticker, year)
                if ticker in df.columns.get_level_values(0):
                    row = df[ticker]
                    if metric in row.index:
                        vals = row.loc[metric]
                        non_nan = vals.dropna()
                        if len(non_nan) > 0:
                            return _safe_float(non_nan.iloc[-1])
            elif isinstance(df.index, pd.MultiIndex):
                # Alternative structure: index is (ticker, metric)
                if ticker in df.index.get_level_values(0):
                    sub = df.loc[ticker]
                    if metric in sub.index:
                        vals = sub.loc[metric]
                        non_nan = vals.dropna()
                        if len(non_nan) > 0:
                            return _safe_float(non_nan.iloc[-1])
            else:
                # Single ticker fallback
                if metric in df.index:
                    vals = df.loc[metric].dropna()
                    if len(vals) > 0:
                        return _safe_float(vals.iloc[-1])
        except Exception:
            logger.debug("Failed to extract %s for %s", metric, ticker, exc_info=True)
        return None

    @staticmethod
    def _compute_revenue_growth(
        income_stmts: pd.DataFrame, ticker: str,
    ) -> float | None:
        """Compute YoY revenue growth from the latest two years."""
        try:
            if isinstance(income_stmts.columns, pd.MultiIndex):
                if ticker in income_stmts.columns.get_level_values(0):
                    sub = income_stmts[ticker]
                    if "Revenue" in sub.index:
                        revs = sub.loc["Revenue"].dropna()
                        if len(revs) >= 2:
                            prev, curr = float(revs.iloc[-2]), float(revs.iloc[-1])
                            if prev != 0:
                                return (curr - prev) / abs(prev)
            elif "Revenue" in income_stmts.index:
                revs = income_stmts.loc["Revenue"].dropna()
                if len(revs) >= 2:
                    prev, curr = float(revs.iloc[-2]), float(revs.iloc[-1])
                    if prev != 0:
                        return (curr - prev) / abs(prev)
        except Exception:
            logger.debug("Failed to compute revenue growth for %s", ticker, exc_info=True)
        return None

    def _fetch_via_edgar(self, ticker: str) -> CompanyData:
        import edgar

        edgar.set_identity(self._user_agent)

        tag = SourceTag(
            source="EDGAR",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            fiscal_period="latest 10-K",
        )

        company = edgar.Company(ticker)
        name = str(company)
        industry = "Unknown"

        # Get latest 10-K filing for financials
        income_stmt: pd.DataFrame | None = None
        try:
            filings = company.get_filings(form="10-K")
            if filings and len(filings) > 0:
                latest_10k = filings[0]
                financials = latest_10k.xbrl()
                if financials is not None:
                    # edgartools returns XBRL data; extract what we can
                    logger.info("Fetched 10-K XBRL for %s via EDGAR", ticker)
        except Exception:
            logger.warning("Failed to fetch EDGAR financials for %s", ticker)

        return CompanyData(
            ticker=ticker,
            name=name,
            industry=industry,
            income_statement=income_stmt,
            key_metrics={"_source_note": TaggedValue(value="EDGAR fallback", tag=tag)},
        )
