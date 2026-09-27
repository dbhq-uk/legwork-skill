# Scripted gathering: wider research for half the cost

**Date:** 2026-09-27
**Status:** draft, awaiting review
**Decisions by:** Dan, 27 Sep 2026, one question at a time; each is recorded
where it applies.
**Scope:** `skills/legwork/scripts/` (a new `gather.py`, additions to
`platforms.py` and `sources.py`), the run as `SKILL.md` describes it,
`methodology.md`, the templates' receipt line, `SECURITY.md`, the evals.

## Contents

- [The problem, measured](#the-problem-measured)
- [Decisions](#decisions)
- [Goal](#goal)
- [The run](#the-run)
- [Components](#components)
  - [A. The plan file](#a-the-plan-file)
  - [B. `gather.py`](#b-gatherpy)
  - [C. Names must come from sources](#c-names-must-come-from-sources)
  - [D. `sources.py quote`](#d-sourcespy-quote)
  - [E. Reddit through `platforms.py`](#e-reddit-through-platformspy)
  - [F. The support scan](#f-the-support-scan)
  - [G. The receipt](#g-the-receipt)
  - [H. What leaves the run](#h-what-leaves-the-run)
- [Confidence](#confidence)
- [Error handling](#error-handling)
- [Testing and proof](#testing-and-proof)
- [Not yet known](#not-yet-known)
- [Out of scope](#out-of-scope)
- [Implementation order](#implementation-order)

---

## The problem, measured

Every figure here comes from the 24 and 25 Sep 2026 eval runs, recorded in
`evals/runs/2026-09-24-*.md` and `2026-09-25-*.md`.

**A standard run costs $4 to $7 of Claude usage, and almost none of that is
reading pages.** In a banks run with Jev on, Sonnet cost $6.48: 8.76 million
cached tokens re-read, 0.47 million new input, 0.45 million written to cache,
0.16 million output. An agent re-sends its whole conversation on every step,
so cost follows how many steps it takes and how much it has read by then.

**The orchestrator is two thirds of that, and much of it is waiting.** In two
banks runs the orchestrator took 50 to 55 steps and re-read 5.4 to 5.9 million
tokens, its conversation growing to 162-179 thousand; all subagents together
took 105 to 110 steps and re-read 2.9 to 3.1 million. In the Jev run, **34 of
the orchestrator's 55 steps were spent waiting** for background subagents -
scheduling a wake-up or listing agents - each re-reading a conversation of
over 100 thousand tokens and doing nothing else.

**Search results fill the subagents.** Across 17 runs, WebSearch output was 45%
of everything returned to subagents (598 calls, 3.5 thousand characters each),
and it stays in their conversations for every later step.

**WebSearch is restricted.** It returns about ten links a query, no snippets
and no country or language control, and only an agent can call it, so its
results cannot be kept out of a conversation. On 24 identical queries it and
Bright Data returned 222 and 204 links with only 37 in common; of the pages the
runs went on to cite, WebSearch found 20, Bright Data 14, both 6. The two
engines see different parts of the web.

**Framing from memory narrows the answer before research starts.** A plan that
names the banks, the vendors or the suppliers at the start can only confirm
Claude's list. It is the failure the 22 Sep comparison exposed in a paid
research model: it settled early on Royal Mail Click & Drop and never found
Intelliprint.

## Decisions

| # | Decision | Dan, 27 Sep |
|---|---|---|
| 1 | Paid Bright Data search is a normal route, not a last resort | yes, **no spending cap** |
| 2 | Success is at most half today's Claude cost, with at least today's reach and confidence | yes |
| 3 | Approach: scripts gather, Claude judges | approach A of three |
| 4 | Reddit is searched on every angle where people's experience matters | yes |
| 5 | Framing runs in two rounds: round 1 finds who is in scope from sources, round 2 researches each | yes |
| 6 | Claude's WebSearch is **dropped entirely** | yes |
| 7 | In step 1 Claude only asks - the question phrased many ways - and names nothing | yes |

Rejected: keeping subagents and WebSearch and trimming the waste (cheaper to
build, saves perhaps a third, no wider); running retrieval on Haiku (the 13
Aug sweep found Haiku filling a comparison from one aggregator and reporting
success); keeping WebSearch as a round-1 second engine (decision 6).

## Goal

A standard run that:

- costs **at most half** today's Claude usage for the same question;
- reaches **at least as many independent parties and primary sources** as
  today, and usually far more;
- keeps every check the gate makes today - quotes checked against the page,
  corroboration counted on independent parties from different angles, the
  confidence bands, the receipt against the log;
- names nothing in its answer that did not come from a source.

## The run

1. **Frame (Claude, about 3 steps).** The decision, the sub-questions, and the
   falsifiers - and for each sub-question, several phrasings in the words
   different people would use: a practitioner, a regulator, a buyer, a
   critic. **Claude names no organisation, product, site or answer.** It is
   the question, asked many ways. Written to a plan file.
2. **Gather, round 1 (`gather.py`, one call, no model).** Every phrasing
   searched, every result opened, passages picked, everything logged. The
   script also extracts the names that recur across the opened pages and
   counts how many independent parties name each.
3. **Plan round 2 (Claude, about 5 steps).** From the round-1 digest, Claude
   chooses what to research - usually the names found - and again only
   phrases questions about each. Every name must point at the round-1 sources
   that produced it.
4. **Gather, round 2 (`gather.py`, one call).** As round 1, per name,
   disconfirming phrasings included.
5. **Judge (Claude, about 10 steps).** Reads the digests, decides what each
   source shows, records the quotes its findings rest on, runs further rounds
   only where evidence is thin, reads what the support scan flags.
6. **Write, gate, file, answer (Claude, about 5 steps).** As today.

No subagents, and no step spent waiting: `gather.py` returns when it is done.

**Memory as a check, never a seed.** After round 1 Claude writes down anything
it expected that the sources never named. Each becomes one more phrasing to
search, marked as such. If nothing is found, the report says "expected X, no
source found" - memory can add a search, never an answer.

## Components

### A. The plan file

JSON, written by Claude, read by `gather.py`. One file per round.

```json
{
  "date": "2026-09-27",
  "round": 1,
  "country": "gb", "language": "en",
  "angles": [
    {"id": "offer", "question": "who offers developers a test environment?",
     "phrasings": ["bank API sandbox UK", "open banking sandbox register developer",
                   "account servicing payment service provider testing facility UK"],
     "disconfirming": ["UK bank open banking sandbox not available"],
     "people": true}
  ]
}
```

`people: true` adds Reddit and the community platforms for that angle. In round
2 each angle also carries `subject` and `from` - see [C](#c-names-must-come-from-sources).

### B. `gather.py`

```
gather.py --plan plan.json --tsv RUN.tsv --out DIGEST.md [--time-limit 600]
gather.py --urls urls.txt --angle ID --tsv RUN.tsv --out DIGEST.md
```

For every angle, concurrently:

1. **Search.** Each phrasing and disconfirming phrasing through `bd_search.py
   -m general` on Google and on Bing, with the plan's country and language.
   Where `people` is set, `platforms.py` for Reddit (E), Hacker News, Stack
   Exchange and GitHub issues. Every search result is logged `--via serp` or
   `api` as a lead.
2. **Narrow.** Canonicalise and de-duplicate links the way `independence.py`
   does.
3. **Open.** Every remaining link through `fetch.py`, in parallel. A refusal
   goes up the ladder `SKILL.md` already defines - Bright Data scrape, render,
   then a copy on another host - and every refusal is logged `blocked`.
   Reddit threads that matter are fetched with their comments through
   `bd_search.py -m reddit`.
4. **Pick.** The two or three passages per page that best match the angle:
   Jev's ranking when a key is available, the angle's phrasings as `--find`
   terms otherwise.
5. **Log.** Every retrieval through `sources.py`'s `log_row`, with page text,
   so any quote taken from it can be checked.
6. **Names.** In round 1, extract recurring organisation and product names from
   opened pages and count the independent parties naming each.
7. **Saturation.** Stop opening pages for an angle once the last few searches
   add no new party; record whether the angle saturated.
8. **Digest.** One Markdown file, one line per source: short id, party, kind,
   date, best passage (about 300 characters). Round 1 adds the name counts.
   This file, not the pages, is what Claude reads.

**Limits.** No spending cap (decision 1). A time limit per call, default 10
minutes: on reaching it the script returns what it has and lists what it did
not reach.

### C. Names must come from sources

A round-2 angle with a `subject` must carry either `from`, the round-1 source
ids that named it, or `expected: true`, meaning Claude's memory suggested it and
this angle is the check. `gather.py` refuses an angle with neither. The digest
and the log carry the provenance through, so the report can say where every
name came from.

### D. `sources.py quote`

```
sources.py quote --tsv RUN.tsv --id b12 --quote "the verbatim sentence"
```

Records the quote Claude chose against a row `gather.py` already logged, and
checks it against that row's saved page text, word for word - the check that
already runs at `log` time. Replaces the subagent-return path for this flow.

### E. Reddit through `platforms.py`

A `reddit` platform using `reddit.com/search.rss`, keyless (HTTP 200 with 25
posts on a live test, 25 Sep 2026). Refused (403 or 429): fall back to
`bd_search.py -m reddit` and log which route served it. Written in legwork, not
borrowed from `last30days`, so `platforms.py` stays standard library only and
depends on no other skill.

### F. The support scan

For each finding, Jev reads every passage gathered for its angles and marks it
supports, contradicts or unrelated; Claude reads only what is marked. This
finds the contradiction on the 140th page that nobody chose to open.

**Conditional.** Jev has been measured on relevance (the quoted passage in its
top three 75% of the time) but never on whether a passage supports a claim.
Built only if an offline test on the 24 Sep reports shows it finds the
passages behind their findings and the contradictions in them. Without a key,
or if the test fails, Claude checks the digest lines for each finding instead.

### G. The receipt

Adds parties reached, searches run, whether the search saturated, and Bright
Data spend (the figures below are illustrative):

> *standard · 3 angles · 186 sources from 74 parties (151 opened, 9 blocked) · 46 searches, saturated · 12 disconfirming · Bright Data $4.10*

### H. What leaves the run

Every phrasing goes to Bright Data as search text, so the research question
reaches them, as it reaches Claude's search provider today. Page text and
angles go to TypeSafe only when Jev is on. `SECURITY.md` says both.

## Confidence

- **Scope.** How many independent parties name each thing, and whether the
  search saturated. Named once is a lead; named by many is in scope.
- **Each finding.** Unchanged and enforced by the gate: quotes checked against
  their pages, corroboration on independent parties from different angles,
  Strong needing primary evidence and two confirmations. More pages opened
  means more chances to be confirmed or contradicted by a separate party.
- **The other side.** Disconfirming phrasings in both rounds, and the support
  scan across everything gathered (F).

## Error handling

| Case | Behaviour |
|---|---|
| Bright Data auth or quota | `gather.py` stops and says `brightdata login` or top up. It is the only search engine, so no findings from nothing |
| One search fails | Retried once, then logged as a failed search; the receipt counts failures |
| A page refuses | The ladder; every refusal logged `blocked` |
| Reddit RSS refuses | Bright Data's Reddit dataset; the route is logged |
| No Jev key, or Jev fails | Passages by phrasing terms; support scan by Claude; the receipt says Jev was not used |
| A round-2 name with no source | Refused (C) |
| Time limit reached | Returns what it has, lists what it did not reach |

## Testing and proof

- **Hermetic tests** for every script change, network patched as today: plan
  parsing, the Bright Data and platform fan-out mapping, de-duplication, name
  extraction and party counts, saturation, the digest, the name-provenance
  refusal, `sources.py quote`, the Reddit fallback, and every row of the error
  table.
- **The support scan's offline test** (F) before it is built.
- **A full eval before merge:** all six cases, today's `main` against the
  branch, Claude Sonnet 5. It passes only if Claude cost is at most half,
  reach (parties, pages opened, primary sources cited) is at least today's,
  confidence (quotes checked, the gate, each case's expectations) is at least
  today's, and no report names anything without a source.
- **Usage limits.** Arms run a few at a time and spread out; the 25 Sep re-runs
  were stopped four minutes in by the plan's limit.

## Not yet known

- **Bright Data's price per search.** Not on record in this repo. The eval
  measures what a run spends; the receipt shows it from then on.
- **Whether Bright Data alone reaches what WebSearch did.** On 24 queries the
  engines overlapped little. Two engines (Google and Bing) plus far more
  phrasings should cover it, and the eval's reach criterion is the test.
- **The time limit.** 10 minutes per round is a starting value.

## Out of scope

- Subagents, `brief.py` and `sources.py log-returns` leave the run. The scripts
  stay until the eval passes, then are removed in a follow-up.
- Jev choosing which search results to open. Tested on 25 Sep and not built;
  see `evals/runs/2026-09-25-jev-and-logging.md`.
- Changes to the gate's bands or checks.

## Implementation order

1. `platforms.py` Reddit (E), with tests.
2. `sources.py quote` (D), with tests.
3. `gather.py` search, narrow, open, pick, log (B 1-5), with tests.
4. Names, saturation, digest, provenance (B 6-8, C), with tests.
5. The support scan's offline test; build F only if it passes.
6. `SKILL.md`, `methodology.md`, templates, `SECURITY.md`, README.
7. The full eval; merge only on the goal above.
