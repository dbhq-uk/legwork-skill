# 2026-09-24 - the receipt says what the run could not reach

**Arms:** today's twelve skill-arm reports replayed through the new gate, and
one live run of the banks prompt (cases 1 and 6) on `feat/receipt-blocked`,
Claude Sonnet 5, with `LEGWORK_SKILL_DIR` on the branch.

## Why

The receipt is the first line a reader sees, and it exists to show the weight
of the work before anyone reads it. `sources.py receipt` has always printed a
blocked count - pages that refused the run on some rung - but the example
receipt in `SKILL.md` and all three template lines had no place for it, and
every run copied the example. The gate compared the opened count with the log
and never looked at blocked.

Now the example and the templates carry `N blocked` beside the opened count,
`SKILL.md` says which counts to copy from `sources.py receipt`, and the gate
warns when a receipt's blocked count disagrees with the log, or when a receipt
that carries counts leaves it out while the log has refused pages. Warnings,
like the opened check. A receipt that predates the counts is left alone.

## Replay

| | receipts |
|---|---|
| Log has refused pages, receipt silent about them | **11 of 11** |
| Log has no refused pages | 1, not flagged |

The eleven include logs with up to eleven refused pages. Not one of them told
the reader.

## Live run

The receipt read `21 opened, 2 via Bright Data, 10 blocked`, and the log holds
exactly 10 refused pages. It was right on the first draft - the new warning
never fired - and the chat answer led with the same line. 12 minutes, $5.70.

## Found, not fixed

**Seven quotes in this run were checked against their page and not found** -
against 0 or 1 in each of today's other runs with page text. Two are elisions:
two real sentences from the page joined with `...`, so each part is on the page
and the joined string is not. Five are whole quotes absent from the stored text,
one of them the page's meta description, which the text extraction does not
keep. This is the checker seeing subagent quotes it could not see before
`brief.py` carried page text back; whether elisions should count as verbatim is
a separate decision.
