# Fundamental and Technical

Python tooling for US-equity trend research: momentum, supply-chain ("cascade"),
and early-stage scanners; a watch/hold tracker with a daily digest; and an
agent-navigable "wisdom wiki" of investing principles.

This repository is a **source-code showcase** — it ships the engine, tests, and
wiki framework only. No portfolio, watchlist, or personal data is included.

## Layout

| Path | What it is |
|------|------------|
| `src/momentum/` | Universe momentum screen (S&P 500 + 400) with tiering and change detection |
| `src/cascade/`  | Supply-chain breadth scan over a curated theme map |
| `src/early/`    | Pre-momentum base scan: surfaces names *before* the run |
| `src/tracker/`  | Watch/hold tracker (`tracker.yaml`) + portfolio join + daily digest renderer |
| `src/street/`   | Analyst price-target consensus and revision dynamics |
| `src/scout/`, `src/calculators/`, `src/comps/` | Fundamentals pulls, valuation helpers, comparables types |
| `src/common/`   | Shared types and a rolling-backup helper |
| `tests/`        | Test suite |
| `llm-wiki/`     | Agent-navigable investing-wisdom wiki — framework + synthesis (source texts not bundled) |
| `.claude/skills/` | Two Claude Code skills that drive the wiki: `wiki-ingest` and `ask-wiki` |

## Run

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env          # FMP_API_KEY / FRED_API_KEY / EDGAR_USER_AGENT (optional for the pure-technical scans)

uv run python -m src --help   # list commands
uv run python -m src momentum-scan
uv run python -m src cascade-scan
uv run python -m src early-scan

uv run pytest                 # run the tests
```

The CLI reads and writes local state under a `.valuation/` directory created on
first use; that directory is gitignored, so your own data never lands in git.

## License

MIT — see [LICENSE](./LICENSE).
