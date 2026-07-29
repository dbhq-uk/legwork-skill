# Design notes

Why Legwork is shaped the way it is. The previous design, for a version aimed at
academic research, is archived at
[`archive/2026-07-pre-redesign-notes.md`](archive/2026-07-pre-redesign-notes.md).

## The problem the redesign solved

Legwork was built for academic research and used for decision research. Those are
not the same job, and the gap showed up in the output rather than in any test.

Auditing a run of real research questions - market validation, build-or-buy,
distribution choice, competitor and pricing scans - turned up five things:

- **Not one DOI in any bibliography.** The DOI resolver, the arXiv locator branch
  and the fake-academic-title heuristics had never fired once. A third of the
  citation-verification code was dead on arrival.
- **A third of one bibliography was a single vendor's documentation site**, spread
  across four subdomains and counted as that many independent sources.
- **No run had ever produced HTML or PDF**, despite around 1,400 lines devoted to
  producing them.
- **The re-ranker's recency component was silently dead.** It parsed dates into
  timezone-aware datetimes, subtracted them from a naive `datetime.now()`, raised
  `TypeError` on every one, and swallowed it in a bare `except`. Any date carrying
  a timezone - which is most of them - scored as unknown age.
- **"Three independent sources" was prose.** The instruction existed in SKILL.md;
  nothing in the code enforced it, and deduplication was by URL identity, so one
  wire story across five outlets counted as five.

The result is roughly a third of the previous line count with more checks, not
fewer.

## Fitness, not authority

The old scorer kept about forty blessed domains and scored everything else at a
flat 55. Nature scored 90; a Substack scored 40. For research into what a product
costs, who is hiring for a skill, or whether a marketplace slug is taken, that
ranking is not merely unhelpful, it is backwards.

A source is now judged by whether it is the right **kind** of thing for the
**claim** it backs. The vendor's own pricing page is the best available evidence
for a price and among the worst for whether the product is any good. The
complaints themselves are primary evidence of sentiment; an article about the
complaints is not.

Recency follows the same logic. A two-year-old price is worthless and a
two-year-old regulatory filing is fine, so the decay half-life is set per claim
kind rather than globally. Rebuilding it also removed the swallowed exception:
every datetime in `sources.py` is timezone-aware, and an unparseable date returns
a stated reason rather than a plausible-looking default.

## Corroboration is counted where we cannot inflate it

This is the part worth reading twice, and it is adapted from the confidence-floor
pattern documented in [`mvanhorn/last30days-skill`](https://github.com/mvanhorn/last30days-skill)
(MIT). The generalised rule there: a gate requiring corroboration must measure it
on a signal layer the system does not itself amplify.

Legwork's Gather phase fans out across sub-questions *in order to* find more
sources per finding. So any count downstream of that fan-out is partly a measure
of how hard we looked. A gate reading "this finding has five sources" is checking
that retrieval works, not that the finding is corroborated.

What we do not amplify is which **angle** surfaced a source. So corroboration is
the largest set of independence groups that can each be attributed to a different
angle - a maximum matching between groups and angles. Five sources from one query
score one confirmation, however many distinct publishers they span.

Before that count runs, sources collapse into independent voices by three tests:
the same canonical URL, the same registrable domain (one party is one voice), and
near-duplicate headlines (syndication).

The testing note from the same source applies and is followed here: a unit test
that hands the gate its parameters directly cannot catch a gate that never binds
in production. `test_the_gate_still_binds_when_the_fan_out_is_actually_running`
drives the full path with the amplifier running, and a CI job asserts the same
property end to end.

## The fetch log

Four sidecar files became one TSV sharing the report's base name. It exists to
make three checks possible that cannot be done after the fact:

**Was this cited page ever opened?** A citation to a URL absent from the log is
fabricated. This replaced a set of heuristics that tried to spot invented
citations by pattern-matching titles which sounded like fake academic papers -
patterns that never fired on real research and could only ever have produced
false positives on a legitimately titled vendor page.

**Did this figure appear on a page we fetched?** The log stores the normalised
numeric tokens found on each page, not the page text. That is enough to catch a
transposed or invented figure, which is the most damaging error this kind of
research can make, and small enough that the log stays a log.

**What did the page actually say?** One verbatim sentence per source, capped at
300 characters.

This column was not in the first cut, and leaving it out was the sharpest mistake
in the redesign. Counting findings across the archived runs, **44% carry no figure
at all** - one report of eight findings had none. For those, dropping the evidence
store left the gate checking nothing but "somebody opened this page", where the
old claim-support pass had done token, entity and year overlap against stored
quotes. The capability regressed sharply even though the practice barely changed,
because that pass ran only at deep level and exactly one archived run ever
produced a claims ledger.

One column restores both halves: a qualitative claim has something recorded behind
it, and that record survives the page changing or going dead. It costs the log
roughly 300 bytes a row and keeps it to one file.

## Two policies that nearly went as collateral

The rewrite deleted two `SKILL.md` sections that had nothing to do with the
academic framing, and it deleted them silently, which is worse than deleting them
on purpose. Both are back:

**The scrape cap.** `--max-chars 8000` on Bright Data scrapes, against the
wrapper's own default of 20000. A run reads dozens of pages and almost none need
twenty thousand characters in context to yield the sentence being quoted.

**The subagent policy.** Retrieval subagents on a cheaper model than the
orchestrator, returning structured evidence only and never a transcript. This one
could not have been restored without the quote column, because structured evidence
had nowhere to go once the evidence store was deleted - which is a reasonable
illustration of why the store existed in the first place. One agent per search
angle also keeps the angle attribution honest, since each agent only ever writes
its own.

## An honest empty answer is a result

The skill could not previously say "I could not answer this". It always produced a
report, so a question with no real evidence behind it produced hedged length
instead of a straight answer.

Findings now carry a confidence band, and material below the floor does not become
a finding at all. If nothing clears the floor the run says so and names the
closest sub-floor signal, which tells the reader the search genuinely ran and
usually suggests the narrower question that would have worked.

This is the same argument the gate makes. A tool whose non-empty answers can be
believed has to be able to produce an empty one.

## Bright Data stays a fallback

Built-in `WebSearch` and `WebFetch` first, direct `WebFetch` next, Bright Data
only when that fails. No per-level spend rule is needed: deep attempts more
primary sources, primary sources are disproportionately the ones that block you,
so paid usage rises with depth on its own.

`bd_search.py` is 272 lines with one dependency and no credentials of its own. The
alternative approach - browser cookie extraction, vendored platform clients, and a
keyless tier scraping search-engine HTML - buys the same coverage with an order of
magnitude more code, all of which decays every time a site changes. Paying for
unblocking is what keeps this small.

## Depth raises rigour, never length

The old modes carried word bands: deep meant 8,000 to 15,000 words. That is a
quota pretending to be a standard, and it rewards padding.

Depth now changes three things - how hard the run tries to disprove itself, how
many angles it takes, and whether it reaches primary sources or settles for
commentary. Length belongs to the format. A question fully answered in 3,000 words
ships at 3,000 words.
