"""Tests for portfolio.yaml -> per-ticker holding aggregation."""

from pathlib import Path

from src.tracker.portfolio_join import load_portfolio_holdings

FIXTURE = Path(__file__).parent / "fixtures" / "portfolio_sample.yaml"


def test_aggregates_multi_account_position() -> None:
    holdings = load_portfolio_holdings(FIXTURE)
    inve = holdings["INVE-B"]
    assert inve.total_shares == 1000 + 500
    assert inve.total_cost_local == 300000.00 + 150000.00
    assert inve.total_cost_gbp == 22000 + 11000
    assert sorted(inve.accounts) == ["investment", "isa1"]
    assert inve.currency == "SEK"


def test_single_account_position() -> None:
    holdings = load_portfolio_holdings(FIXTURE)
    wdc = holdings["WDC"]
    assert wdc.total_shares == 10
    assert wdc.total_cost_local == 4500.00
    assert wdc.total_cost_gbp == 3375
    assert wdc.accounts == ["isa2"]
    assert wdc.avg_cost_local == 4500.00 / 10


def test_gbp_native_position_has_zero_local_cost() -> None:
    holdings = load_portfolio_holdings(FIXTURE)
    vuag = holdings["VUAG"]
    assert vuag.total_shares == 50
    assert vuag.total_cost_local == 0.0  # no book_cost_local in fixture
    assert vuag.total_cost_gbp == 5000
    assert vuag.avg_cost_local is None
    assert vuag.avg_cost_gbp == 5000 / 50


def test_zero_share_positions_omitted() -> None:
    holdings = load_portfolio_holdings(FIXTURE)
    assert "ZERO" not in holdings


def test_missing_file_returns_empty() -> None:
    holdings = load_portfolio_holdings(Path("/nonexistent/path/portfolio.yaml"))
    assert holdings == {}
