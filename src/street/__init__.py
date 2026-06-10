"""Street-target intelligence — analyst consensus + revision dynamics.

Pulls per-firm analyst actions and consensus targets from yfinance, then
computes the four diagnostics the morning digest cares about:

- central anchor (10% trimmed mean if N>=12 fresh analysts, else median)
- dispersion (high-low spread vs median)
- rerating velocity (count + magnitude of >=10% target moves in last 30d)
- stale mass (% of covering analysts who haven't refreshed in 120d)

The composite verdict suppresses the static price-vs-central read when a
rerating wave is in progress — the SNDK / NVDA-2023 archetype this project
exists to catch.
"""

from src.street.analyzer import StreetRead, analyze
from src.street.formatter import detail_card, digest_card, render_street_markdown

__all__ = [
    "StreetRead",
    "analyze",
    "detail_card",
    "digest_card",
    "render_street_markdown",
]
