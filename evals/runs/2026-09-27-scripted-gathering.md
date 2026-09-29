# 2026-09-27 - scripted gathering against `main`

*The branch was closed unmerged on 29 Sep 2026, after grading against answer keys
([2026-09-28-facts-against-answer-keys.md](2026-09-28-facts-against-answer-keys.md)).
The costs below held; the reach did not come with accuracy.*

**What:** the scripted-gathering branch (`gather.py`, no retrieval subagents,
no WebSearch) against `main` at 9cb872e, Sonnet 5, headless, one run per arm.
Five prompts: banks (cases 1 and 6), Postgres, plugin (reuse of an earlier
run), accountancy (case 4, no answer exists) and campervan. A TypeSafe key was
on the machine for both arms, so both reranked with Jev.

**Pass test, from the spec:** Claude cost at most half of `main`'s, reach and
confidence at least `main`'s, and no report names anything without a source.

## Result

| Case | Claude cost, `main` → branch | Minutes | Hosts opened | Hosts cited | Findings by band |
|---|---|---|---|---|---|
| banks | $8.08 → **$2.60** (32%) | 14.7 → 21.9 | 21 → 172 | 17 → 19 | 2 Strong 1 Moderate → **4 Strong** 1 Moderate |
| Postgres | $7.25 → **$2.67** (37%) | 13.4 → 20.2 | 18 → 207 | 15 → 25 | 2 Strong 2 Moderate → **4 Strong** 2 Moderate |
| plugin | $1.06 → $0.30 and $1.82 | 3.9 → 1.1 and 11.3 | reuse | reuse | see below |
| accountancy | $1.78 → $1.37 (77%) | 7.8 → 16.8 | 4 → 195 | 5 → 25 | 3 Moderate → 2 Strong 2 Moderate; both "could not answer" |
| campervan | $2.11 → $1.30 (62%) | 8.0 → 20.1 | 7 → 90 | 6 → 13 | 2 Strong 1 Moderate → 1 Strong 3 Moderate |
| **All five** | **$20.28 → $8.99 (44%)** | | | | |

The plugin row counts the mean of the branch's two runs in the total.

**Cost: passes in total, not in every case.** The two big questions came in
at a third. The two small ones did not reach half, because `main` researched
them thinly - four and seven sites opened - and there was little to save. On
those the branch opened fifteen to fifty times as many sites for less money.

**Reach: passes everywhere.** More sites opened in every case, more cited in
every case.

**Confidence: passes in four cases of five.** More Strong findings in banks,
Postgres and accountancy. Campervan had one Strong to `main`'s two.

**No names from memory: passes.** Every round-1 phrasing across the five
plans named nothing. Every round-2 subject carried `from` ids, and each was
checked against the saved passages: every subject is named in at least one of
its ids, and no id is missing.

**Gate:** every report passed at standard, with fewer warnings than `main`'s.

**Time: worse.** The branch took 17 to 22 minutes a question to `main`'s 8 to
15, most of it in two six-minute `gather.py` rounds. Nothing in the pass test
covers time.

**Plugin.** In its first run the branch answered from the July report and only
warned that it might be stale. `main` refreshed and found that the submission
form had moved, and now needs a paid plan. The branch's second run refreshed
and found the same. Both arms follow the same rule for reusing a run, so
this was run-to-run variance, not the branch.

## What the eval found and fixed on the way

Four rounds, each version kept under `~/legwork-evals/20260927/eval/gather-v*`:

1. **A single refusal from Bright Data stopped the run.** Four sessions on one
   account hit its rate limit, `bd_search.py` maps that to exit 2, and
   `gather.py` aborted - once throwing away 286 opened pages. Now a refused
   call is logged, the digest counts it, and the run stops only when every
   search failed.
2. **Local Bing answered with results for the first word only.** "managed
   postgres pricing comparison" returned dictionary entries for "managed".
   Ten results is not a refusal, so the fallback never fired and both agents
   searched by hand. Local results must now carry the query's words, or the
   search goes to Bright Data. On this machine that sends almost every search
   there.
3. **Round 1 overran the ten-minute command limit.** Jev scored every one of
   2,000+ passages an angle, and names were counted with one regex per name
   over the pool (24 to 44 seconds an angle). Jev now reads the term match's
   top 200, names are counted once, and the time limit caps every step of
   opening a page. Round 1 on the banks plan now takes about six minutes, and
   its digest is 98 KB rather than 139 KB.
4. **Postgres cost 55%** in the third round: eleven single quote calls and
   twelve edits correcting URLs the agent had rebuilt from memory, each
   re-reading 200,000 tokens. `quote` now takes several sources in one call,
   and every digest line shows the passage's URL. The rerun cost 37%.

Banks, accountancy and campervan ran before fix 4. Postgres and the second
plugin run ran after it.
