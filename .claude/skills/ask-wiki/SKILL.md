---
description: Answer a question by navigating the wisdom wiki — reads AGENTS, INDEX, candidate topic/author pages, follows wikilinks, returns an answer with citations. Refuses to hallucinate when the wiki is silent.
---

# /ask-wiki — read loop for the wisdom wiki (autonomous)

## What this skill does

Given a question, navigate `llm-wiki/wiki/` and return a cited answer:

1. Load the rule book (`AGENTS.md`) and the index (`INDEX.md`).
2. From the question, identify 2–5 candidate topic and author pages.
3. Read the candidates.
4. Follow `[[wikilinks]]` to related pages and (sparingly) into specific source files when a verbatim quote strengthens the answer.
5. Synthesise the answer.
6. Cite back to wiki pages and source files with wikilinks.
7. If the wiki is silent on the question, **say so** — point to the gap, suggest what source could fill it. Do not invent positions for investors not yet ingested.

**Autonomous.** No follow-up questions. The skill answers in one pass.

---

## Inputs

- **`/ask-wiki <question>`** — natural-language question. Examples:
  - `/ask-wiki What does Buffett say about margin of safety?`
  - `/ask-wiki How do Buffett and Marks differ on cycles?`
  - `/ask-wiki When does Munger argue you should NOT diversify?`

The question is a free-form string. No flags.

---

## Process

### 1. Load schema + index

Read `llm-wiki/wiki/AGENTS.md` (rule book, page-type semantics, author roster).
Read `llm-wiki/wiki/INDEX.md` (the table of contents).
Read `llm-wiki/wiki/ROUTING.md` — if it has active rules (deferred in Phase 1), apply them to shortlist candidate pages directly.

If `AGENTS.md` is missing: hard fail with "Wiki schema missing — bootstrap the wiki first."

### 2. Detect empty wiki

If `INDEX.md` shows `_no entries yet_` under all sections: respond gracefully:

```
The wiki has not been populated yet. Run /wiki-ingest on a source in llm-wiki/raw/ to seed it.
Suggested starting source: a Buffett partnership letter or Marks memo.
```

Do not attempt further synthesis. Stop.

### 3. Identify candidate pages

From the question, extract:

- **Concept keywords** → match against topic slugs in `INDEX.md ## Topics`. Examples: "margin of safety" → `[[topics/margin-of-safety]]`; "cycles" → `[[topics/drawdowns-and-temperament]]` and any cycles-specific topic.
- **Author names** → match against `INDEX.md ## Authors` and the `AGENTS.md` author roster (with aliases). "Buffett", "Warren", "WEB" → `[[authors/buffett]]`.
- **Comparison axis** → if the question contrasts two named investors ("Buffett vs Marks on..."), check `INDEX.md ## Comparisons` for an existing page on that axis; if absent, list both author pages instead.
- **Entity name** → "Berkshire", "Oaktree" → corresponding `entities/` page.

Aim for 2–5 candidate pages on the first sweep. More is fine if the question is broad; never fewer than 1.

### 4. Read the candidates

Use the `Read` tool on each shortlisted page. Internalise:

- The topic-page content and its citations.
- The author's position as stated on the author page.
- Any explicit `## Related` link sections — these are the agent's curated next hops.

### 5. Follow wikilinks judiciously

For each topic page, follow ≤2 outbound wikilinks if they materially strengthen the answer:

- **Follow into `[[sources/...]]`** when a verbatim quote is the strongest evidence and the topic page only paraphrases.
- **Follow into `[[comparisons/...]]`** when the question involves two or more authors.
- **Follow into related `[[topics/...]]`** when the question spans multiple concepts.

Do **not** follow every wikilink on a page — the topic page is the synthesis layer; deep traversal is for edge cases.

### 6. Synthesise the answer

Open with the direct answer in 1–3 sentences. Then expand with cited evidence — each investor's position quoted or paraphrased, cited via `[[source]]` wikilink.

When investors agree: state the agreement, name them, cite each.
When they differ: state the divergence, name them, cite each, and surface the load-bearing difference.

Length: match the question. Single-author factual questions → ~150 words. Cross-author comparative questions → up to ~500 words. Do not pad.

### 7. Handle gaps explicitly

If the wiki has thin or no coverage on the question:

- **Author not yet ingested?** State: "The wiki has no [Author] sources yet. To answer this properly, ingest a [recommended source]."
- **Topic exists but is sparse?** State: "The wiki currently only has [N] cited passages on this topic, all from [Author]. The picture below is incomplete."
- **Question is about TA / timing / live data?** Redirect: "This wiki is for fundamental wisdom. For technical setups, use `/ta-read`; for portfolio state, see `.valuation/portfolio.yaml`."

Never paper over gaps with general knowledge. The whole point of citable wisdom is to know what's evidenced and what isn't.

### 8. Append citations block

End every answer with a `## Citations` block listing every wikilink referenced, deduplicated, in the order they appeared in the body.

```markdown
## Citations

- [[topics/margin-of-safety]]
- [[authors/buffett]]
- [[sources/buffett/letters/1965-partnership-letter]]
```

### 9. Log silent gaps (optional — Phase 1 deferred)

In Phase 2, `/wiki-lint` will catch coverage gaps. For Phase 1: if a meaningful gap is surfaced, optionally append a one-liner to `LOG.md` under a `## YYYY-MM-DD — /ask-wiki gap` block — but do NOT auto-ingest, and do NOT modify any other wiki file.

---

## Output format

```
[direct answer, 1–3 sentences]

[expanded synthesis with cited evidence, one paragraph per author or per axis]

## Citations

- [[wikilink 1]]
- [[wikilink 2]]
- ...
```

For gap answers:

```
[gap statement — what the wiki does and does not contain on this question]

[best partial answer from what IS in the wiki, with citations]

[suggested next ingest to fill the gap]

## Citations

- [[whatever was actually used]]
```

---

## Edge cases

### Wiki is empty

Respond with the empty-wiki message (step 2). Do not synthesise.

### Question is out of scope

If the question is about live market data, position state, scans, TA, or timing — redirect to the appropriate tool. Examples: "Should I buy NVDA today?" → "Use `/ta-read NVDA` and check `tracker.yaml`. This wiki is for durable wisdom, not live decisions."

### Broken wikilink in a candidate page

If a `[[link]]` in a topic page points to a file that doesn't exist (`<!-- TODO: create page -->` comment or otherwise), skip it silently in the answer but mention the broken link at the end of the response under a `## Broken links surfaced` block — Phase 2's `/wiki-lint` will sweep these.

### Question contradicts a wiki claim

The wiki is evidence-based, not opinion-based. If the user's question has a built-in assumption that contradicts a wiki claim, surface the contradiction with citations: "The wiki actually argues X (cited from [[source]]), which contradicts the framing of the question."

### Multiple plausible interpretations of the question

Pick the most literal interpretation. Answer it. **Then** add a `## Other readings of the question` section listing the alternatives in one line each and inviting a follow-up. Do not pre-emptively answer all interpretations — one good answer beats three muddled ones.

### Question is multi-part

Answer each part in sequence under `### Part 1`, `### Part 2`. Citations block at the end covers all parts.

---

## Hard rules

1. **Zero user prompts.** Never call `AskUserQuestion`. Answer or explain the gap; never ask.
2. **Always cite.** Every non-trivial claim has a wikilink. Uncited synthesis is anti-pattern.
3. **Never hallucinate positions for un-ingested investors.** If Howard Marks hasn't been ingested, do not write "Marks would argue…" — write "the wiki has no Marks sources yet."
4. **Never invoke `/wiki-ingest` from within `/ask-wiki`.** The two loops are independent. If the read loop discovers a gap, optionally log it; do not auto-ingest.
5. **Never edit topic, author, entity, or comparison pages from this skill.** Read-only. Only the LOG may be touched (and only for gap-logging, optional).
6. **Don't overshoot length.** Match the question. A 100-word question doesn't need a 1000-word answer.
7. **Don't paraphrase when a verbatim quote is available.** If the source page has the quote, surface it.

---

## What this skill is NOT

- Not a Google-substitute — it answers only from what's been ingested.
- Not a chatbot — no small talk, no "Great question!" openers, no closing pleasantries.
- Not a fact-checker — if a wiki page is wrong, `/ask-wiki` will faithfully report what it says. `/wiki-lint` (Phase 2) is the correctness layer.
- Not interactive.

---

## Failure modes

| Failure | Cause | Fix |
|---|---|---|
| `AGENTS.md` missing | Wiki not bootstrapped | Hard fail; tell user to scaffold |
| `INDEX.md` missing | Wiki damaged | Hard fail; suggest `/wiki-rebuild-index` (Phase 2) or restoring from backup |
| No candidate pages identified from the question | Question vocabulary doesn't match any wiki slug | Fall back to reading all topic pages (still bounded — Phase 1 has at most a handful). If still no signal: emit gap response. |
| Topic page has frontmatter but empty body | Half-written page | Surface in the answer (`the page exists but is empty`), point at LOG to see when it was created |
| Recursive wikilinks (A links to B links to A) | Authoring error | Visit each page at most once per query |
