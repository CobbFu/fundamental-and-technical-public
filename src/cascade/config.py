"""Cascade definition loader — reads YAML config into typed dataclasses.

Cascade definitions live in `.valuation/cascades.yaml` (user-provided).
The file is optional; a missing or empty file yields an empty config.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CASCADES_PATH = Path(".valuation/cascades.yaml")


@dataclass
class TierDef:
    name: str
    tickers: list[str]


@dataclass
class CascadeDef:
    name: str
    demand_driver: str
    tiers: list[TierDef]


@dataclass
class CascadeConfig:
    version: int
    cascades: list[CascadeDef]


def load_cascades(path: Path | None = None) -> CascadeConfig:
    """Load cascade definitions from YAML.

    The cascade map is optional (for some scans it is only a labeling
    overlay), so a missing or empty file yields an empty config rather
    than raising.
    """
    if path is None:
        path = DEFAULT_CASCADES_PATH
    try:
        data = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        data = None
    if not data:
        return CascadeConfig(version=1, cascades=[])
    cascades = []
    for c in data.get("cascades", []):
        tiers = [
            TierDef(name=t["name"], tickers=t["tickers"])
            for t in c.get("tiers", [])
        ]
        cascades.append(CascadeDef(
            name=c["name"],
            demand_driver=c["demand_driver"],
            tiers=tiers,
        ))
    return CascadeConfig(version=data.get("version", 1), cascades=cascades)


def all_tickers(config: CascadeConfig) -> list[str]:
    """Return deduplicated list of all tickers across all cascades."""
    seen: set[str] = set()
    result: list[str] = []
    for cascade in config.cascades:
        for tier in cascade.tiers:
            for ticker in tier.tickers:
                if ticker not in seen:
                    seen.add(ticker)
                    result.append(ticker)
    return result


def cross_cascade_map(config: CascadeConfig) -> dict[str, list[str]]:
    """Return ticker -> list of cascade names for stocks in 2+ cascades."""
    ticker_cascades: dict[str, set[str]] = {}
    for cascade in config.cascades:
        for tier in cascade.tiers:
            for ticker in tier.tickers:
                ticker_cascades.setdefault(ticker, set()).add(cascade.name)
    return {
        ticker: sorted(names)
        for ticker, names in ticker_cascades.items()
        if len(names) >= 2
    }
