# 2026-09-25 - whole-page reads, optional Jev ranking, and logging by script

**Arms:** two live banks runs on `feat/fetch-outline` (Claude Sonnet 5), one
with `TYPESAFE_API_KEY` set and one without; three feasibility tests of
TypeSafe's Jev model on the 24 Sep logs; and a replay of the live runs'
subagent replies through the new logging script. Two further live runs were
started and stopped four minutes in by the plan's usage limit, and produced
nothing. The scripts are in `/home/devops/legwork-evals/20260925/` on the
machine that ran them.

## Why

Across the 24 Sep runs, subagents opened whole saved pages 81 times, about
9,700 characters each and 785,000 in all, and everything read stays in the
subagent's context for the rest of its turns. Of the 79 traced, 52 came
straight after a `fetch.py --find` that matched nothing: the agent's guess at a
term was not on the page, so it opened the page to look.

## What Jev is good for, measured before anything was built

Jev is TypeSafe's System One model: typed questions over supplied evidence,
answers with probabilities, about $0.042 per million tokens.

| Asked to judge | Result | Cost |
|---|---|---|
| Whole pages a subagent had opened, against its angle | Weak: cited pages averaged 1.97 on a 0-3 scale, uncited 1.63; keeping only 2 and above would drop 44 of 91 cited pages | $0.007 for 113 |
| Search results from title and link only, 1,294 of them | AUC 0.73. Dropping only "unrelated" opens 78% and keeps 95% of what the run cited; opening the top half keeps 80%, the top 30% keeps 57% | $0.009 |
| The same, with Bright Data snippets, 204 results | No gain: AUC 0.83 on titles, 0.80 with snippets, on only 14 cited results. A threshold that looked good there (keep 13 of 14) kept 78% on the larger set | 40 SERP calls, cents |
| **Passages inside a page**, 40 pages with a quote checked against the page | **The quoted passage was in Jev's top three 75% of the time, against 26% for a random pick; top five, 85%** | $0.007 for 40 |

**Built:** passage ranking, and only when `--find` missed. Ranking every page
would add three passages to every fetch, which on the 24 Sep runs is more text
than the whole-page reads it replaces.

**Not built:** searching wider and letting Jev choose what to open. Snippets
did not help, the one safe cut removes only a fifth of results, and any tighter
cut loses between a tenth and a half of the evidence the runs relied on. Worth
revisiting if a later Jev model, or a different question wording, lifts the
title-only AUC well above 0.73 on a set this size.

## What changed

- `fetch.py` records the page's headings with every fetch and prints them only
  when `--find` found nothing. `--saved FILE` searches a page already on disk
  again, with no network.
- `fetch.py --relevant QUESTION`, with `TYPESAFE_API_KEY` set and `--find`
  missed, prints the three passages Jev ranks highest. Without the key it says
  so and carries on. A failed call never fails a fetch.
- `sources.py log-returns` logs a subagent's whole reply - every JSON object in
  it, wherever it sits - with the page text attached wherever `fetch_json`
  points at one, refusals as blocked and search results as leads.
- The gate flags `fetch.py` rows whose quotes were never checked, since
  `fetch.py` always keeps the text: a warning at standard, an error at deep.

## Live runs

| | 24 Sep banks runs | no key | with Jev |
|---|---|---|---|
| Whole-page reads | 13, 2, 6 | 11 | **0** |
| Jev passages returned | - | - | 33 |
| Saved-page searches | - | 11 | 3 |
| Quotes checked against the page | 19, 12, 17 | **0** | **0** |
| Time / cost | 11-13 min / $4.09-5.70 | 11 min / $5.94 | 15 min / $6.50 |

**Jev stopped the whole-page reads.** The outline alone did not: that run
searched saved pages eleven times and still opened eleven whole.

**Both runs checked no quotes, and it was not this change.** Their subagents
returned `fetch_json` as the brief asks, but the orchestrator logged the
returns with a loop it wrote itself and left out `--from-fetch`, so every row
went in without its page text. The gate passed both. Two of the last five runs
lost their quote checks this way. `log-returns` and the gate check are the
answer.

## The replay

The real subagent replies from those two runs, fed through `log-returns`:

| Run | Orchestrator's own loop | `log-returns` |
|---|---|---|
| with Jev | 45 rows, 0 quotes checked | 41 rows, 30 with page text, 22 checked and found, 7 not found |
| no key | 23 rows, 0 quotes checked | 33 rows, 21 with page text, 15 checked and found, 5 not found |

The gate check, replayed over the 24 and 25 Sep reports, flags the two runs
above (30 and 14 rows), the pre-rewrite banks run (24) and three runs with
partial losses (10, 6 and 2), and is silent on every run that logged properly.

## Not yet shown

Whether an orchestrator calls `log-returns` rather than writing its own loop
needs a live run, and the two started for it were stopped by the usage limit.
If one does not, the gate check says so, and at deep the run cannot pass.
