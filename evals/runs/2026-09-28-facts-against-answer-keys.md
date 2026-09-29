# 2026-09-28 - the facts version against answer keys

**What:** the same test as 27 Sep (`2026-09-27-quality-against-answer-keys.md`),
same answer keys, fresh blind grading. `main`'s nine reports were graded again
beside nine from the branch at dc72cb5 to 66983de. What changed on the branch:
a facts file with an own-site standard for facts about an entity's own offer
and two independent sources for any other fact, price checks against the
entity's own site, own-site searches in round 2, separate time budgets for
searching and opening. Two runs outran the command limit before the budgets
and were rerun on 66983de; the other seven ran on dc72cb5. Scores:
`~/legwork-evals/20260928/grading/`.

| | banks, `main` → branch | Postgres, `main` → branch | campervan, `main` → branch |
|---|---|---|---|
| Core covered (average) | 12.7 → 13.0 of 16, extras 0 → 7 | 6.0 → **9.0** of 9 | 1.3 → 1.7 of 3 |
| Facts correct | 13 → 20 | 11 → 18 | 3 → 3 |
| Facts wrong | 2 → 5 | 4 → 9 | 1 → 1 |
| Scope errors | 0 → 5 | - | 1 → 2 |
| Other errors | 4 → 0 | 9 → 17 | 4 → 1 |
| Sound recommendation | - | 1 → **3** of 3 | - |
| Claude cost, three runs | $22.79 → $11.24 (49%) | $16.81 → $18.55 (110%) | $9.03 → $9.71 (108%) |

Across all nine: **81% of `main`'s cost**, and 21 to 47 minutes a question
against 8 to 16.

**Against the 27 Sep branch:** scope errors fell from 10 to 5 (banks) and 6
to 2 (campervan). Wrong facts did not fall (banks 6 to 5, Postgres 7 to 9),
and cost rose from 65% to 81% of `main`, most of it the facts step and the
wider round 2.

**Verdict: does not meet the bar set for merging** - accuracy at least
`main`'s and cost at most 65% of it. The branch states more correct facts
than `main`, covers every core Postgres provider every time and recommends
soundly every time, but it also states more wrong ones: 15 wrong facts and 7
scope errors across the nine, against 7 and 1.

**What the wrong facts are:** mostly an own-offer fact quoted from the right
site but from a stale or neighbouring page - Render's retired $7 price,
"no free tier" for Azure, Nationwide as free sign-up - which an own-site
quote does not catch, because the entity's own site says it somewhere.
