"""Scout agent — fetches data from all sources (Damodaran, FMP, EDGAR, yfinance, FRED)."""

from src.scout.company import CompanyFetcher
from src.scout.damodaran import DamodaranFetcher
from src.scout.holdings import HoldingsFetcher
from src.scout.market import MarketFetcher
from src.scout.segments import SegmentFetcher

__all__ = [
    "DamodaranFetcher",
    "CompanyFetcher",
    "HoldingsFetcher",
    "MarketFetcher",
    "SegmentFetcher",
]
