#!/usr/bin/env python3
"""Fetch portfolio prices + FX rates via yfinance. Outputs JSON to stdout.

Reads holdings from .valuation/portfolio.yaml (v2 multi-account format).
All prices converted to GBP for portfolio-level analysis.

Usage:
    python scripts/portfolio_prices.py                  # JSON output
    python scripts/portfolio_prices.py --format table   # Markdown table
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml
import yfinance as yf

PORTFOLIO_PATH = Path(".valuation/portfolio.yaml")

# yfinance returns GBp (pence) for individual UK stocks (not ETFs)
GBP_PENCE_TICKERS = {"AZN.L"}


def load_portfolio(path: Path = PORTFOLIO_PATH) -> dict:
    """Load portfolio YAML file."""
    with open(path) as f:
        return yaml.safe_load(f)


def _latest_close(data: pd.DataFrame, ticker: str, is_multi: bool) -> float:
    """Extract the latest closing price for a ticker from yfinance data."""
    series = data["Close"][ticker] if is_multi else data["Close"]
    return float(series.dropna().iloc[-1])


def _aggregate_holdings(position: dict) -> tuple[int, float]:
    """Sum shares and book_cost_gbp across all accounts for a position."""
    total_shares = 0
    total_cost_gbp = 0.0
    for h in position.get("holdings", []):
        total_shares += h.get("shares", 0)
        total_cost_gbp += h.get("book_cost_gbp", 0)
    return total_shares, total_cost_gbp


def fetch_prices(portfolio: dict) -> dict:
    """Fetch all stock prices, FX rates, and benchmark in one batch call."""
    positions = portfolio["positions"]
    fx_pairs = portfolio.get("fx_pairs", {})
    benchmark = portfolio.get("benchmark", "URTH")

    yf_tickers = [p["yf_ticker"] for p in positions]
    fx_tickers = list(fx_pairs.values())
    all_tickers = yf_tickers + fx_tickers + [benchmark]

    data = yf.download(all_tickers, period="5d", progress=False)
    is_multi = isinstance(data.columns, pd.MultiIndex)

    prices = {}
    for pos in positions:
        ticker = pos["ticker"]
        yf_tick = pos["yf_ticker"]
        total_shares, book_cost_gbp = _aggregate_holdings(pos)
        try:
            price = _latest_close(data, yf_tick, is_multi)

            # London-listed ETFs and stocks trade in GBp (pence)
            if yf_tick in GBP_PENCE_TICKERS:
                price = price / 100.0

            prices[ticker] = {
                "price": round(price, 2),
                "currency": pos["currency"],
                "yf_ticker": yf_tick,
                "company": pos["company"],
                "shares": total_shares,
                "book_cost_gbp": book_cost_gbp,
                "thesis_status": pos.get("thesis_status", "active"),
                "holdings": pos.get("holdings", []),
            }
        except Exception as e:
            prices[ticker] = {
                "error": str(e),
                "currency": pos["currency"],
                "yf_ticker": yf_tick,
                "company": pos["company"],
            }

    fx_rates: dict[str, float | str] = {"GBP": 1.0}
    for curr, yf_tick in fx_pairs.items():
        try:
            fx_rates[curr] = round(_latest_close(data, yf_tick, is_multi), 6)
        except Exception as e:
            fx_rates[curr] = f"ERROR: {e}"

    result = {"prices": prices, "fx_rates": fx_rates, "benchmark": benchmark}

    try:
        result["benchmark_price"] = round(
            _latest_close(data, benchmark, is_multi), 2,
        )
    except Exception:
        result["benchmark_price"] = None

    return result


def compute_portfolio(result: dict) -> dict:
    """Compute GBP values, weights, and returns for each position."""
    prices = result["prices"]
    fx_rates = result["fx_rates"]

    holdings = []
    total_value_gbp = 0.0

    for ticker, info in prices.items():
        if "error" in info:
            holdings.append({"ticker": ticker, "error": info["error"]})
            continue

        price = info["price"]
        shares = info["shares"]
        currency = info["currency"]
        book_cost_gbp = info["book_cost_gbp"]
        yf_tick = info["yf_ticker"]

        # Determine FX rate: use the currency field from portfolio.yaml
        # yfinance prices are in the exchange's native currency; the currency
        # field tells us what that is so we can convert to GBP.
        if currency == "GBP":
            # GBP-denominated — check if it's a CDI (US ticker, no suffix)
            if not any(yf_tick.endswith(s) for s in (".L", ".ST", ".OL", ".SW")):
                # CDI — yfinance returns USD price, convert to GBP
                fx = fx_rates.get("USD", 1.0) if isinstance(fx_rates.get("USD"), (int, float)) else 1.0
            else:
                fx = 1.0
        elif isinstance(fx_rates.get(currency), (int, float)):
            fx = fx_rates[currency]
        else:
            holdings.append({"ticker": ticker, "error": f"Missing FX rate for {currency}"})
            continue

        value_local = shares * price
        value_gbp = value_local * fx
        return_pct = ((value_gbp - book_cost_gbp) / book_cost_gbp * 100) if book_cost_gbp else 0

        total_value_gbp += value_gbp

        # Per-account breakdown
        account_detail = []
        for h in info.get("holdings", []):
            acct_shares = h.get("shares", 0)
            acct_value = acct_shares * price * fx
            account_detail.append({
                "account": h["account"],
                "shares": acct_shares,
                "value_gbp": round(acct_value, 2),
            })

        holdings.append({
            "ticker": ticker,
            "company": info["company"],
            "price": price,
            "currency": currency,
            "shares": shares,
            "value_gbp": round(value_gbp, 2),
            "book_cost_gbp": round(book_cost_gbp, 2),
            "return_pct": round(return_pct, 1),
            "thesis_status": info.get("thesis_status", "active"),
            "accounts": account_detail,
        })

    # Compute weights
    for h in holdings:
        if "error" not in h:
            weight = h["value_gbp"] / total_value_gbp * 100 if total_value_gbp else 0
            h["weight_pct"] = round(weight, 1)

    result["holdings"] = sorted(holdings, key=lambda h: h.get("weight_pct", 0), reverse=True)
    result["total_value_gbp"] = round(total_value_gbp, 2)

    # Account-level totals
    account_totals: dict[str, float] = {}
    for h in result["holdings"]:
        for a in h.get("accounts", []):
            account_totals[a["account"]] = account_totals.get(a["account"], 0) + a["value_gbp"]
    result["account_totals_gbp"] = {k: round(v, 2) for k, v in account_totals.items()}

    return result


def format_table(result: dict, rules: dict | None = None) -> str:
    """Format portfolio as a markdown table for Telegram delivery."""
    hard_ceiling = rules.get("hard_ceiling_pct", 15.0) if rules else 15.0
    trim_warning = rules.get("trim_warning_pct", 12.0) if rules else 12.0

    lines = []
    lines.append(f"**Portfolio** — £{result['total_value_gbp']:,.0f} GBP")

    # Account breakdown
    for acct, total in result.get("account_totals_gbp", {}).items():
        lines.append(f"  {acct}: £{total:,.0f}")

    lines.append("")
    lines.append("| Ticker | Company | Shares | Weight | Return | Status |")
    lines.append("|--------|---------|--------|--------|--------|--------|")

    for h in result.get("holdings", []):
        if "error" in h:
            lines.append(f"| {h['ticker']} | — | — | — | ERROR | — |")
            continue

        status = h.get("thesis_status", "active")
        flag = ""
        if h.get("weight_pct", 0) > hard_ceiling:
            flag = " ALARM"
        elif h.get("weight_pct", 0) > trim_warning:
            flag = " WARN"

        lines.append(
            f"| {h['ticker']} | {h['company']} | {h['shares']} | "
            f"{h.get('weight_pct', 0):.1f}%{flag} | "
            f"{h['return_pct']:+.1f}% | {status} |"
        )

    # FX rates
    lines.append("")
    lines.append("**FX:** " + ", ".join(
        f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}"
        for k, v in result.get("fx_rates", {}).items()
        if k != "GBP"
    ))

    if result.get("benchmark_price"):
        lines.append(f"**Benchmark:** {result['benchmark']} = {result['benchmark_price']:.2f}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch portfolio prices + FX rates")
    parser.add_argument(
        "--format", choices=["json", "table"], default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--portfolio", type=Path, default=PORTFOLIO_PATH,
        help="Path to portfolio YAML file",
    )
    args = parser.parse_args()

    portfolio = load_portfolio(args.portfolio)
    result = fetch_prices(portfolio)
    result = compute_portfolio(result)

    if args.format == "table":
        print(format_table(result, rules=portfolio.get("position_rules")))
    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
