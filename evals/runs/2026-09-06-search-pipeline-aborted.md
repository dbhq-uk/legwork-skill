# Legwork eval run - 6 September 2026 (aborted)

Cases 5 and 6, both arms, writer model Claude Sonnet. Skill at
`dbhq-uk/legwork-skill@feat/search-pipeline`.

**All four arms were terminated by an account rate limit before any produced a
deliverable.** No case is scored, and nothing here should be read as a result.
This file exists because one arm left evidence on disk before it stopped, and
because a run that was attempted and abandoned is itself a thing the next
session needs to know.

## What survived

The case 6 skill arm wrote ten fetch-log rows before it died:

```
10 sources · 5 opened · 0 snippet-only · 0 via Bright Data · 5 blocked · 4 queries
```

| Status | Rows |
|---|---|
| ok | openbanking.org.uk, develop.hsbc.com, developer.nationwide.co.uk, docs.monzo.com (two pages) |
| blocked | developer.sandbox.rbs.co.uk, developer.sandbox.ulsterbank.co.uk, developer.coventrybuildingsociety.co.uk, apis.developer.tsb.co.uk, developer.openbanking-obie-sandbox.chase.co.uk |

Three things are visible in that, and all three are what case 6 was written to
measure:

- **Blocked pages were recorded as blocked.** Five of them. In the 2026-08-13
  run every row in every log said `ok`, so a refusal left no trace and "how far
  did the run get" could not be asked. It can now.
- **Every row carries its query.** Four distinct queries across ten rows.
- **Nothing was cited from a snippet.** Zero snippet-only rows at the point it
  stopped.

## What it does not show, and should not be read as showing

- **No deliverable, so no gate result, no confidence bands, no receipt.** The
  arm never reached Phase 4.
- **Every row is `via=webfetch`, not `direct`.** The skill's page ladder puts
  `fetch.py` first. Ten rows is too few to say whether the agent skipped that
  rung, had not yet read that part, or hit only pages where it fell through -
  but it is the first thing the completed run must be checked for, because a
  ladder whose first rung is ignored is prose rather than mechanism.
- **The baseline arms produced nothing at all**, so there is no comparison of
  any kind in this file.

## Outstanding

Re-run cases 5 and 6, both arms, and score them. Until that happens the search
pipeline's reach is supported by unit tests, live smoke tests of each script,
and the ten rows above - not by a paired eval.
