# Legwork eval run - 6 September 2026

Cases 5 and 6, both arms, writer model Claude Sonnet. Skill at `main`,
commit `2b737a2`, the first run after the search pipeline landed.

An earlier attempt the same morning was killed by a rate limit before any arm
produced a deliverable; it is recorded separately in
[`2026-09-06-search-pipeline-aborted.md`](2026-09-06-search-pipeline-aborted.md)
because one of its logs answered a question this run then answered properly.

## Headline

**Both cases discriminate, and they discriminate on reach rather than on
honesty.** Both baselines were careful, cited their sources and named their own
gaps, exactly as the August run found. What separates the arms is how much of
the primary evidence each one actually got its hands on.

| | case 5 baseline | case 5 skill | case 6 baseline | case 6 skill |
|---|---|---|---|---|
| Searches | 11 | 11 | 19 | 32 recorded against sources |
| Retrievals logged | none | 10 | none | 40 |
| Pages opened | 9 of 12 attempts | 6 | 1 of 4 attempts | 33 |
| Pages that refused | 3 | 2, recorded as blocked | 3, in prose only | 3, recorded as blocked |
| Cited from a snippet | not knowable | 0 | 3 of the most important rows | 0 cited |
| Gate | n/a | pass, second attempt | n/a | pass, second attempt |
| Filed for reuse | no | yes | no | yes |
| Words | 1,311 | 2,025 | 1,924 | 4,033 |

The case 6 comparison is the sharp one. The baseline made **19 searches and 4
fetch attempts, 3 of which failed**, so its entries for Barclays, NatWest's Bank
of APIs and HSBC rest on search-engine summaries of pages it never read. The
skill arm logged **40 retrievals and opened 33 pages**, and its 14-row matrix has
no unknown cells. This is the same 19-to-5 ratio the August baseline showed, on
the same institutions, and it is the gap the page ladder was built to close.

## The two questions this run was called to settle

**Is the `fetch.py` rung actually used, or is it prose?** Used.

| Arm | `direct` | `webfetch` | `websearch` |
|---|---|---|---|
| case 5 skill | 4 | 5 | 0 |
| case 6 skill | 37 | 0 | 3 |

The aborted attempt had raised this: its ten surviving rows were all `webfetch`,
which suggested agents might skip the first rung. On a completed run they do not.
Case 6 went through `fetch.py` for 37 of 40 retrievals.

**Does the snippet rule bite without producing noise?** Yes, and the best
evidence is a case where it correctly stayed silent.

Santander's live developer portal refused `fetch.py` with a 403. The agent had
the page as a search snippet and could have cited it - that is precisely the
2026-08-16 failure. Instead it went to the Wayback rung, opened the archived
snapshot, and put *the archive URL* in the bibliography. The citation therefore
points at a page it genuinely read, the gate has nothing to complain about, and
the reader can see exactly what was and was not reachable.

Both skill arms produced a receipt line whose opened count matches what
`sources.py receipt` prints from the log: `6 opened` and `33 opened`. Neither
was counted by hand.

## What went wrong, and it is not nothing

**The paid rungs were never reached.** Bright Data is authenticated on this
machine, its zones are live, and `0 via Bright Data` appears in both receipts.
Case 5 hit Campal's kit pricing, was refused on `fetch.py` *and* `WebFetch`, and
stopped there rather than escalating to `-m scrape`. Case 6 met three
client-rendered portals - NatWest, Starling, Bank of Ireland UK - that returned
title-only shells, which is exactly what `-m render` exists for, and recorded
them as unreachable instead.

Both are honest outcomes and both are recorded rather than papered over, so the
gate is satisfied and the reader is not misled. But a ladder whose top three
rungs go unclimbed is, for those rungs, still prose. Two possible causes, and
this run cannot separate them: the escalation is written as a table in
`SKILL.md` rather than as a step in the Phase 2 playbook, and nothing checks
that a blocked row was ever followed by an attempt on a higher rung.

**The gate failed first on both arms, for a trivial reason.** Case 5 failed on a
bibliography numbering gap it created by trimming unused entries; case 6 on
three warnings including an unfetched citation. Both fixed and passed on the
second attempt, which is the loop working - but the first failure being clerical
in both arms is worth watching.

**Only one platform rung was used at all.** Two `web.archive.org` retrievals,
nothing from Hacker News, GitHub, Stack Exchange, npm or Google News. Case 6 is a
capability question about vendor documentation, so `vendor_docs` on 33 of 40 rows
is the right shape and no community source was needed. Case 5 is a price and
demand question where forum evidence would have helped, and it used one forum
page found by ordinary search rather than through `platforms.py`. Not a defect;
an unexercised capability, and the next case written should exercise it.

## Scoring

**Case 5 - open the page rather than citing the snippet.**

| Expectation | Result |
|---|---|
| Opens the pages it cites rather than quoting snippets | satisfied - 0 snippet-only rows |
| Uses `fetch.py` before `WebFetch`, records page text | satisfied - 4 of 9 opens via `direct` |
| Records the query that surfaced each source | satisfied - 6 queries across 10 rows |
| Receipt's opened count matches `sources.py receipt` | satisfied - both say 6 |
| Quotes verified against page text rather than recalled | satisfied where page text existed |
| Passes `check.py` at the announced level | satisfied - second attempt |
| Reaches a supplier's own page for a price | satisfied - EVO's own page, GBP 9,453 |

**Verdict: pass.** The failure this case reproduces did not recur.

**Case 6 - get through a blocked primary source.**

| Expectation | Result |
|---|---|
| Logs a page that would not open with `--status blocked` | satisfied - 3 blocked rows |
| Tries the next rung after a block, and logs which succeeded | **partly** - the archive rung yes, the paid rungs never |
| Uses `platforms.py` where the answer is a record | satisfied - Wayback, twice |
| Leaves `[unknown]` rather than filling from a snippet | not exercised - 0 unknown cells in 56 |
| The receipt reports the blocked count | satisfied |
| Names the specific unreachable sources in Limitations | satisfied - all three client-rendered portals named |

**Verdict: pass, with the escalation row half-satisfied.** That row is the
finding of this run.

## Actions

1. **Move the escalation out of the ladder table and into the Phase 2 playbook
   as a step.** A blocked page is currently a table lookup; it should be an
   instruction in the sequence the agent is already following.
2. **Consider a gate check for an unfollowed block.** A `blocked` row whose URL
   never appears again on a higher rung is visible in the log and nothing looks
   at it. This is the same argument that produced the snippet rule: the record
   exists, so the check can be mechanical rather than exhortative.
3. **Write a case that needs a community or registry source**, so the rest of
   `platforms.py` is exercised rather than assumed.
4. Rewrite case 6's `[unknown]` expectation. A run that fills every cell has not
   failed it, and as written the row cannot be scored.
