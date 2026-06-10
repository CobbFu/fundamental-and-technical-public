"""CLI entry point — scan commands only (trimmed from the Valuation CLI).

Usage:
    python -m src momentum-scan [--universe us|eu|all]
    python -m src fallen-angel-scan
    python -m src new-highs-check
    python -m src cascade-scan
    python -m src street-read <TICKER> [--format=digest|detail|json]
"""

import argparse
import json
import logging
import sys
from typing import NoReturn

from src.cascade.report import format_all_cascade_parts
from src.cascade.scanner import CascadeScanner
from src.early.report import format_early_report_parts, write_digest
from src.early.scanner import EarlyScanner
from src.momentum.report import (
    format_daily_signal,
    format_fallen_angel_report,
    format_momentum_report,
    format_momentum_report_parts,
)
from src.momentum.scanner import FallenAngelScanner, MomentumScanner
from src.street.cli import cmd_street_read
from src.tracker.cli import (
    DEFAULT_DIGESTS_DIR,
    DEFAULT_PORTFOLIO_PATH,
    DEFAULT_TRACKER_PATH,
    cmd_track_add,
    cmd_track_refresh,
    list_tracker,
)


def _json_out(data: dict) -> None:
    json.dump(data, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def _json_error(message: str) -> NoReturn:
    _json_out({"status": "error", "message": message})
    sys.exit(1)


def cmd_momentum_scan(args: argparse.Namespace) -> None:
    universes = ["us", "eu"] if args.universe == "all" else [args.universe]
    all_outputs: list[dict] = []

    for univ in universes:
        scanner = MomentumScanner()
        try:
            result = scanner.run_weekly_scan(universe=univ)
            report = format_momentum_report(result, universe=univ)
            report_parts = format_momentum_report_parts(result, universe=univ)
            all_entries = result.tier1 + result.tier2 + result.tier3
            all_outputs.append({
                "universe": univ,
                "status": "ok",
                "report": report,
                "report_parts": report_parts,
                "tier1_count": len(result.tier1),
                "tier2_count": len(result.tier2),
                "tier3_count": len(result.tier3),
                "universe_size": result.universe_size,
                "market_regime": result.market_regime,
                "promotions": [e.ticker for e in result.promotions],
                "new_entries": [e.ticker for e in result.new_entries],
                "drops": result.drops,
                "stage_breakdown": {
                    "EARLY": sum(1 for e in all_entries if e.stage == "EARLY"),
                    "MID": sum(1 for e in all_entries if e.stage == "MID"),
                    "LATE": sum(1 for e in all_entries if e.stage == "LATE"),
                },
            })
        except Exception as e:
            all_outputs.append({
                "universe": univ,
                "status": "error",
                "error": f"Momentum scan failed: {e}",
            })
        finally:
            scanner.close()

    if len(all_outputs) == 1:
        out = all_outputs[0]
        if out.get("status") == "error":
            _json_error(out["error"])
        _json_out(out)
    else:
        _json_out({"scans": all_outputs})


def cmd_fallen_angel_scan(args: argparse.Namespace) -> None:
    scanner = FallenAngelScanner()
    try:
        result = scanner.run_scan()
        report = format_fallen_angel_report(result)
        _json_out({
            "status": "ok",
            "report": report,
            "angel_count": len(result.angels),
            "candidates_scanned": result.candidates_scanned,
            "angels": [
                {"ticker": a.ticker, "drawdown_pct": a.drawdown_pct, "f_score": a.f_score}
                for a in result.angels
            ],
        })
    except Exception as e:
        _json_error(f"Fallen angel scan failed: {e}")
    finally:
        scanner.close()


def cmd_new_highs_check(args: argparse.Namespace) -> None:
    scanner = MomentumScanner()
    try:
        result = scanner.run_daily_new_highs()
        if result is None:
            _json_out({"status": "ok", "signal": None})
        else:
            _json_out({
                "status": "ok",
                "signal": format_daily_signal(result),
                "ticker": result.ticker,
                "new_high_count_20d": result.new_high_count_20d,
                "return_12m": result.return_12m,
                "on_radar": result.on_radar,
            })
    except Exception as e:
        _json_error(f"New highs check failed: {e}")
    finally:
        scanner.close()


def cmd_cascade_scan(args: argparse.Namespace) -> None:
    scanner = CascadeScanner()
    try:
        result = scanner.run_scan()
        parts = format_all_cascade_parts(result)
        _json_out({
            "status": "ok",
            "report_parts": parts,
            "cascade_count": len(result.cascades),
            "cross_cascade_count": len(result.cross_cascade),
            "date": result.date,
        })
    except Exception as e:
        _json_error(f"Cascade scan failed: {e}")
    finally:
        scanner.close()


def cmd_early_scan(args: argparse.Namespace) -> None:
    scanner = EarlyScanner()
    try:
        result = scanner.run_scan(persist=not args.dry_run)
        digest_path = None if args.dry_run else str(write_digest(result))
        _json_out({
            "status": "ok",
            "date": result.date,
            "universe_size": result.universe_size,
            "candidate_count": len(result.candidates),
            "cohort_count": len(result.cohorts),
            "confirmed_cohorts": sum(1 for c in result.cohorts if c.confirmed),
            "digest_path": digest_path,
            "report_parts": format_early_report_parts(result),
            "candidates": [
                {
                    "ticker": c.ticker, "name": c.name, "score": round(c.early_score, 1),
                    "stage": c.stage, "cohort": c.cohort, "market_cap_b": round(c.market_cap_b, 2),
                    "trailing_12m": c.trailing_12m, "why_now": c.why_now, "change": c.change,
                }
                for c in result.candidates
            ],
            "watchlist": [
                {
                    "ticker": c.ticker, "name": c.name, "verdict": c.verdict, "stage": c.stage,
                    "dist_from_high": c.dist_from_high, "trailing_12m": c.trailing_12m,
                    "market_cap_b": round(c.market_cap_b, 2),
                }
                for c in result.watchlist
            ],
            "dropped": result.dropped,
        })
    except Exception as e:
        _json_error(f"Early scan failed: {e}")
    finally:
        scanner.close()


def cmd_early_triggers(args: argparse.Namespace) -> None:
    scanner = EarlyScanner()
    try:
        result = scanner.run_daily_triggers()
        _json_out({
            "status": "ok",
            "date": result.date,
            "fired_count": len(result.fired),
            "fired": result.fired,
        })
    except Exception as e:
        _json_error(f"Early triggers failed: {e}")
    finally:
        scanner.close()


def main() -> None:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--verbose", "-v", action="store_true",
                        help="Enable DEBUG logging.")

    parser = argparse.ArgumentParser(
        prog="fund-tech",
        description="Fundamental & Technical — scan commands.",
    )
    subs = parser.add_subparsers(dest="command", required=True)

    mscan_p = subs.add_parser("momentum-scan", parents=[parent],
                              help="Weekly momentum radar scan")
    mscan_p.add_argument("--universe", "-u", choices=["us", "eu", "all"],
                         default="us",
                         help="Stock universe: us (Russell 1000), eu, all")
    mscan_p.set_defaults(func=cmd_momentum_scan)

    fa_p = subs.add_parser("fallen-angel-scan", parents=[parent],
                           help="Weekly fallen angel scan")
    fa_p.set_defaults(func=cmd_fallen_angel_scan)

    nh_p = subs.add_parser("new-highs-check", parents=[parent],
                           help="Daily new 52-week highs check")
    nh_p.set_defaults(func=cmd_new_highs_check)

    cscan_p = subs.add_parser("cascade-scan", parents=[parent],
                              help="Supply chain cascade scan")
    cscan_p.set_defaults(func=cmd_cascade_scan)

    escan_p = subs.add_parser("early-scan", parents=[parent],
                              help="Early-stage (pre-momentum) scan — find the next SanDisk")
    escan_p.add_argument("--dry-run", action="store_true",
                         help="Skip disk writes (no state, no digest); emit JSON only")
    escan_p.set_defaults(func=cmd_early_scan)

    etrig_p = subs.add_parser("early-triggers", parents=[parent],
                              help="Daily base-breakout watch on existing early candidates")
    etrig_p.add_argument("--dry-run", action="store_true", help="No-op flag for symmetry")
    etrig_p.set_defaults(func=cmd_early_triggers)

    add_p = subs.add_parser("track-add", parents=[parent],
                            help="Add or replace a tracker.yaml entry")
    add_p.add_argument("--tracker-path", default=str(DEFAULT_TRACKER_PATH))
    add_p.add_argument("--payload", help="Path to JSON payload file")
    add_p.add_argument("--payload-stdin", action="store_true",
                       help="Read payload JSON from stdin")
    add_p.add_argument("--replace", action="store_true",
                       help="Overwrite if ticker already exists")
    add_p.add_argument("--dry-run", action="store_true",
                       help="Skip disk writes; emit JSON only")
    add_p.set_defaults(func=cmd_track_add)

    refresh_p = subs.add_parser("track-refresh", parents=[parent],
                                help="Refresh one or all tracker entries with fresh reads")
    refresh_p.add_argument("--tracker-path", default=str(DEFAULT_TRACKER_PATH))
    refresh_p.add_argument("--portfolio-path", default=str(DEFAULT_PORTFOLIO_PATH))
    refresh_p.add_argument("--digests-dir", default=str(DEFAULT_DIGESTS_DIR))
    refresh_p.add_argument("--payload", help="Path to JSON payload file (list of reads)")
    refresh_p.add_argument("--payload-stdin", action="store_true",
                           help="Read payload JSON from stdin")
    refresh_p.add_argument("--dry-run", action="store_true",
                           help="Skip disk writes; emit JSON only")
    refresh_p.set_defaults(func=cmd_track_refresh)

    list_p = subs.add_parser("track-list", parents=[parent],
                             help="List tracker entries (used by /track-refresh skill)")
    list_p.add_argument("--tracker-path", default=str(DEFAULT_TRACKER_PATH))
    list_p.set_defaults(func=list_tracker)

    street_p = subs.add_parser("street-read", parents=[parent],
                               help="Pull analyst consensus + revision dynamics for a ticker")
    street_p.add_argument("ticker", help="Ticker symbol (e.g. MU, NVDA)")
    street_p.add_argument("--format", "-f",
                          choices=["digest", "detail", "json"],
                          default="json",
                          help="Output format (default: json for downstream tools)")
    street_p.set_defaults(func=cmd_street_read)

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    args.func(args)


if __name__ == "__main__":
    main()
