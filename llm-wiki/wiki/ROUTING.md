# ROUTING.md — DEFERRED in Phase 1

This file is a **placeholder**, intentionally empty of rules.

## What `ROUTING.md` is for

In larger wikis (synthadoc, OmegaWiki), `ROUTING.md` encodes query → page-subset patterns so the read loop can skip `INDEX.md` for common query types. Example rule:

> Question about "drawdowns", "panic", "1973-74", "2008", "cycles" → start at `[[topics/drawdowns-and-temperament]]` and `[[topics/mr-market-and-temperament]]`; consult `[[authors/marks]]` next.

The pattern is an optimisation, not a correctness layer — without `ROUTING.md`, `INDEX.md` is enough.

## Why it is DEFERRED

In Phase 1 the wiki has at most a handful of pages. The agent reading `INDEX.md` in full is faster than maintaining routing rules. Premature routing rules become stale faster than they help.

## When to activate

Add routing rules here only when **both** are true:

1. The wiki contains > ~100 pages and `INDEX.md` is itself becoming slow to scan, AND
2. There are observable, repeatable query-type → page-subset patterns from real usage (not anticipated patterns).

Until then: leave this file as-is. `/ask-wiki` will read it, find no rules, and fall back to `INDEX.md` navigation.

## Reference

Session 1, section 14 — `.valuation/Sessions/27-05-Karpathy-llm-wiki-2/session-1.md`.
