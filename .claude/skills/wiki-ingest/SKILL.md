---
description: Process a file in llm-wiki/raw/ into the wisdom wiki — converts to markdown, adds frontmatter, moves to sources/<author>/<work_type>/, updates topic + author + entity pages, updates INDEX, appends LOG. Zero questions — best-guess + log + proceed.
---

# /wiki-ingest — write loop for the wisdom wiki (autonomous)

## What this skill does

Given a path to a file in `llm-wiki/raw/`, ingest it into the wisdom wiki at `llm-wiki/wiki/`:

1. Load the wiki's rule book (`AGENTS.md`).
2. Read the source — PDF, audio, HTML, plain text.
3. Convert to clean markdown, stamp with YAML frontmatter, save to `sources/<author>/<work_type>/<year>-<slug>.md`.
4. Identify which topic pages this source contributes to. Update each — append verbatim quotes + `[[source]]` citations.
5. Update the author page (create if first time).
6. If a notable firm is discussed substantively, update or create the corresponding entity page.
7. Update `INDEX.md` for any new pages.
8. Append a structured entry to `LOG.md`.
9. Report a one-block summary to the user — files touched, inferences made, anything deferred.

**Autonomous.** The skill never asks the user a question. When something is ambiguous, it picks the best-evidence option and notes the choice in the LOG entry. Wrong calls are cheaper than friction — they're corrected by re-ingesting or by manual edit.

---

## Inputs

- **`/wiki-ingest <path>`** — path to a file in `llm-wiki/raw/`. Example: `/wiki-ingest llm-wiki/raw/Buffett-1965-Letter.pdf`.
- **`/wiki-ingest`** (no argument) — infer the **most recently modified file** in `llm-wiki/raw/` and proceed with that. Log the inference.

Acceptable formats: PDF (read natively via the `Read` tool), MP3 / MP4 / M4A / WAV (transcribe first via the `transcribe` skill), HTML, MD, TXT.

---

## Process

### 1. Load the rule book

Read `llm-wiki/wiki/AGENTS.md` in full. Internalise:
- The five page types and their creation rules
- The frontmatter spec for each page type
- The author roster (`buffett`, `munger`, `marks`, `lynch`, `graham`, plus any later additions)
- The seed topic taxonomy
- The citation rules
- The "when ambiguous" decision table
- The LOG.md format

If `AGENTS.md` is missing or unreadable: hard fail with "Wiki schema missing — `llm-wiki/wiki/AGENTS.md` not found. Bootstrap the wiki first."

### 2. Resolve the input file

If a path argument was given: verify the file exists. If not: hard fail with "File not found: `<path>`. Check `llm-wiki/raw/` listing."

If no argument: list `llm-wiki/raw/` sorted by mtime descending, pick the first non-`.gitkeep` entry, log the inference.

### 3. Read the source content

| Extension | How to read |
|---|---|
| `.pdf` | `Read` tool — Claude reads PDFs natively per the tool's docs. |
| `.md` `.txt` `.html` | `Read` tool directly. Light cleanup of obvious encoding noise. |
| `.mp3` `.mp4` `.m4a` `.wav` `.mkv` | Invoke the `transcribe` skill. Use the resulting markdown transcript as the body. |
| Other / scanned PDF without text layer | Log failure, leave the raw file in place, abort with a clear message. |

The content of the source becomes the *body* of the eventual source page. Do not summarise the body — sources are citation-only and need fidelity. Light cleanup is fine (fix obvious OCR errors, normalise whitespace, add structural headings if the original lacked them).

### 4. Identify author

Use this priority order:

1. **Filename hint** — e.g., `Buffett-1965-Letter.pdf` clearly indicates Buffett.
2. **First-page content cues** — "Berkshire Hathaway Inc.", "Oaktree Capital", "by Warren Buffett", a recognised letterhead.
3. **Author roster aliases** in `AGENTS.md` — fuzzy match.
4. **Content style cues** — Munger's Latin / psychology vocabulary; Marks's "first-level / second-level" frame; Lynch's everyman tone; Buffett's folksy + numeric style.

If genuinely unclear after all four: pick the best-evidence option, set `tags: [author-uncertain]`, note "guessed author = X from internal cues (low confidence)" in LOG.

### 5. Identify work + work_type + year

Work types: `letter | book-chapter | speech | interview | memo | podcast | video | article`.

| Heuristic | Map to |
|---|---|
| Filename contains "letter", "shareholder", or a year in the 1957–1969 range with Buffett author | `letter` |
| Title page is "The Most Important Thing Is …" (Marks memo title pattern) | `memo` |
| Audio / video source | `podcast` or `video` (use `video` if originally on YouTube / Vimeo; `podcast` otherwise) |
| Annual letter to Berkshire shareholders | `letter` (year is the cover year, e.g. `1989` not `1990` even if dated Feb 1990) |
| Book excerpt (single chapter) | `book-chapter` with `work_part` set (e.g., `"chapter 8: Mr. Market"`) |
| Magazine / newspaper article | `article` |
| Speech at a university / conference | `speech` |
| Q&A / sit-down conversation | `interview` |

Year: pull from cover page, publication date, or filename. If truly unknown: `year: null` plus a `circa-` tag.

### 6. Slugify and build the source path

```
sources/<author_key>/<work_type_plural>/<year>-<short-slug>.md
```

- `author_key` is lowercase last name (`buffett`, `munger`, ...).
- `work_type_plural`: `letters`, `book-chapters`, `speeches`, `interviews`, `memos`, `podcasts`, `videos`, `articles`.
- `<short-slug>` is kebab-case, ≤6 words, capturing the work's essence.

Examples:
- `sources/buffett/letters/1965-partnership-letter.md`
- `sources/munger/speeches/1994-psychology-of-misjudgment.md`
- `sources/marks/memos/2008-01-the-limits-to-negativism.md` (use year-month for memos, since Marks publishes many per year)
- `sources/lynch/book-chapters/1989-tenbagger-rules.md` with `work: "One Up on Wall Street"` and `work_part: "chapter 14"`.

### 7. Write the source file

Compose the file as: YAML frontmatter (per the `source` spec in `AGENTS.md`) + a blank line + the cleaned markdown body.

```yaml
---
type: source
author: Warren Buffett
author_key: buffett
work: 1965 Partnership Letter
work_type: letter
year: 1965
work_part: null
url: https://www.berkshirehathaway.com/letters/1965.html
ingested: 2026-05-27
ingested_by: /wiki-ingest
tags: [partnership-era, concentration, mr-market, margin-of-safety]
---

# 1965 Partnership Letter

[body of the source, lightly cleaned]
```

Write the file. Then **move** (not copy) the file from `llm-wiki/raw/` to a `processed/` archive — `llm-wiki/raw/processed/<original-filename>` — so the raw drop zone doesn't accumulate duplicates. (Create `llm-wiki/raw/processed/` if it doesn't exist.)

### 8. Scan content for topics

Read the source body. For each candidate topic, decide:

- **Already a topic page** (`topics/<slug>.md` exists)? → Update it. Append a section under `## <Author full name>` with the citation, or extend the existing author section if present.
- **Not yet a topic page, but the concept is plausibly multi-author** (per the page-type criterion in `AGENTS.md`)? → Create `topics/<slug>.md` with the topic frontmatter, a one-paragraph definition, and the first author section.
- **Not yet a topic, and the concept is single-author-specific**? → Skip. Add to the author page instead. (Promote to a topic page on a future ingest if a second author cites it.)

The seven seed topic slugs from `AGENTS.md`:

```
margin-of-safety
owner-earnings
circle-of-competence
second-level-thinking
drawdowns-and-temperament
position-concentration
mr-market-and-temperament
```

For each topic-page update:

1. Read the existing page (if any).
2. Identify the section for this author (`## Warren Buffett`, `## Charlie Munger`, ...).
3. Append a quote block (`>`) with the verbatim passage, followed by the `[[source]]` wikilink and a one-sentence framing.
4. Update `updated:` in frontmatter to today.
5. Update `authors_cited:` in frontmatter if this author is new to the topic.

### 9. Update the author page

`authors/<author_key>.md`.

- **First ingest of this author:** create the page with the `author` frontmatter, a one-paragraph bio (from canonical knowledge), and a `## Core principles` section seeded from this source's contributions.
- **Subsequent ingests:** read the existing page, append new core-principles bullets (each cited), and update the `updated:` and `## Topics covered` link table.

### 10. Update entity pages (if applicable)

Scan the source for **substantive** discussion of firms or vehicles. Substantive = ≥2 paragraphs of discussion, or a clear case study, not a passing mention.

For each substantive firm:

- **Entity page exists** (`entities/<slug>.md`)? → Append a section with what this source adds.
- **Entity page doesn't exist, and this is the second substantive mention across the corpus**? → Create the entity page. (First substantive mention: just add to the relevant author/topic pages; defer entity-page creation until corroboration.)
- **First mention only**? → Skip the entity page; cite via the source link in topic/author pages.

Track entity-mention counts implicitly by checking whether the entity name appears in any existing wiki page (`grep` is fine).

### 11. Update INDEX.md

For any of these conditions, add a line under the corresponding `INDEX.md` section:

- New topic page → add to `## Topics`
- New author page → add to `## Authors`
- New entity page → add to `## Entities`
- New source page → add to `## Sources by author` under the relevant author subsection (create the subsection on first source for that author)

Format example:

```markdown
## Topics

- [[topics/margin-of-safety]] — Buy below intrinsic value by a wide enough margin that errors leave you whole.

## Sources by author

### buffett

- [[sources/buffett/letters/1965-partnership-letter]] — 1965 partnership letter; concentration, margin of safety, mr-market.
```

Also bump the `## Last refresh` line to today's date.

### 12. Append LOG.md entry

Per the format in `AGENTS.md`:

```markdown
## 2026-05-27 18:42 — /wiki-ingest

- **Source:** `raw/Buffett-1965-Letter.pdf`
- **Resolved to:** `sources/buffett/letters/1965-partnership-letter.md`
- **Topic pages updated:** margin-of-safety, mr-market-and-temperament
- **Topic pages created:** (none)
- **Author page updated:** buffett (created)
- **Entity pages touched:** (none)
- **Comparison pages touched:** (none)
- **INDEX updated:** yes — added buffett author + 1965 source under Sources by author
- **Notes:** clean ingest; 4 verbatim citations extracted; author was inferred from filename.
```

### 13. Print summary block to user

Single block, no follow-up question. Format:

```
## Wiki ingest complete

- **Source:** <raw filename> → [[sources/<resolved path>]]
- **Author:** <full name> (<key>)<if first ingest of author: " — new author page created">
- **Topics touched:** <list>
- **Topics created:** <list or "(none)">
- **Entities touched:** <list or "(none)">
- **INDEX:** <change summary>
- **LOG:** entry appended

### Inferences made
- <each non-trivial inference, one bullet>

### Next steps
- Read [[INDEX.md]] to see the new entries.
- Drop another source into `llm-wiki/raw/` and run /wiki-ingest again.
```

That's the full output. **No "want me to also..." follow-ups.**

---

## Edge cases

### Multiple authors in one source (interview, panel)

Set `author` to the **primary speaker** (the investor whose wisdom is the point of the ingest). Mention other speakers in the source body but do not list them in `author`. If the interviewer is themselves an investor in the roster (e.g., Marks interviewing Buffett), note this in the LOG.

### Partial source — chapter excerpt of a longer work

Set `work` to the work's title and `work_part` to the chapter / section identifier. The slug should hint at the part: `sources/lynch/book-chapters/1989-tenbagger-rules.md`.

### Source has no clear date

Set `year: null` and add a `circa-1990s` tag (or finer if known). Note the date ambiguity in LOG.

### Source spans multiple decades (e.g., a compilation memo)

Use the publication year of the compilation. Tag with `[compilation]`.

### Source language is not English

Phase 1: skip. Log "non-English source — deferred to Phase 2+". Phase 2+ may add a translation step.

### Source is too long to fit in one read

Read in segments. Concatenate the cleaned text in the source body. Skill remains autonomous — do not ask the user to choose.

### Source contradicts an existing wiki claim

Update the topic page to surface the contradiction (e.g., "Buffett's 1989 letter reframes this earlier position…"). Never silently delete the older citation — both are evidence. If the contradiction is between two authors, that's natural — that's what `comparisons/` pages exist for (create one if not present per the page-type rule).

### Unparseable file (scanned PDF without OCR, corrupted audio)

Abort gracefully. Log the failure. Leave the file in `llm-wiki/raw/` (do not move to `processed/`). Surface in the summary.

---

## Hard rules

1. **Zero user prompts.** Never call `AskUserQuestion`. Never write "want me to..." follow-ups. If a decision is genuinely impossible, hard fail with a one-liner.
2. **Always read `AGENTS.md` first.** It's the rule book. Skipping it produces malformed ingests.
3. **Light cleanup only on source bodies.** Verbatim fidelity is the point — sources are citation evidence.
4. **Move raw files to `processed/` after successful ingest.** Prevents duplicate ingests of the same file.
5. **Don't auto-promote single-author concepts to topic pages.** Wait for the second author. Author pages absorb single-author concepts.
6. **Don't auto-create comparison pages from a single ingest.** Requires ≥2 author perspectives already in the wiki.
7. **Don't write wikilinks to pages that don't exist.** Either create the page first (when the page-type rule allows) or write plain text with a `<!-- TODO: create [[page]] -->` comment.
8. **The wiki is for wisdom, not TA.** If a source is genuinely about timing or chart patterns rather than philosophy, abort the ingest and surface the misclassification.

---

## What this skill is NOT

- Not a research summariser — sources stay verbatim; synthesis happens in topic pages.
- Not interactive — one summary at the end, no questions.
- Not a translator (yet).
- Not a TA / methodologies ingester — that's the sibling planned wiki.

---

## Failure modes

| Failure | Cause | Fix |
|---|---|---|
| `AGENTS.md` missing | Wiki not bootstrapped | Hard fail; tell user to scaffold the wiki first |
| File in `llm-wiki/raw/` doesn't exist | Bad path | Hard fail with `ls llm-wiki/raw/` hint |
| `transcribe` skill returns error | Audio file corrupted or unsupported | Log failure, leave file in raw/, abort |
| Scanned PDF without OCR text | No text layer | Log failure, abort with "no OCR text layer — preprocess externally" |
| Topic page write conflict (concurrent edit) | Another skill or manual edit mid-flight | Re-read the topic page before merging; if still conflicts, log + abort |
| Author roster has no match for source | Genuinely new author | Add a row to AGENTS.md author roster, then proceed (log the addition) |
| Non-English source | Out of scope for Phase 1 | Log "non-English source — deferred", abort |
