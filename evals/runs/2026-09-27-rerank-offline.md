# 2026-09-27 - reranking a pool of pages, offline

**What:** every passage from every page opened for an angle, pooled and
ranked against that angle, then checked for where the passage the run went on
to quote lands. Seven runs from 24 Sep (banks, Postgres, accountancy), 31
angles, a median of 81 passages a pool and at most 368. No new eval run.

**Pages re-opened, not reused.** The machine restarted on 26 Sep and `/tmp`
was cleared, taking the saved pages with it. The 154 page links in those
runs' logs were re-opened with `fetch.py` (free) on 27 Sep: 135 opened, 19 were
blocked or unreadable and were left out rather than paid for again. A quoted
passage counts only if the quote is still on the page today.

| Scorer | Top 5 | Top 10 | Top 20 | Top 40 | Survives the capped digest (40, cap 3) |
|---|---|---|---|---|---|
| Term match (free) | 74% | 93% | 100% | 100% | 28 of 31 |
| Jev | 76% | 86% | 93% | 100% | 25 of 30 |
| **Average of both** | **86%** | 93% | 100% | 100% | 27 of 30 |
| Random pick | | 21% | | | |

**Decisions.** `rerank.pool_scores` uses the average when a Jev key is
available and the term match otherwise. The digest stays at 40 passages, twice
what these pools needed.

**Why the term match is strong here.** It scores against the search phrasings,
and those are the words that surfaced the pages. `gather.py` has the same
advantage by design, since its terms are the plan's phrasings. Jev saw only the
angle.

**The cap.** In 3 of 31 angles a quoted passage was cut by the three-per-party
cap. None of these pools had a subject, so none had the exemption that protects
a round-2 subject's own pages; a cut passage still appears in the overflow
list.
