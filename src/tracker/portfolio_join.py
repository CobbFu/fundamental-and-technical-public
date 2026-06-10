"""Aggregate portfolio.yaml positions into a per-ticker holding snapshot.

Source schema: `.valuation/portfolio.yaml` — each `position` has a
`holdings: [{account, shares, book_cost_local, book_cost_gbp, avg_fx_rate}]`
list. We sum across accounts and surface a single snapshot per ticker so
the digest can answer "am I in this and at what level".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class HoldingSnapshot:
    ticker: str
    total_shares: float = 0.0
    total_cost_local: float = 0.0  # 0.0 if all holdings are GBP-native (no book_cost_local)
    total_cost_gbp: float = 0.0
    currency: str = ""
    accounts: list[str] = field(default_factory=list)

    @property
    def avg_cost_local(self) -> float | None:
        if self.total_shares == 0 or self.total_cost_local == 0:
            return None
        return self.total_cost_local / self.total_shares

    @property
    def avg_cost_gbp(self) -> float | None:
        if self.total_shares == 0:
            return None
        return self.total_cost_gbp / self.total_shares


def load_portfolio_holdings(path: Path) -> dict[str, HoldingSnapshot]:
    """Return ticker -> aggregated snapshot. Tickers with zero shares are omitted."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text()) or {}
    positions: list[dict[str, Any]] = raw.get("positions") or []
    pools: dict[str, HoldingSnapshot] = {}
    for pos in positions:
        ticker = str(pos["ticker"])
        currency = str(pos.get("currency", ""))
        snap = pools.setdefault(ticker, HoldingSnapshot(ticker=ticker, currency=currency))
        for h in pos.get("holdings") or []:
            snap.total_shares += float(h.get("shares") or 0)
            snap.total_cost_local += float(h.get("book_cost_local") or 0)
            snap.total_cost_gbp += float(h.get("book_cost_gbp") or 0)
            acc = h.get("account")
            if acc and acc not in snap.accounts:
                snap.accounts.append(str(acc))
    return {t: s for t, s in pools.items() if s.total_shares > 0}
