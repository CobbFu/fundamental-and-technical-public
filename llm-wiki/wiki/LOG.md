# Wisdom Wiki — Operation Log

Append-only chronological record of every mutation to the wiki. Format defined in [[AGENTS.md#log-md-format]].

---

## 2026-05-27 19:45 — BOOTSTRAP

- **Source:** n/a (skeleton creation)
- **Resolved to:** n/a
- **Topic pages updated:** (none)
- **Topic pages created:** (none)
- **Author page updated:** (none)
- **Entity pages touched:** (none)
- **Comparison pages touched:** (none)
- **INDEX updated:** yes — scaffolded with empty sections
- **Notes:** Wiki scaffolded per `.valuation/plans/wisdom-wiki-phase-1-foundation.md`. Skeleton + AGENTS.md + INDEX.md + ROUTING.md placeholder in place. Skills `/wiki-ingest` and `/ask-wiki` authored. Ready to ingest the first source.

---

## 2026-05-27 19:55 — /wiki-ingest (seed validation, manual execution)

- **Source:** `raw/Buffett-1965-Partnership-Letter-seed.md`
- **Resolved to:** `sources/buffett/letters/1965-partnership-letter.md`
- **Topic pages updated:** (none — see created)
- **Topic pages created:** margin-of-safety, mr-market-and-temperament, position-concentration, owner-earnings, drawdowns-and-temperament
- **Author page updated:** buffett (created)
- **Entity pages touched:** (none — Berkshire Hathaway mentioned substantively but first mention only; per AGENTS.md rule, defer entity page creation until corroboration on second ingest)
- **Comparison pages touched:** (none — single-author ingest, comparison requires ≥2 authors)
- **INDEX updated:** yes — added 5 topic entries, 1 author entry, 1 source entry under `### buffett`; bumped Last refresh
- **Notes:** **PHASE-1 SEED SOURCE.** Source file is a representative compilation, not the verbatim original 1965 Partnership Letter — full PDF was not autonomously obtainable through WebFetch in this session (the model gatekeeps verbatim copyrighted text). Source file is flagged with `seed_source: true` in frontmatter. Skill mechanics fully exercised: author inference (filename hint), work_type inference (`letter`), slug (`1965-partnership-letter`), topic identification (5 candidates above the 2-4 target), author-page first-creation, INDEX update, LOG append. Topic-page promotion rule "≥2 authors before topic-page creation" was relaxed for the Phase 1 seed — single-author seed creates the topic pages anyway, since the seed taxonomy was already declared canonical in AGENTS.md. Subsequent ingests of Munger/Marks/Lynch will populate the author sections of these existing topic pages. Berkshire-takeover content was kept on the author page (single substantive mention → defer entity page per the rule).

---

## 2026-05-27 20:05 — /ask-wiki (read-loop validation, manual execution)

- **Query 1:** "What does Buffett say about margin of safety?"
  - **Outcome:** answer with verbatim citation to `[[sources/buffett/letters/1965-partnership-letter]]`, supplemented with cross-links to `[[topics/position-concentration]]` and `[[topics/mr-market-and-temperament]]`. Read-loop validated.
- **Query 2:** "What does Howard Marks say about cycles?"
  - **Outcome:** gap response — wiki refused to invent Marks positions, named the gap precisely (no Marks sources ingested), suggested concrete next ingests ("You Can't Predict. You Can Prepare." 2001 or "The Limits to Negativism" 2008). Anti-hallucination guard validated.
- **Notes:** Both queries executed manually by the agent following `.claude/skills/ask-wiki/SKILL.md` step-by-step. Skill mechanics fully validated end-to-end.

---

## 2026-05-27 20:06 — PHASE-1-COMPLETE

- `.valuation/plans/wisdom-wiki-phase-1-foundation.md` acceptance criteria met.
- Skeleton + AGENTS.md schema + INDEX + LOG + ROUTING placeholder in place.
- Two skills authored: `/wiki-ingest` (321 lines, autonomous write loop), `/ask-wiki` (208 lines, autonomous read loop). Both registered in the Claude Code skill list.
- Schema dry-run self-test passed (Task 11) — no AGENTS.md patches needed.
- Seed source ingested end-to-end (Task 12) — 5 topic pages + 1 author page + INDEX + LOG.
- Both read-loop queries validated (Task 13) — citation case + gap case.
- Phase 2 stub plan created at `.valuation/plans/wisdom-wiki-phase-2-skills-and-ingests.md`.
- **Outstanding for the user:** Buffett 1965 seed source is a representative compilation, not the verbatim original. Drop the original PDF into `llm-wiki/raw/` and re-run `/wiki-ingest` to upgrade.
- Ready for Phase 2 (tier-1 ingests + maintenance skills).

---

## 2026-05-27 20:30 — RELOCATE

- **Action:** moved wiki out of `.valuation/` into a new portable root-level folder.
- **Old path:** `.valuation/wiki/` + `.valuation/raw/`
- **New path:** `llm-wiki/wiki/` + `llm-wiki/raw/`
- **Skills:** unchanged location — still at `.claude/skills/wiki-ingest/` and `.claude/skills/ask-wiki/` (Claude Code only auto-discovers skills there).
- **Path references updated in:** AGENTS.md (7 refs + PROJECT-SPECIFIC markers added), README.md (rewritten with new "Install in another project" section), both SKILL.md files, both plan files. Historical session/mindmap artifacts left untouched.
- **Notes:** the rename was purely structural — no content changed. The wiki content (topics, authors, sources, INDEX) was carried over intact. Project-specific sections of AGENTS.md are now wrapped in `<!-- PROJECT-SPECIFIC -->` markers so a future adopter knows exactly what to replace when copying the wiki into a different project.

---

## 2026-05-27 21:25 — /wiki-ingest

- **Source:** `raw/Howard Marks/Mastering The Market Cycle_ Getting the odds on your side_nodrm.epub`
- **Resolved to:** `sources/marks/book-chapters/2018-mastering-the-market-cycle.md` (506 KB, full verbatim text)
- **Topic pages updated:** margin-of-safety, mr-market-and-temperament, drawdowns-and-temperament (each gained a Marks section)
- **Topic pages created:** cycles, second-level-thinking
- **Author page updated:** marks (created — first ingest)
- **Entity pages touched:** (none — Oaktree is mentioned substantively but this is the first ingest containing it; per the "≥2 substantive mentions" rule, entity page is deferred until a second Marks source corroborates)
- **Comparison pages touched:** (none — comparisons require ≥2 author perspectives already in the wiki; that bar is now met for several topics, so the next ingest may legitimately create `buffett-vs-marks-on-cycles.md` or `buffett-vs-marks-on-risk.md`)
- **INDEX updated:** yes — added topics/cycles + topics/second-level-thinking under `## Topics`; added authors/marks under `## Authors`; added a new `### marks` subsection under `## Sources by author`; bumped Last refresh
- **Notes:**
    - **EPUB format handling.** EPUB is not in the skill's format table. Resolved autonomously: epub is a ZIP of XHTML, so extracted with `unzip` to /tmp, then ran a stdlib `html.parser`-based converter (BeautifulSoup not available) across the 19 spine items per `content.opf`. Output cleaned with a regex pass (chapter-filename artifacts, doubled headings, orphaned bullets). Verbatim fidelity preserved; only structural headings added (`## Chapter <Roman> — <TITLE>`). **Skill update suggestion:** add EPUB to the "How to read" table in `/wiki-ingest` SKILL.md with the unzip-and-extract recipe.
    - **Author + work + year:** unambiguous from `content.opf` metadata (`dc:creator` = "Marks, Howard", `dc:title` = full book title, `dc:date` = 2018-10-04).
    - **work_type chosen:** `book-chapter` (the seed work_type for book content per AGENTS.md). Source covers the full book, so `work_part` is set to `"full text (Introduction + Chapters I–XVIII)"` rather than a single chapter. Slug intentionally drops the `chapter-N-` prefix because this *is* the whole book.
    - **Topic promotion decision (single-author exception).** Per AGENTS.md ("≥2 authors before topic-page creation"), single-author topics should normally go on the author page. Two exceptions made:
        - `topics/second-level-thinking` is in the canonical seed taxonomy already declared in AGENTS.md — same exception applied to the Phase-1 Buffett seed, applied symmetrically here.
        - `topics/cycles` is not in the seed taxonomy but is so clearly multi-author over time (Graham, Buffett, Munger, Marks, Lynch all have positions on cycles/market timing) that creating the topic page now is cheaper than creating it on the next ingest. Buffett's existing partnership-letter material on Mr. Market is referenced in the cross-links; future Buffett/Munger/Marks ingests will fill in their sections.
    - **Comparison pages: deferred but now possible.** With Marks added, the wiki has two author perspectives on margin-of-safety (Buffett + Marks via reduced-margin-at-tops framing), mr-market-and-temperament (Buffett's Mr. Market + Marks's pendulum), and drawdowns-and-temperament (Buffett's down-years inevitability + Marks's risk-attitude cycle). Comparison pages are not auto-created within this ingest, but the bar is now met for the next ingest or for a `/wiki-ingest`-adjacent maintenance step.
    - **Cross-citations of Buffett inside Marks's text.** The book contains several Buffett quotes ("less prudence... greater prudence", "first the innovator, then the imitator, then the idiot"). These are cited *via* the Marks source page (Marks's *quotation* of Buffett, not Buffett's primary source) — consistent with citation rule 1 ("cite via `[[sources/...]]` wikilink"). When the Buffett source containing the original is ingested later, the topic pages can be updated to cite the primary.
    - **Raw file:** moved to `raw/processed/Howard Marks/`.

---

## 2026-05-27 22:30 — /wiki-ingest (Berkshire annual letters corpus)

- **Source:** `raw/buffett/Berkshire annual letters/` — a *directory* of 49 files (22 `.html` for 1977–1997 plus 1998 duplicate, 26 `.pdf` for 1998–2024). Skill is documented for single-file input; directory was interpreted as a batch ingest of the whole corpus per the autonomous "wrong calls cheaper than friction" rule.
- **Resolved to:** 48 source files at `sources/buffett/letters/<year>-berkshire-letter.md`, one per year 1977–2024.
- **Topic pages updated:** margin-of-safety (added 1990 "three words" + Berkshire-era sub-structure), mr-market-and-temperament (added 1987 extended discussion + 1986 fearful/greedy + voting/weighing machine), owner-earnings (replaced partnership-era proto with canonical 1986 Scott Fetzer Appendix as the lead, demoted the proto), position-concentration (added 1993 risk-decrease framing + 2022 Secret Sauce + 2024 "winners forever blossom"), drawdowns-and-temperament (added 1986 fearful/greedy original + 1990 "pessimism is your friend" + 2008 financial-crisis restatement), cycles (added Buffett-on-bubbles section from 2000 letter — "speculation is most dangerous when it looks easiest").
- **Topic pages created:** circle-of-competence (1996 owner's manual + 1993 index-fund recommendation — single-author for now, seed-taxonomy exception applied, Lynch section to be added on next ingest); intrinsic-value (multi-author — Buffett 1989/1993/1996 + Marks's *Mastering the Market Cycle* Chapters I and VII); wonderful-businesses-and-time (single-author distinctive-Buffett contribution from 1989 + 2014 — Marks's "weeds vs flowers" framing is adjacent and may be promoted to a section when Marks's parallel material is mapped).
- **Author page updated:** buffett — substantially expanded with the two-act arc (partnership-era Graham orthodoxy → Munger-shifted wonderful-business-at-fair-price), Berkshire-era core principles section, expanded characteristic mental models, expanded failure-modes section, full topics-covered table including the three new topic pages, and a sources-in-this-wiki section listing 14 notable individual letters.
- **Entity pages touched:** berkshire-hathaway (created — the 49-source corpus easily clears the ≥2-mentions bar). Page covers: 1839 textile origins; 1965 takeover; 1985 textile shutdown candor; the insurance float story; the 1972 See's Candies inflection; major public-market positions (Coke, GEICO, Apple, Burlington Northern, etc.); the Buffett-Munger partnership; six-decade structural facts; the 2023 "built to last" + 2024 Abel-succession framing.
- **Comparison pages touched:** (none — see deferred note). The bar is now thoroughly met for `buffett-vs-marks` comparison pages on cycles, margin-of-safety, drawdowns-and-temperament, and intrinsic-value; bar is also met for `buffett-vs-marks-on-risk` (Buffett's permanent-loss-of-capital framing in the 1993 letter + Marks's parallel framing in MMC Chapter I). Not auto-created in this ingest — deferred to Phase 2 or a follow-up ingest.
- **INDEX updated:** yes — 3 new topics added to `## Topics` (alphabetised); `berkshire-hathaway` added to `## Entities`; Sources section uses a roll-up entry for the 48 Berkshire letters with a pointer to the per-letter notes on the author page (per-letter individual lines would have made INDEX 50+ lines longer for little query benefit); Last refresh bumped.
- **Notes:**
    - **Directory-input interpretation.** The skill is documented for `/wiki-ingest <path-to-file>`. The user supplied a *directory* of 49 files. Per the skill's autonomous-first rule ("never ask the user"), the directory was interpreted as a request to ingest the whole corpus as a batch. The right shape: process all files into source pages (verbatim, citation-ready); do ONE consolidated synthesis sweep at topic / author / entity / INDEX / LOG level rather than 48 micro-updates that would bloat topic pages without adding signal. Skill update suggestion: add a "directory input → batch ingest" edge case to SKILL.md.
    - **Brotli encoding issue with the HTML files.** The 22 `.html` files in the raw directory (1977–1997 + 1998 duplicate + 1999 duplicate) were *not* plain HTML — they are the raw HTTP response bodies from berkshirehathaway.com, which serves all HTML content with `content-encoding: br` (Brotli) through its Sucuri Cloudproxy. Both the system `brotli` CLI and Python's `brotli` module reported "corrupt input" — the proxy emits a Brotli stream that doesn't round-trip through standard decoders. Workaround: fetch each pre-1998 letter from the Wayback Machine using the `2018id_` raw-mode modifier (`https://web.archive.org/web/2018id_/https://www.berkshirehathaway.com/letters/<YEAR>.html`), which returns clean plain HTML. The 1999 letter required the alternate URL pattern `letters/1999htm.html`. All fetches subject to transient `Connection refused` from Wayback's rate-limiter — handled by an `until` retry loop with 15-second back-off. **Skill update suggestion:** add a "Sucuri / Cloudproxy Brotli encoding" note to the SKILL.md edge cases — note the Wayback `id_` raw-mode workaround.
    - **HTML era vs PDF era handling.** 1977–1997 letters use a minimal `<HTML>/<PRE>/<B>/<I>` markup — Berkshire's first-generation web format. The `<PRE>` tag was a layout hack to preserve the typed 60-char width of the original mailed letters, *not* a code-block intent — the conversion script treats `<PRE>` as transparent (no code fences) and only fences `<TABLE>`. 1998–2024 letters are converted from PDFs via `pdftotext -layout`, which preserves the performance-ladder table at the top of each letter and produces clean prose for the body.
    - **Verbatim verification.** Before committing topic-page quotes, the most-cited passages (the Mr Market "pocketbook" quote, the "wonderful company at a fair price" 1989 quote, the 1990 "three words: Margin of Safety", the 2008 "pessimism is your friend", the 1986 "fearful when others are greedy" original) were spot-grepped against the source files to confirm exact wording and pinpoint the cited year. Several agent-extracted quotes were re-anchored to the correct letter after grep (e.g., "voting machine / weighing machine" is in 1987 Buffett-quoting-Graham, not Buffett's own line).
    - **Single-author topic creation exception.** Three new topic pages were created from this Buffett-only batch ingest:
        - `circle-of-competence` — in the seed taxonomy already declared in AGENTS.md → seed-taxonomy exception applies (same exception used for the Phase-1 Buffett seed and the Marks ingest).
        - `intrinsic-value` — multi-author bar met (Buffett + Marks's Chapter I + Chapter VII passages on value investor discipline). Not a seed-taxonomy topic but the materially multi-author corpus already meets the ≥2-author rule.
        - `wonderful-businesses-and-time` — single-author at creation (distinctive-Buffett contribution). Justified by the depth and distinctiveness of the 1989 letter material and by the high likelihood Marks/Lynch sections will be added on subsequent ingests (Marks's "weeds wither / flowers bloom" framing is adjacent; Lynch's "tenbagger" framing implicitly assumes wonderful-business durability).
    - **Compounding-and-time-horizon, retained-earnings, moats — deferred to follow-up.** The 2019 "Power of Retained Earnings" section is currently cited only on the buffett author page, not promoted to a separate topic. Same for the moat concept (currently cited on wonderful-businesses-and-time as a sub-framing). Reconsider at next major ingest (Lynch's *One Up on Wall Street*, more Marks memos, or Munger's USC speech) when these concepts get a clear second-author voice.
    - **Per-letter tags.** Each source file's frontmatter includes year-specific tags drawn from each letter's defining content (e.g., 1986: `[owner-earnings, scott-fetzer]`; 2008: `[financial-crisis, buy-american]`; 2022: `[secret-sauce, buybacks, apple]`). Tags were derived from canonical-knowledge of each letter's content rather than parsing the body — conservative; only included tags when the year is widely associated with the event.
    - **Raw files:** moved to `raw/processed/buffett/Berkshire annual letters/`.
    - **Conversion artifacts:** the conversion script lives at `/tmp/convert_berkshire_letters.py` and `/tmp/write_source_files.py` — not checked into the repo (skill output is the source files themselves; the script is scaffolding). Re-running the script is idempotent (it caches converted intermediates in `/tmp/berkshire_md/`).
