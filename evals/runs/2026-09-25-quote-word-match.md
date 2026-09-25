# 2026-09-25 - a quote is checked word for word

No eval run: this is a replay of the 2026-09-24 eval runs' fetch logs against
the page text those runs saved, through the old check and the new one.

## Why

The receipt run logged seven quotes as not on their page. Traced one by one,
five had every word on the page, in order, and differed only in punctuation: a
full stop or a colon joining a heading to the next line, commas joining list
items, a full stop closing a sentence the page continues, and a space the text
extraction left before a full stop (`app/environment .`). The other two were
elisions, two sentences joined with `...`.

Across every run on 24 Sep, twelve quotes were marked false. Eight were
punctuation or symbols only - the three from earlier runs were a colon after a
heading, em dashes and curly quotes rewritten as commas, and a dropped `®`. Two
were elisions, one was a real misquote (a changed price), and one had no page
text left to check.

## Change

`normalise_for_match` now treats every punctuation mark and symbol as a space,
and folds case and whitespace. A quote verifies when its words appear on the
page as a contiguous sequence.

## Replay

Every quote from those logs with page text still on disk, 329 of them:

| Old check | New check | Quotes |
|---|---|---|
| true | true | 240 |
| false | false | 70 |
| false | **true** | 19 |
| true | false | **0** |

Nothing that passed now fails. Every flip is, by construction, a quote whose
words are all on the page in order. The real misquote and both elisions still
fail.

## Found, not fixed: quotes taken through WebFetch are mostly not verbatim

The replay could also check quotes that were never checked when logged, because
no page text went with them, against a real copy of the same page saved by
another run. Non-elided quotes only:

| Taken via | Quotes | On the page word for word |
|---|---|---|
| `fetch.py`, logged without its text | 45 | 80% |
| WebFetch | 44 | **38%** |
| Bright Data | 5 | 60% |
| Search snippet | 13 | 7% |

WebFetch returns a model's reading of a page, not the page, and a quote taken
from it is usually that model's paraphrase. The gate counts an unchecked quote
as recorded evidence, which is how these pass. Some of the gap may be a page
that changed between runs, which is why `fetch.py`'s own unchecked quotes sit at
80% rather than 100%; it does not explain 38%.

**How far it reaches, and why no gate change followed.** Of 62 findings across
the 24 Sep reports, 7 rest on nothing but WebFetch or snippet quotes nobody
checked - and all 7 are from runs before the subagent brief came from a script
(`2026-09-24-brief-script.md`). Every run since has none. The WebFetch quotes
were a symptom of subagents not using `fetch.py`, which the script fixed, so
the gate is left as it is. If a later eval shows findings resting on unchecked
WebFetch quotes again, that is the signal to make the gate treat them as
unrecorded.
