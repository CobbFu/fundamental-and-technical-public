"""CLI for `python -m src street-read <TICKER> [--format=digest|detail|json]`."""

import argparse
import json
import sys

from src.street.analyzer import analyze
from src.street.formatter import detail_card, digest_card


def cmd_street_read(args: argparse.Namespace) -> None:
    """Single-ticker street-target read.

    Default output is the JSON payload (for downstream tools); use --format
    to emit the digest card or the full detail card instead.
    """
    result = analyze(args.ticker.upper())
    fmt = args.format

    if fmt == "json":
        json.dump(result.to_dict(), sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    elif fmt == "digest":
        print(digest_card(result))
    elif fmt == "detail":
        print(detail_card(result))
    else:  # pragma: no cover — argparse choices guards this
        raise SystemExit(f"unknown format: {fmt}")
