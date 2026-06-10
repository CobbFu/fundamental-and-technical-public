# Fundamental and Technical

Python tooling for US- and European-equity trend research: momentum, supply-chain
("cascade"), and early-stage scanners; a watch/hold tracker with a daily digest;
and an **agentic-RAG knowledge wiki** the agent navigates by structure.

This repository is a **source-code showcase** — it ships the engine, tests, and
wiki framework only. No portfolio, watchlist, or personal data is included.

## Layout

| Path | What it is |
|------|------------|
| `src/momentum/` | Universe momentum screen (S&P 500 + 400, STOXX 600) with tiering and change detection |
| `src/cascade/`  | Supply-chain breadth scan over a curated theme map |
| `src/early/`    | Pre-momentum base scan: surfaces names *before* the run |
| `src/tracker/`  | Watch/hold tracker (`tracker.yaml`) + portfolio join + daily digest renderer |
| `src/street/`   | Analyst price-target consensus and revision dynamics |
| `src/scout/`, `src/calculators/`, `src/comps/` | Fundamentals pulls, valuation helpers, comparables types |
| `src/common/`   | Shared types and a rolling-backup helper |
| `tests/`        | Test suite |
| `llm-wiki/`     | Agentic-RAG investing-wisdom wiki — framework + synthesis (source texts not bundled) |
| `.claude/skills/` | Two Claude Code skills that drive the wiki: `wiki-ingest` and `ask-wiki` |

## The knowledge wiki — agentic RAG, not embeddings

`llm-wiki/` follows Andrej Karpathy's [LLM-wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f):
**synthesise at ingest, navigate at query.** Rather than embedding raw documents and
retrieving the nearest chunks at query time (standard vector RAG), an ingest step
*compiles* sources into a structured, interlinked markdown wiki; at query time the
agent navigates `INDEX → topic → [[wikilink]]` **by structure — no vector store, no
embeddings.** It is, in Karpathy's phrase, "agentic RAG with exactly one tool: the
wiki itself," and unlike a passive index it **compounds** across sessions.

Two Claude Code skills drive it:

- **`wiki-ingest`** — the write loop. Reads the rule book (`AGENTS.md`), then a raw
  source, writes a citation-only `source` page, and rewrites every topic/author/entity
  page it touches with verbatim quotes + `[[source]]` links; updates `INDEX.md` and `LOG.md`.
- **`ask-wiki`** — the read loop. Walks `INDEX → topic → [[wikilink]]` and answers with
  a citations block, under a hard rule: **never invent a position for an author who
  hasn't been ingested.**

**Page types** (declared in each file's frontmatter, governed by `wiki/AGENTS.md`):

- `topics/` — the queryable layer: synthesised concept pages cited across ≥2 investors —
  margin-of-safety, intrinsic-value, owner-earnings, circle-of-competence,
  position-concentration, second-level-thinking, mr-market-and-temperament, cycles,
  drawdowns-and-temperament, wonderful-businesses-and-time.
- `authors/` — per-investor worldview digests (Buffett, Marks; Munger/Lynch/Graham scaffolded).
- `entities/` — firms & vehicles (Berkshire Hathaway).
- `comparisons/` — cross-author synthesis on one axis (deferred until ≥2 perspectives exist).
- `sources/` — processed primary sources, citation-only (the Berkshire letters, a Marks chapter).

`raw/` is the ingest drop zone; `wiki/{AGENTS,INDEX,LOG,ROUTING,README}.md` are the
load-bearing roots.

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
