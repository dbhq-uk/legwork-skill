# 2026-09-24 - a matrix row must rest on a page somebody opened

**Arms:** today's eleven skill-arm reports replayed through the new gate, and
one live run of the banks prompt (cases 1 and 6) on `feat/matrix-snippet-rows`,
Claude Sonnet 5, with `LEGWORK_SKILL_DIR` pointed at the branch so the Stop hook
graded with the new gate. Same harness as
[`2026-09-24-rewrite.md`](2026-09-24-rewrite.md).

## Why

In the rewrite run, the banks report grew its comparison matrix from twelve rows
to sixteen, and three of the new rows - Tide, Allica, Metro - rested on nothing
but search results. The gate said so, as a warning, and at standard a warning
does not stop a run. A cell reads as settled, and a reader cannot tell a
snippet from a page, so the matrix is where that warning matters most.

The change: at standard and deep, a matrix row whose every citation is a search
result or a page absent from the log is an error. A row that cites one opened
page beside a snippet passes. Quick is not asked. Snippet citations in prose
stay a warning at standard, as before.

## Replay

Every skill-arm report from today, gated at its own level by `main` and by the
branch:

| Report | `main` | branch |
|---|---|---|
| rewrite, banks | pass | **fail: Tide, Allica, Metro** |
| every other report (ten) | pass | pass |

It catches the three rows it was built for and nothing else.

## Live run

**The rule changed what the run did.** The first gate run failed four rows -
HSBC, Starling, Revolut and TSB - each resting on a search result. The run took
all four to `bd_search.py -m render`, opened each bank's own developer pages,
and rewrote the rows to cite them. One of those pages changed the answer: TSB's
own FAQ requires FCA registration and production eIDAS certificates before it
will accept even a sandbox application, which made TSB the exception the
report's title now leads with - "eight of nine don't require FCA authorisation".
Under `main` that row would have shipped on a snippet and the headline would
have been wrong by one bank.

| | |
|---|---|
| Time / cost | 14 min / $7.55 |
| Log rows / opened / blocked | 36 / 21 / 3 |
| Pages logged `via brightdata` | **4** - both earlier banks runs logged 0, having rendered six and two |
| Calls to the non-existent `-m serp` | **0** |
| Gate at standard | pass; prose warnings only |

The last two rows close action 2 of the rewrite run: the wording fixes that
landed after its arms ran now hold on a real run.

## What it found that this does not fix

**The orchestrator paraphrased the subagent brief and lost `fetch.py`.** The
brief's step 2 is a command - `python3 {SKILL_DIR}/scripts/fetch.py "<url>"
--find "<term>"` - and this run's orchestrator rewrote it as "using a fetch tool
or WebFetch". Its nine subagents, on Haiku as the brief allows for narrow
angles, made 103 WebFetch calls and 4 `fetch.py` calls, so the log carries page
text on 1 row of 36 and no quote could be checked against a page. The rewrite
run's orchestrator pasted the command and its subagents used `fetch.py` 45
times. The difference is whether the orchestrator paraphrases, which is exactly
what a written instruction cannot guarantee.

Eight prose citations in this report rest on search results. That is the
standard-level warning working as designed, not a defect in this change.
