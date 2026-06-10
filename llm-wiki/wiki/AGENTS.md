# `llm-wiki/wiki/` — Agent Manifest

> **Rule of first contact.** When any Claude session touches a file under `llm-wiki/wiki/`, the first action is to read this file in full. Then read `INDEX.md`. Then act. Skipping this file means the operation is malformed.

---

<!-- PROJECT-SPECIFIC: edit this Purpose section when adopting in a new project. The "what this wiki holds" and "what it is NOT" lists should describe the new project's domain and cross-references. The Karpathy-pattern paragraph at the end of this section is universal — keep it. -->

## Purpose

This wiki holds **durable investor wisdom** — philosophy, mental models, multi-decade-stable principles — drawn from primary sources (books, shareholder letters, speeches, interviews, memos, podcast/video transcripts) of fundamentals-and-philosophy investors: Warren Buffett, Charlie Munger, Howard Marks, Peter Lynch, and a small handful of others as the corpus grows.

It is **NOT** for:

- Live market data (use TradingView MCP, `tracker.yaml`)
- Position state (use `portfolio.yaml`)
- Cascade theses (use `cascades.yaml`)
- TA / timing methodologies (those will live in the planned `.valuation/knowledge/methodologies/` sibling wiki)

<!-- /PROJECT-SPECIFIC -->

It is built on Karpathy's LLM Wiki pattern: **synthesize at ingest, navigate at query**. Knowledge is compiled into topic and author pages at ingest time. At query time, the agent navigates by structure (INDEX → topic page → wikilinks), not by similarity search.

---

## When Claude touches this wiki, the rule is

1. **Read this file first** (`AGENTS.md`).
2. **Read `INDEX.md`**.
3. **Then act** — ingest, query, edit, lint.

The skills `/wiki-ingest` and `/ask-wiki` both encode this. If you find yourself acting on a wiki file without having read both, stop and restart.

---

## Folder structure

```
llm-wiki/
  wiki/
    README.md           ← human-readable orientation (not loaded by skills)
    AGENTS.md           ← this file — rule book, loaded first
    INDEX.md            ← table of contents, loaded second
    LOG.md              ← chronological operation log (append-only)
    ROUTING.md          ← (deferred placeholder) query-routing rules

    topics/             ← synthesized concept pages — THE QUERYABLE LAYER
    authors/            ← per-investor worldview digests
    entities/           ← firms / vehicles (Berkshire, Oaktree, Magellan...)
    comparisons/        ← cross-author synthesis on one axis
    sources/            ← processed primary sources, citation-only
      <author>/<work_type>/<slug>.md
  raw/                  ← drop zone for unprocessed inputs (sibling of wiki/)
    processed/          ← archive of successfully-ingested raw files
```

The drop zone is `llm-wiki/raw/` — a sibling of `wiki/`, outside the wiki proper. Anything in `raw/` is fair game for `/wiki-ingest`; nothing in `wiki/` is fair game for direct manual edits except through a skill (or with full understanding of these rules).

---

## Page types

Every markdown file in the wiki is exactly one of these five types. The `type` field in frontmatter declares which.

### 1. `topic` — `topics/<slug>.md`

A concept or principle synthesized across authors. The queryable surface. Each topic page is the agent's first stop for any question about that concept.

**Created when:** an ingest surfaces a concept that isn't yet a topic page **and** that concept is plausibly cited by ≥2 investors in the corpus over time. Single-author concepts get a section on the author page, not a topic page.

**Contents:** a definition, the canonical framing, then a section per cited author with verbatim quotes + `[[source]]` wikilinks. Closing section: `## Related` linking to nearby topics.

### 2. `author` — `authors/<key>.md`

One investor's worldview, compiled as a digest. Created on first ingest of that author. Updated on every subsequent ingest of the same author.

**Contents:** one-paragraph bio, core principles (5–10 bullets, each with a `[[source]]` citation), characteristic mental models, recurring failure modes the investor warns against, link table to all topic pages the investor contributes to.

### 3. `entity` — `entities/<slug>.md`

A firm, fund, or vehicle of substantive importance: Berkshire Hathaway, Oaktree Capital, Fidelity Magellan, Wesco, See's Candies (as a Buffett case study), etc.

**Created when:** ≥2 sources discuss the entity substantively (not in passing). A single mention is a footnote, not an entity page.

**Contents:** brief history, role in the relevant author's career, key case studies (e.g., for Berkshire: insurance float, See's, Coca-Cola, the IBM mistake), `[[wikilinks]]` to authors and topics.

### 4. `comparison` — `comparisons/<slug>.md`

A cross-author synthesis on one axis. Examples: `buffett-vs-marks-on-cycles.md`, `lynch-vs-buffett-on-circle.md`, `munger-vs-marks-on-mental-models.md`.

**Created when:** the agent encounters a substantive disagreement, contrast, or complementary framing between two or more represented investors on a specific axis. **Never auto-create comparison pages from a single ingest** — they require ≥2 author perspectives already in the wiki.

**Contents:** the axis stated as a question, then each author's position with citations, then a synthesis note (where they agree, where they differ, what's load-bearing about the difference).

### 5. `source` — `sources/<author>/<work_type>/<slug>.md`

A processed primary source. **Citation-only.** Sources are not the queryable layer; topic pages are. Sources exist so that when a topic page makes a claim, the claim's evidence is one wikilink away.

**Created when:** `/wiki-ingest` processes a file from `llm-wiki/raw/`. Never created any other way.

**Contents:** full frontmatter (see below), then the cleaned markdown body of the original. Light cleanup is acceptable (fix obvious OCR errors, normalise whitespace, add structural headings if the original lacked them). Heavy summarisation is not — sources are for citation, so verbatim fidelity matters.

---

## Frontmatter conventions

Every markdown file (except the load-bearing roots — `README.md`, `AGENTS.md`, `INDEX.md`, `LOG.md`, `ROUTING.md`) carries YAML frontmatter.

### `topic` frontmatter

```yaml
---
type: topic
slug: margin-of-safety
created: 2026-05-27
updated: 2026-05-27
authors_cited: [buffett, munger, marks, graham]
tags: [valuation, risk, defensive-posture]
---
```

### `author` frontmatter

```yaml
---
type: author
key: buffett
full_name: Warren Buffett
born: 1930
primary_works: [partnership-letters, berkshire-letters, fortune-articles]
created: 2026-05-27
updated: 2026-05-27
---
```

### `entity` frontmatter

```yaml
---
type: entity
slug: berkshire-hathaway
founded: 1839
key_figures: [buffett, munger]
created: 2026-05-27
updated: 2026-05-27
---
```

### `comparison` frontmatter

```yaml
---
type: comparison
slug: buffett-vs-marks-on-cycles
axis: "How to think about market cycles"
authors: [buffett, marks]
created: 2026-05-27
updated: 2026-05-27
---
```

### `source` frontmatter

```yaml
---
type: source
author: Warren Buffett                    # full name, human-readable
author_key: buffett                       # lowercase last-name key
work: 1965 Partnership Letter             # specific work title
work_type: letter                         # letter | book-chapter | speech | interview | memo | podcast | video | article
year: 1965
work_part: null                           # null OR e.g. "chapter 8" for book chapters
url: https://www.berkshirehathaway.com/letters/1965.html
ingested: 2026-05-27
ingested_by: /wiki-ingest
seed_source: true                         # OPTIONAL — set true for Phase-1 placeholder / compiled-passages sources awaiting replacement by a verbatim original. Omit otherwise.
tags: [partnership-era, concentration, mr-market, margin-of-safety]
---
```

---

## Wikilink syntax

Obsidian-style internal links. Always relative to wiki root, no `.md` extension, no leading slash.

```markdown
See [[topics/margin-of-safety]].

Buffett describes margin of safety as a defensive moat in his
[[sources/buffett/letters/1965-partnership-letter]].

[[authors/munger|Munger]] (using a display alias) frames it differently.

[[topics/circle-of-competence#scope-of-knowledge]] (linking to a section).
```

**Rules:**

- Always `[[folder/file]]` — never relative paths (`./` or `../`) and never `.md`.
- Use `|alias` for display-text overrides when the slug reads awkwardly inline.
- Use `#heading` for deep links into a section.
- **Before writing a wikilink, verify the target exists.** If it doesn't, either create the page first (when appropriate per the page-type rules) or write the target name as plain text (no `[[ ]]`) and append `<!-- TODO: create page -->` so `/wiki-lint` (Phase 2) catches it.

---

## Citation rules

The point of this wiki is **citable wisdom**. Vague paraphrasing without attribution defeats the purpose.

1. **Every claim made about an investor's view must cite a source.** Cite via a `[[sources/...]]` wikilink. If you can't cite, you can't make the claim.
2. **Verbatim quotes are preferred** over paraphrase when the original is concise and quotable. Wrap quotes in standard markdown blockquotes (`>` prefix) and follow with the wikilink. Include page / chapter / paragraph if known.
3. **Paraphrase is acceptable** for longer passages. Make the paraphrase mark itself as such (`Buffett argues, in his 1965 letter, that…`) and cite the source.
4. **Never invent positions** for an investor who isn't in the wiki yet. If `/ask-wiki` is queried about Howard Marks but no Marks sources have been ingested, the answer must say so — not extrapolate from "general knowledge."
5. **Cross-investor citations on a topic page** should be ordered chronologically (oldest first) unless there's a thematic reason to reorder.

---

<!-- PROJECT-SPECIFIC: replace the Author roster and Topic taxonomy below with your new project's domain. Keep the structure (table format, key conventions, one-line definitions). The "key" column is what `/wiki-ingest` uses to map sources to authors — keep keys lowercase and stable. -->

## Author roster (current)

The authoritative list of investors covered. `/wiki-ingest` uses the `key` column to map sources to authors and the `aliases` column to fuzzy-match author names from source content.

| Key | Full name | Primary works | Aliases (for fuzzy match) |
|---|---|---|---|
| `buffett` | Warren Buffett | Partnership Letters (1957–1969), Berkshire Letters (1965–), Fortune articles, lectures | "Warren Buffett", "Warren E. Buffett", "WEB", "the Oracle of Omaha" |
| `munger` | Charles T. Munger | *Poor Charlie's Almanack*, USC 1994 "Psychology of Human Misjudgment", Wesco / Daily Journal meetings | "Charlie Munger", "Charles Munger", "Charles T. Munger" |
| `marks` | Howard Marks | *The Most Important Thing*, *Mastering the Market Cycle*, Oaktree memos (1990–) | "Howard Marks", "Howard S. Marks" |
| `lynch` | Peter Lynch | *One Up on Wall Street*, *Beating the Street*, *Learn to Earn*, interviews | "Peter Lynch", "Peter S. Lynch" |
| `graham` | Benjamin Graham | *The Intelligent Investor*, *Security Analysis* (with Dodd), 1976 Financial Analysts Journal interview | "Ben Graham", "Benjamin Graham" |

New authors may be added — append a row here, follow the same key conventions (lowercase last name), and create `authors/<key>.md` on first ingest.

---

## Topic taxonomy (seed)

The seven Phase-1 topic slugs. These exist as conceptual placeholders; topic pages are created lazily by `/wiki-ingest` when a source provides citable content for the topic.

| Slug | One-line definition |
|---|---|
| `margin-of-safety` | Buy below intrinsic value by a wide enough margin that errors of judgement leave you whole. (Graham; refined by Buffett, Marks.) |
| `owner-earnings` | Reported earnings adjusted for the cash a business can return to owners without impairing competitive position. (Buffett; an antidote to GAAP-driven mis-valuation.) |
| `circle-of-competence` | The set of businesses an investor genuinely understands. Outside the circle, expected returns are zero before fees. (Buffett, Lynch.) |
| `second-level-thinking` | Pricing not the consensus expectation but the divergence between consensus and reality. (Marks.) |
| `drawdowns-and-temperament` | Volatility is the price of admission to long-term returns; temperament is the gating skill. (Buffett, Marks, Munger.) |
| `position-concentration` | A small number of high-conviction positions vs. broad diversification. (Buffett's 20-hole punch card; Lynch's "know what you own".) |
| `mr-market-and-temperament` | Graham's allegory of Mr. Market — a manic-depressive partner offering prices that one can accept, reject, or exploit. (Graham, refined by Buffett.) |

New topics may emerge as ingests reveal them — `/wiki-ingest` is empowered to create new topic pages when the criteria in "Page types: topic" are met. Add the new slug here as part of that ingest's update sweep.

<!-- /PROJECT-SPECIFIC -->

---

## When the ingest skill is ambiguous

The ingest skill is **autonomous** — it never asks the user. When it hits an ambiguity, it follows these rules and logs the choice in `LOG.md` under the entry's `Notes` field.

| Ambiguity | Rule |
|---|---|
| Author of source is unclear from filename + content | Match against the author roster aliases. Pick the highest-confidence match. Note the inference in LOG. |
| Source touches a borderline topic (single-author concept that might also become multi-author later) | Add the section to the author page first. Only promote to a topic page when a second author cites the same concept. |
| New topic would be created — name is borderline (`mental-models` vs `latticework-of-mental-models`) | Use the shorter, more general slug. Cross-reference in the topic body. |
| Source is a chapter / excerpt of a longer work | Set `work_part` in frontmatter (e.g., `"chapter 8: Mr. Market"`). Use the work's full title in `work`. |
| Source contains multiple speakers (interview, panel) | The "author" is the **primary speaker** (the investor whose wisdom is being captured). Add the interviewer / other speakers in the source body but not as authors. |
| Source has no clear date | Use the publication or recording date. If genuinely unknown, set `year: null` and add a `circa:` tag (e.g., `tags: [circa-1990s]`). |
| Source is in audio / video and `transcribe` skill fails | Log the failure, leave the file in `raw/`, do not create a partial source page. Surface in the final summary. |

**Never ask the user.** Pick the best-evidence option, write it down, move on. Wrong calls are cheaper than friction — they can be corrected by re-ingesting or by manual edit.

---

## LOG.md format

`LOG.md` is append-only. Every operation that mutates the wiki appends one block. Format:

```markdown
## YYYY-MM-DD HH:MM — /wiki-ingest

- **Source:** `raw/<original-filename>`
- **Resolved to:** `sources/<author>/<work_type>/<slug>.md`
- **Topic pages updated:** topic-slug-a, topic-slug-b
- **Topic pages created:** (none) | topic-slug-c
- **Author page updated:** <author-key>
- **Entity pages touched:** (none) | entity-slug
- **Comparison pages touched:** (none)
- **INDEX updated:** yes/no — what changed
- **Notes:** any inferences (e.g., "guessed author = Munger from internal cues"), edge-case decisions, deferred items.
```

For `/wiki-lint` and `/wiki-rebuild-index` (Phase 2), the format will be analogous but driven by their respective action verbs.

---

## Tone & length guide for wiki pages

- **Terse.** A topic page is not a textbook chapter. Aim for 200–600 words per topic, expanding only with cited content. Padding is anti-pattern.
- **Citation-dense.** Every non-trivial claim has a wikilink. If a paragraph has no wikilinks, it's probably either too abstract or missing evidence.
- **No chatbot voice.** Don't open with "Let's explore…" or close with "In summary…". Write like a research analyst: state the claim, cite the evidence, move on.
- **No hedging by default.** When investors disagree, say so explicitly and cite both. Don't write "some argue X, others argue Y" without naming names.
- **Quotes are gold.** A two-sentence verbatim quote from Buffett or Munger is worth more than a paragraph of paraphrase.

---

<!-- PROJECT-SPECIFIC: list this project's cross-references — other wikis, key config files, anything an ingest should respect. -->

## Cross-references

- **Sibling TA wiki (planned).** `.valuation/knowledge/methodologies/` will hold technical/timing methodologies (Weinstein / Minervini / Qullamaggie / Shannon). This wiki and that one cover different domains — never cross-pollute. If a `/wiki-ingest` source is genuinely about timing rather than philosophy, abort the ingest and surface the misclassification.
- **Project root `CLAUDE.md`.** Mission, position rules, conventions. Read once per session for general project orientation; not loaded by every wiki operation.

<!-- /PROJECT-SPECIFIC -->

---

## Versioning

This manifest is treated as load-bearing — changes to the schema (page types, frontmatter fields, citation rules) require corresponding updates to both `/wiki-ingest` and `/ask-wiki`. When the schema evolves:

1. Edit this file.
2. Bump the schema understanding inside the affected skill SKILL.md.
3. Log the schema change in `LOG.md` under a `## YYYY-MM-DD HH:MM — schema-update` block.

The wiki is small enough that breaking-change migrations are cheap. Prefer clarity over backwards compatibility.
