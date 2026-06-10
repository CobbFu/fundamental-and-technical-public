# `llm-wiki/wiki/` — Investor Wisdom Library

A curated, searchable knowledge base of investing wisdom from Warren Buffett, Charlie Munger, Howard Marks, Peter Lynch, and others.

Built on Karpathy's LLM Wiki pattern: **synthesize at ingest, navigate at query**. Knowledge is compiled into topic and author pages, not stored as raw chunks waiting to be retrieved.

---

## Structure

```
llm-wiki/
  wiki/
    README.md                    ← this file
    AGENTS.md                    ← system manifest, loaded by Claude on every wiki touch
    INDEX.md                     ← top-level table of contents
    LOG.md                       ← chronological operation log
    ROUTING.md                   ← (deferred) query routing rules — add later if needed

    topics/                      ← synthesized concept pages (the queryable layer)
    authors/                     ← per-investor worldview pages
    entities/                    ← firms / vehicles (Berkshire, Oaktree, etc.)
    comparisons/                 ← cross-author synthesis pages
    sources/                     ← processed primary sources, organized by author/type

    .search.db                   ← (Phase 2) SQLite FTS5 keyword search index
  raw/                           ← drop zone (sibling of wiki/, not inside it)
    processed/                   ← archive of successfully-ingested raw files
```

The two skills that operate on this wiki live OUTSIDE `llm-wiki/`, at the project root:

```
.claude/skills/wiki-ingest/SKILL.md     ← the write loop
.claude/skills/ask-wiki/SKILL.md        ← the read loop
```

Skills must live in `.claude/skills/` for Claude Code to auto-discover them.

`llm-wiki/raw/` is where you dump anything — PDFs, transcripts, scraped articles, podcast text. The `/wiki-ingest` skill processes from there.

---

## Daily workflow

### To ADD knowledge

1. **Drop a source** into `llm-wiki/raw/` — any format (PDF, MP3 transcript, scraped HTML, plain text).
2. Run **`/wiki-ingest llm-wiki/raw/<filename>`** in Claude Code.
3. Claude will:
   - Convert it to clean markdown
   - Stamp it with YAML frontmatter (author, work, year, type, tags)
   - Move it to `sources/<author>/<type>/<slug>.md`
   - Identify which topic pages it touches
   - Update each affected `topics/*.md` with what this source contributes, including verbatim quotes and `[[citations]]` back to the source
   - Update `authors/<name>.md`
   - Update `INDEX.md` if new topics emerged
   - Append an entry to `LOG.md`
4. Review the diff Claude shows you, accept or adjust.

### To ASK the wiki

Run **`/ask-wiki <your question>`**. Claude will:
1. Read `AGENTS.md` (the system manifest)
2. Read `INDEX.md`
3. Identify relevant topic and author pages
4. Read them and follow `[[wikilinks]]`
5. Optionally pull verbatim quotes from `sources/` for citation
6. (If navigation isn't enough) fall back to BM25 keyword search via `/wiki-search`
7. Answer with citations

### To MAINTAIN the wiki

- **`/wiki-lint`** — health check. Detects broken wikilinks, sources referenced by topic pages but missing from `sources/`, topic pages missing key authors' perspectives, duplicate concepts, stale claims. Writes report to `LOG.md`.
- **`/wiki-search <query>`** — direct BM25 keyword search when navigation isn't enough.
- **`/wiki-rebuild-index`** — regenerate `INDEX.md` from current folder state and rebuild `.search.db`.

---

## Conventions

### Wikilinks

Use `[[topics/margin-of-safety]]` Obsidian-style links between pages. You can open `llm-wiki/wiki/` as an Obsidian vault to get the visual graph view for free.

### Frontmatter

See [[AGENTS.md#frontmatter-conventions]] for the canonical schema across all five page types (topic, author, entity, comparison, source). The AGENTS.md spec is the single source of truth — this README is human orientation only.

### Citation style

In `topics/*.md` and `authors/*.md`, cite back to sources with wikilinks:

```markdown
Buffett describes margin of safety as a defensive moat in his
[[sources/buffett/letters/1965-partnership-letter]], explaining
that "you don't need to swing at every pitch."
```

---

## What's NOT in this wiki

- Live market data — that's TradingView MCP, `tracker.yaml`, scans
- Portfolio state — that's `portfolio.yaml`
- Cascade theses — those live in `cascades.yaml` and `.valuation/Building/knowledge/`

The wiki is for **durable, citable investor wisdom**. Other knowledge layers stay in their existing locations.

---

## Skills reference

| Skill | Purpose |
|---|---|
| `/wiki-ingest <path>` | Write loop. Process a raw source into topic + author + entity + INDEX updates. |
| `/ask-wiki <question>` | Read loop. Navigate the wiki and answer with citations. |
| `/wiki-lint` | (Phase 2) Health check. Find broken links, coverage gaps, duplicates. |
| `/wiki-search <query>` | (Phase 2) BM25 search escape hatch. |
| `/wiki-rebuild-index` | (Phase 2) Regenerate INDEX.md and `.search.db`. |

---

## Installing this wiki in another project

This wiki folder (`llm-wiki/`) is designed to be portable. To use the same pattern in a different project:

### 1. Copy two things into the new project

```bash
# From the original project, copy:
cp -r llm-wiki                          /path/to/new-project/
cp -r .claude/skills/wiki-ingest        /path/to/new-project/.claude/skills/
cp -r .claude/skills/ask-wiki           /path/to/new-project/.claude/skills/
```

The `llm-wiki/` folder carries the schema, the daily-workflow, and any content you want to keep. The two skill folders MUST live at `.claude/skills/` in the new project — Claude Code only auto-discovers skills there.

### 2. Empty the content (start fresh)

In the new project:

```bash
# Wipe the example content from this project
rm -rf llm-wiki/wiki/topics/*.md
rm -rf llm-wiki/wiki/authors/*.md
rm -rf llm-wiki/wiki/entities/*.md
rm -rf llm-wiki/wiki/comparisons/*.md
rm -rf llm-wiki/wiki/sources/*
rm -rf llm-wiki/raw/processed/*

# Keep the .gitkeep files in each empty folder
touch llm-wiki/wiki/{topics,authors,entities,comparisons,sources}/.gitkeep
touch llm-wiki/raw/.gitkeep

# Reset LOG.md to a fresh BOOTSTRAP entry (manual edit)
```

### 3. Edit `AGENTS.md` to your new project's domain

Open `llm-wiki/wiki/AGENTS.md` and rewrite every section marked `<!-- PROJECT-SPECIFIC -->`:

- **Purpose paragraph** — what kind of wisdom / domain / corpus is this wiki for?
- **Author roster table** — who are the primary thinkers / sources / subjects?
- **Topic taxonomy seed** — what concepts will this wiki synthesise across authors?
- **Cross-references** — what other files / wikis / config does this project's wiki need to respect or avoid overlapping with?

The universal sections (page types, frontmatter conventions, wikilink syntax, citation rules, "when ambiguous" decision rules, LOG format, tone guide) should be kept as-is.

### 4. Edit the SKILL.md files if needed

Open `.claude/skills/wiki-ingest/SKILL.md` and `.claude/skills/ask-wiki/SKILL.md`. The skill logic is domain-agnostic, but example author names (Buffett, Munger, Marks, Lynch) appear throughout as illustrations — replace with examples from your new domain if you want, or leave them as generic guidance.

The paths inside the skills (`llm-wiki/wiki/AGENTS.md`, `llm-wiki/raw/`, etc.) assume the new project uses the same `llm-wiki/` folder name at its root. If you rename the folder, grep-and-replace.

### 5. Seed the wiki

Drop one real source into `llm-wiki/raw/` and run `/wiki-ingest`. Confirm the source ends up at `llm-wiki/wiki/sources/<author>/<type>/`, that topic + author pages are created, and that LOG.md gets an entry. That's the loop working.

---

This pattern follows Karpathy's [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), with refinements from lucasastorian/llmwiki, skyllwt/OmegaWiki, axoviq-ai/synthadoc, and the implementations shown by Cole Medin and Nate Herkelman on YouTube.
