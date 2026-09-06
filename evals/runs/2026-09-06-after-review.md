# Legwork eval run - 6 September 2026, second run

Cases 5 and 6, skill arms only, Claude Sonnet. Skill at `feat/answer-in-chat`,
which is `main` after the external-review fixes plus the rule that the answer is
given in the conversation as well as in the file.

**The baseline arms were not re-run.** A baseline never loads the skill, so
nothing changed for it; the arms from
[`2026-09-06-search-pipeline.md`](2026-09-06-search-pipeline.md), same prompts
and same model, still stand. Re-running them would have measured nothing.

Run for three reasons: the gate changed underneath the first run, the chat-output
rule had never been exercised, and the first run's finding was that the paid
rungs never got climbed.

## The first run's finding is closed

| | first run | this run |
|---|---|---|
| case 5 paid retrievals | 0 | **5**, against eBay pages that refused a direct fetch |
| case 6 paid attempts | 0 | **2**, one scrape and one render, both against blocked portals |

Case 5 escalated properly: `fetch.py` refused, `WebFetch` refused, Bright Data
scrape got through. Case 6 escalated and still failed, which is a different and
honest outcome - Santander 403s the Unlocker too.

Nothing in the fixes told an agent to escalate, so this is not a change anyone
made on purpose. Two runs is not a trend. What can be said is that the rung is
reachable in practice, which the first run left open.

## What the new checks did on real runs

**Quote verification fired.** Case 5 logged 10 quotes checked true and **one
false**, and the arm's own account says the gate sent it back to fix "two
duplicate rows with unverified quotes" before it would pass. Case 6: 17 true,
none false. Twenty rows in each run are unchecked, which is the expected shape -
no page text, so nothing to check against.

**The receipt matched the log in both arms**, again without being counted by
hand: `15 opened, 4 via Bright Data` and `15 opened, 0 via Bright Data`.

**The blocked count now shows the resistance.** Case 6 logged 14 blocked rows and
14 unreachable, against 3 in the first run. That is not the web getting harder; it
is the first run's arithmetic hiding retries and this run's not.

## The chat-output rule works

Both arms gave the answer in the conversation in the shape the skill asks for:
receipt line first, then the findings with their confidence bands, then
Limitations, then the path. Neither pasted a whole report. Case 6, whose
deliverable is a full report, correctly gave the Executive Summary and the
finding headings rather than the 4,000 words.

## The defect this run found

**`bd_search.py -m render` was returning the CLI's own help text as the page.**
`brightdata browser get` is a command group, not a leaf: invoked bare it prints
its usage and exits 0. The wrapper took that for a page body.

The case 6 arm caught it - it reported the render attempt failing with "what
looks like a CLI usage bug in this environment, not an auth/quota error" - and it
was right. **The unit test did not catch it, because it asserted the sequence of
verbs and never looked at what `get` returned.** That is the same class of defect
the external review flagged elsewhere: a test that would pass if the thing it
covers were broken.

Fixed three ways: `get html` is now sent, a body that looks like CLI usage is
refused outright, and the test asserts the full argument list.

While fixing it, two related things:

- **Paid fetches are now classified like free ones.** `_emit_page` marked
  everything `ok`, so a challenge page or an empty shell bought from the Unlocker
  would have been written to disk and quoted as the source. It now runs the same
  content checks and exits 3 when what came back is not a page.
- **A settle delay for the browser rung.** The CLI has no wait command and a
  single-page app is often still drawing when `open` returns. Measured on one
  bank portal: 7,115 bytes of HTML immediately, 7,392 after a few seconds, stable
  after that. Default 3 seconds, `--settle` to change it.

That portal still comes back as a shell with 49 characters of text, correctly
classified. The render rung works; that page defeats it.

## Scoring

Both cases pass, on the same expectations as the first run and with the same
verdicts. The one row that was half-satisfied then - "tries the next rung after a
block, and logs which succeeded" - is **satisfied now** in case 5, and satisfied
as far as it can be in case 6, where the next rung was tried and also refused.

## Actions

1. `platforms.py` is still barely used: two Wayback retrievals across both runs
   and nothing else in either. Write the case that needs a community or registry
   source, or accept that the rung exists for questions these two cases do not
   ask.
2. Case 6's `[unknown]` expectation still cannot be scored, for the same reason
   as before.
3. The render rung has now been fixed but never used successfully on a real page.
   The next run that meets a client-rendered source is the one that proves it.
