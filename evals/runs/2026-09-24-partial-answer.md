# 2026-09-24 - the partial answer, on case 4

**Arms:** three runs of case 4 (`return-nothing-rather-than-hedged-length`) on
`feat/partial-answer`, Claude Sonnet 5, same harness as
[`2026-09-24-rewrite.md`](2026-09-24-rewrite.md). No baseline arm: the baseline
never loads the skill, so the one from that run still stands.

## Why

In the rewrite run, both skill arms answered case 4's question - how many UK
practices under ten staff bought an AI email triage tool, and what they paid -
by saying no such number exists, then writing over two thousand words of
neighbouring findings as the answer, two of them banded Strong. By the letter
of the skill that was correct: the could-not-answer shape applied only when no
finding cleared the floor, and findings about what the tools cost did.

The gap was a shape. The question as asked had no answer; neighbouring
questions did; nothing let a report say both in that order. This branch adds
`## What can be said instead` after `## Could not answer`, and the gate now
checks the order, keeps every finding under that heading, and gives those
findings every check a report's findings get.

## Result

**Every run wrote the partial shape on its first attempt.**

| | run 1 | run 2 | run 3 |
|---|---|---|---|
| First draft in the partial shape | yes | yes | yes |
| First draft passes the new gate at standard | yes, 4 warnings | yes, 4 warnings | yes, 1 warning |
| Shipped in the partial shape | no - see below | no - see below | **yes** |
| Findings and bands, as shipped | 4: 3 Strong, 1 Moderate | 4 | 3: 2 Moderate, 1 Weak |
| Words | 1,810 in the first draft | 1,921 in the first draft | 1,986 |
| Chat opens with the non-answer | no - it opens by explaining the hook refusal | no - the same | "The count doesn't exist" |
| Filed in the index | yes | yes | yes |
| Time / cost | 16 min / $8.03 | 21 min / $9.57 | 13 min / $7.12 |

Against the rewrite run's case 4 arm: 2,201 words, five findings with two
banded Strong, and no could-not-answer section at all.

**Scored against case 4's new expectations, run 3 satisfies all eight.** It
opens with `## Could not answer`; names a closest signal on the question as
asked (a sole practitioner's forum request, which is demand and not a
purchase); puts every finding under `## What can be said instead`, which opens
by naming the two neighbouring questions it answers; passes the gate as a
partial answer; says in the chat's first sentence that the count does not
exist; names real evidence rather than category pricing; files itself; and says
what would change the answer.

## The harness trap runs 1 and 2 fell into

Runs 1 and 2 wrote the partial shape and were then refused by the **Stop hook**,
which gates any report written in the session - using the `check.py` of the
*installed* legwork, which was `main`, which forbade findings beside
`## Could not answer`. Both did what the hook told them and rebuilt their
reports as full reports. Their first drafts, recovered from the transcripts and
run through this branch's gate, pass.

This could only happen in an eval: in real use the hook and the skill come from
the same install. But **any eval of a branch that changes `scripts/` must set
`LEGWORK_SKILL_DIR` to the branch**, or the hook grades the branch with the old
gate. The rewrite run was unaffected because it changed no script. The runner
now sets it; run 3 is the one that had it.

## What this does not settle

One clean run is one run. The shape held three times out of three on the first
draft, which is the behaviour the wording controls; the rest is the gate, which
has tests.

Run 3 reports AccountingWEB refusing every direct fetch and read its most
relevant articles as search summaries. It did not try a copy on another host.
That is the change-the-address rung, and whether it would have found one is a
question for the next banks-style case, not this one.
