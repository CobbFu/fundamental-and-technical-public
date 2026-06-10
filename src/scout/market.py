"""Wrapper around yfinance (market prices) and fredapi (macro data from FRED)."""

import logging
from datetime import datetime, timedelta, timezone

import yfinance as yf
from fredapi import Fred

from src.common.types import MacroContext, MacroData, MacroSignal, SourceTag, TaggedValue

logger = logging.getLogger(__name__)

# OECD long-term government bond series on FRED, keyed by currency
_OECD_SERIES: dict[str, str] = {
    "SEK": "IRLTLT01SEM156N",
    "EUR": "IRLTLT01EZM156N",
    "GBP": "IRLTLT01GBM156N",
    "JPY": "IRLTLT01JPM156N",
    "CAD": "IRLTLT01CAM156N",
    "AUD": "IRLTLT01AUM156N",
    "CHF": "IRLTLT01CHM156N",
    "NOK": "IRLTLT01NOM156N",
    "DKK": "IRLTLT01DKM156N",
}

# FRED series IDs
SERIES_10Y_TREASURY = "GS10"  # 10-Year Treasury Constant Maturity Rate
SERIES_GDP = "GDP"  # Gross Domestic Product
SERIES_CPI = "CPIAUCSL"  # Consumer Price Index for All Urban Consumers
SERIES_YIELD_CURVE = "T10Y2Y"  # 10Y-2Y spread
SERIES_CREDIT_SPREAD = "BAMLC0A4CBBB"  # BBB OAS spread
SERIES_VIX = "VIXCLS"  # VIX close

# All series with human-readable labels for macro context
_MACRO_SERIES = [
    (SERIES_10Y_TREASURY, "10Y Treasury Yield"),
    (SERIES_YIELD_CURVE, "10Y-2Y Yield Curve Spread"),
    (SERIES_CREDIT_SPREAD, "BBB Credit Spread (OAS)"),
    (SERIES_VIX, "VIX (Volatility Index)"),
    (SERIES_GDP, "Nominal GDP"),
    (SERIES_CPI, "CPI (All Urban Consumers)"),
]


class MarketFetcher:
    """Fetches market prices (yfinance) and macro data (FRED)."""

    def __init__(self, fred_api_key: str) -> None:
        self._fred = Fred(api_key=fred_api_key)

    def _yf_tag(self) -> SourceTag:
        return SourceTag(
            source="yfinance",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            fiscal_period="latest",
        )

    def _fred_tag(self, series_id: str) -> SourceTag:
        return SourceTag(
            source=f"FRED:{series_id}",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            fiscal_period="latest",
        )

    # ------------------------------------------------------------------
    # FX cross-rate helper
    # ------------------------------------------------------------------

    def _get_cross_rate(
        self, from_currency: str, to_currency: str,
    ) -> float | None:
        """Get FX rate to convert *from_currency* → *to_currency*.

        Returns the multiplier: value_in_from * rate = value_in_to.
        Returns None on failure.
        """
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        if from_currency == to_currency:
            return 1.0
        # Try direct pair first (e.g., USDEUR=X)
        try:
            pair = f"{from_currency}{to_currency}=X"
            info = yf.Ticker(pair).info or {}
            rate = info.get("regularMarketPrice") or info.get("previousClose")
            if rate is not None and float(rate) > 0:
                return float(rate)
        except Exception:
            pass
        # Try inverse pair (e.g., EURUSD=X → invert)
        try:
            pair = f"{to_currency}{from_currency}=X"
            info = yf.Ticker(pair).info or {}
            rate = info.get("regularMarketPrice") or info.get("previousClose")
            if rate is not None and float(rate) > 0:
                return 1.0 / float(rate)
        except Exception:
            pass
        logger.warning(
            "Could not fetch cross-rate %s→%s", from_currency, to_currency,
        )
        return None

    # ------------------------------------------------------------------
    # Price & market cap (currency-aware)
    # ------------------------------------------------------------------

    def fetch_stock_price(
        self, ticker: str, reporting_currency: str | None = None,
    ) -> TaggedValue:
        """Fetch current stock price via yfinance.

        If *reporting_currency* is provided and differs from the quote
        currency on the exchange, the price is converted so it is always
        expressed in the reporting (financial-statement) currency.
        """
        info = yf.Ticker(ticker).info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        quote_ccy = str(info.get("currency", "USD")).upper()

        note = f"Quote currency: {quote_ccy}"
        if (
            price is not None
            and reporting_currency
            and quote_ccy != reporting_currency.upper()
        ):
            fx = self._get_cross_rate(quote_ccy, reporting_currency.upper())
            if fx is not None:
                price = float(price) * fx
                note = (
                    f"Converted {quote_ccy}→{reporting_currency.upper()} "
                    f"(rate {fx:.6f})"
                )
            else:
                note = (
                    f"WARNING: price in {quote_ccy}, could not convert "
                    f"to {reporting_currency.upper()}"
                )

        return TaggedValue(
            value=float(price) if price else None,
            tag=self._yf_tag(),
            note=note,
        )

    def fetch_market_cap(
        self, ticker: str, reporting_currency: str | None = None,
    ) -> TaggedValue:
        """Fetch market cap via yfinance.

        Returns market cap in USD (quote currency). The reporting_currency parameter
        is kept for API compatibility but market cap is always returned in USD
        for valuation purposes.
        """
        info = yf.Ticker(ticker).info
        mcap = info.get("marketCap")
        quote_ccy = str(info.get("currency", "USD")).upper()

        # Always return market cap in USD (quote currency)
        # Don't convert to reporting currency - DCF needs USD
        note = f"Quote currency: {quote_ccy}"
        
        return TaggedValue(
            value=float(mcap) if mcap else None,
            tag=self._yf_tag(),
            note=note,
        )

    def fetch_risk_free_rate(self, currency: str = "USD") -> TaggedValue:
        """Fetch risk-free rate from FRED, currency-aware.

        For USD, uses GS10 (10-Year Treasury). For other currencies, uses the
        OECD long-term government bond series. Falls back to GS10 on failure.
        """
        currency = currency.upper()
        series_id = _OECD_SERIES.get(currency, SERIES_10Y_TREASURY)
        try:
            series = self._fred.get_series(series_id)
            latest = series.dropna().iloc[-1]
            note = (
                f"{currency} 10-Year government bond rate as decimal"
                if currency != "USD"
                else "10-Year Treasury rate as decimal"
            )
            return TaggedValue(
                value=float(latest) / 100,
                tag=self._fred_tag(series_id),
                note=note,
            )
        except Exception:
            if series_id != SERIES_10Y_TREASURY:
                logger.warning(
                    "Failed to fetch %s risk-free rate (series %s), falling back to US 10Y",
                    currency, series_id,
                )
                series = self._fred.get_series(SERIES_10Y_TREASURY)
                latest = series.dropna().iloc[-1]
                return TaggedValue(
                    value=float(latest) / 100,
                    tag=self._fred_tag(SERIES_10Y_TREASURY),
                    note=f"US 10Y fallback (no {currency} series available)",
                )
            raise

    def fetch_gdp_growth(self) -> TaggedValue:
        """Fetch latest GDP growth rate from FRED."""
        series = self._fred.get_series(SERIES_GDP)
        recent = series.dropna().tail(2)
        if len(recent) >= 2:
            growth = (recent.iloc[-1] - recent.iloc[-2]) / recent.iloc[-2]
            return TaggedValue(
                value=float(growth),
                tag=self._fred_tag(SERIES_GDP),
                note="Quarter-over-quarter GDP growth",
            )
        return TaggedValue(value=None, tag=self._fred_tag(SERIES_GDP), note="Insufficient data")

    def fetch_inflation(self) -> TaggedValue:
        """Fetch latest CPI-based inflation rate from FRED."""
        series = self._fred.get_series(SERIES_CPI)
        recent = series.dropna().tail(13)  # 13 months for YoY
        if len(recent) >= 13:
            inflation = (recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0]
            return TaggedValue(
                value=float(inflation),
                tag=self._fred_tag(SERIES_CPI),
                note="Year-over-year CPI inflation",
            )
        return TaggedValue(
            value=None, tag=self._fred_tag(SERIES_CPI), note="Insufficient data"
        )

    def _compute_percentile(
        self, series_id: str, label: str, lookback_years: int = 10,
    ) -> MacroSignal | None:
        """Fetch series, compute current value and percentile rank over lookback period."""
        try:
            start = (
                datetime.now(timezone.utc) - timedelta(days=365 * lookback_years)
            ).strftime("%Y-%m-%d")
            series = self._fred.get_series(series_id, observation_start=start)
            values = series.dropna()
            if len(values) < 2:
                return None
            current = float(values.iloc[-1])
            percentile = float(sum(1 for v in values if v < current) / len(values) * 100)
            return MacroSignal(
                series_id=series_id,
                label=label,
                current_value=current,
                percentile_10y=round(percentile, 1),
                tag=self._fred_tag(series_id),
            )
        except Exception as e:
            logger.warning("Failed to compute percentile for %s: %s", series_id, e)
            return None

    def fetch_macro_context(self, lookback_years: int = 10) -> MacroContext:
        """Fetch all macro signals with percentile context for scenario generation."""
        signals: list[MacroSignal] = []
        for series_id, label in _MACRO_SERIES:
            signal = self._compute_percentile(series_id, label, lookback_years)
            if signal is not None:
                signals.append(signal)
        return MacroContext(
            signals=signals,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
        )

    def fetch_fx_rate(self, currency: str) -> TaggedValue:
        """Fetch FX rate to convert *currency* → USD.

        Returns a TaggedValue whose value is the multiplier: local * rate = USD.
        USD returns 1.0 immediately. Falls back to 1.0 with a warning on failure.
        """
        currency = currency.upper()
        if currency == "USD":
            return TaggedValue(
                value=1.0,
                tag=self._yf_tag(),
                note="USD — no conversion needed",
            )
        try:
            pair = f"{currency}USD=X"
            info = yf.Ticker(pair).info or {}
            rate = info.get("regularMarketPrice") or info.get("previousClose")
            if rate is not None:
                return TaggedValue(
                    value=float(rate),
                    tag=self._yf_tag(),
                    note=f"{currency}/USD exchange rate",
                )
        except Exception:
            logger.warning("yfinance FX lookup failed for %s", currency)

        logger.warning("Could not fetch FX rate for %s — defaulting to 1.0", currency)
        return TaggedValue(
            value=1.0,
            tag=self._yf_tag(),
            note=f"FX rate unavailable for {currency} — fallback 1.0",
        )

    def fetch_macro_data(self, currency: str = "USD") -> MacroData:
        """Fetch core macro data points (risk-free rate, GDP, inflation, FX rate).

        Note: Does NOT populate macro_context (extended signals for scenarios).
        Call fetch_macro_context() separately when scenario generation is needed
        — this avoids 6 extra FRED API calls on every pipeline run.
        """
        risk_free: TaggedValue | None = None
        gdp: TaggedValue | None = None
        inflation: TaggedValue | None = None
        fx_rate: TaggedValue | None = None

        try:
            risk_free = self.fetch_risk_free_rate(currency=currency)
        except Exception:
            logger.warning("Failed to fetch risk-free rate from FRED")

        try:
            gdp = self.fetch_gdp_growth()
        except Exception:
            logger.warning("Failed to fetch GDP growth from FRED")

        try:
            inflation = self.fetch_inflation()
        except Exception:
            logger.warning("Failed to fetch inflation from FRED")

        try:
            fx_rate = self.fetch_fx_rate(currency)
        except Exception:
            logger.warning("Failed to fetch FX rate for %s", currency)

        return MacroData(
            risk_free_rate=risk_free,
            gdp_growth_rate=gdp,
            inflation_rate=inflation,
            fx_rate_to_usd=fx_rate,
        )
