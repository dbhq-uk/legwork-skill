# 2026-09-22 - a paid research model as the third arm

**Question run:** which UK API posts a physical letter as Royal Mail Signed For and hands back the tracking number.
**Arms:** legwork's real run of 2026-09-17, against `perplexity/sonar-deep-research` via OpenRouter, given the same question and nothing else.
**Cost of the comparator arm:** $1.80 over two calls - once at default parameters, once at high reasoning effort and high search context. Both missed the answer. See "The run was repeated at full strength" below.

## Why this run exists

Every case in `evals.json` scores legwork against an agent without legwork. That
baseline measures whether the skill changes what an agent does. It cannot
measure whether the result is any good, because both arms are the same model
reading the same web.

This arm is a different question: put the same brief to a purpose-built paid
research system and see which report you would rather act on. It was run once,
on a question legwork had already answered in earnest, so the skill arm is a
real deliverable rather than an eval artefact.

It is not a new standard. Perplexity is a comparator and not an oracle - it
synthesises, and what it retrieved cannot be audited from the outside. A
disagreement is a lead to chase, never a verdict.

## Result

legwork wins on the only thing that decides the question, and has one real
defect the comparator exposed.

| | legwork (2026-09-17) | sonar-deep-research |
|---|---|---|
| Words | ~3,500 | 12,652 |
| Sources cited | 70, of which 54 opened | 19 |
| Providers characterised | 12 | 5 |
| Wall clock | ~30 min | 7.1 min |
| Marginal cost | Bright Data SERP + free fetches | $0.95 |
| **Recommendation meets the stated hard requirement** | **Yes** | **No** |

Three and a half times the length on 27% of the sources. legwork's "depth raises
rigour, it never raises length" is not a stylistic preference in this comparison;
it is the difference between the two reports.

## Where the comparator failed

**1. The primary recommendation does not do what was asked.** It recommends
Royal Mail's Click & Drop API or ShipEngine's Royal Mail carrier API, and
describes the workflow in its own words: *"the business prints the letter content
and label internally and injects the letter into the Royal Mail network"*. The
brief asked for an API that posts a letter. It never notices the contradiction.
legwork's Finding 4 names this exact trap - Click & Drop generates a label for an
item you print and hand over, which is not a letter Royal Mail prints.

**2. The secondary recommendation rests on a misread price.** It proposes
Postworks at "£7.75-£9.75 per item for Signed For hybrid mail" and builds a cost
comparison on it. Those two figures sit under the **inbound** plan's detailed
pricing on `postworks.co.uk/pricing/`, beside "Registered office address (per
month) £38.10" and "Request original (handling fee) £2.00". They are what
Postworks charges to forward post it has *received* for you. Postworks' outbound
plans - all three tiers - say "Post 1st and 2nd Class" and nothing else. The
weight brackets `<1kg` and `<2kg` are the tell: legwork's Finding 5 had already
established that Signed For prices a Letter as a Letter.

**3. The headline price figure is not in the sources it cites.** It gives
£2.74-£2.77 for 2nd Class Signed For, citing two royalmail.com PDFs and one
third-party copy. Both royalmail.com PDFs return 403 to `fetch.py` here, and the
third-party copy contains the string "Signed For" zero times - it is the Retail
Letters guide, covering Advertising, Business and Publishing Mail.

**4. It missed the answer.** Intelliprint, Docsaway, PC2Paper, PostGrid, Lob and
GOV.UK Notify do not appear in its report at all. Intelliprint is the only
provider either arm found that publishes a Signed For price, exposes it as an
enum in a public OpenAPI spec, and documents returning the Royal Mail tracking
number.

**One thing it got right that is worth recording:** legwork's structural Finding
3 - that bulk hybrid mail cannot do Signed For, for physical rather than
commercial reasons - correctly predicts Postworks, a provider legwork never saw.
A finding that predicts a case outside its own evidence is the kind worth having.

## Where legwork failed

**The blocked-source ladder escalates transport and never source. Confirmed, and
fixed in this PR.**

legwork's run recorded: *"Royal Mail blocks automated fetching. Every
royalmail.com figure came via Bright Data scraping rather than a direct read, and
the Royal Mail PDF price guides returned 403 to every route tried, so the 5
October 2026 letter prices are not verified from a Royal Mail document."*

The first half is still true. Both PDFs return 403 to `fetch.py` today. The
conclusion did not follow. The ladder was `fetch.py` -> WebFetch ->
`bd_search.py -m scrape`, which is three transports asking the same host for the
same URL; a publisher refusing by policy refuses all three, so climbing it can
only fail. Nothing in the ladder looked for a different copy of the document.

Measured on 2026-09-22, both halves of the missing rung:

| | Result |
|---|---|
| `bd_search.py "Royal Mail Retail Letters Price Guide January 2026 filetype:pdf"` | Republication at **rank 1** |
| `fetch.py` on the royalmail.com original | 403, 0 chars, 0 numbers, verdict `blocked` |
| `fetch.py` on the republication | **200**, 64,571 chars, **400 numeric tokens**, verdict `ok` |

A genuine Royal Mail price guide, effective 5 January 2026, on the free rung, one
search away. The run declared it unreachable and carried an unverified price into
Limitations instead.

**The fix in this PR** adds the rung to `methodology.md` step 6 and to
`fetch.py`'s exit-3 guidance, with the constraint that makes it safe: a
republication is logged and cited as the host that served it, never as the
original publisher, its effective date is checked against the original, and
Limitations still records that the original refused.

**A second defect, found while fixing the first.** The test pinning the new rung
used a `.pdf` URL. It passed here and failed on all five CI Pythons. The cause is
a real bug rather than a bad fixture: `fetch.py` dispatched on content type
*before* it looked at the HTTP status, so a 403 on a `.pdf` reached the PDF
branch, found no `pdftotext` on PATH, and exited 4 - *"content type this cannot
read; use WebFetch"*. Wrong twice over. The document was refused, not unreadable,
and WebFetch would be refused too. It only passed locally because this machine
has `pdftotext` installed.

Royal Mail's price guides are precisely this case, so on a clean machine the
run that started all of this would have been told the wrong rung about the exact
document that mattered. The refusal is now decided before the body is parsed.
Worth recording how it surfaced: the comparison found the missing rung, and CI
found the bug underneath it. Neither would have found the other.

**A third, smaller miss, and the comparator found it by accident.** Postworks
sells ClearSend - *"certified, time-stamped proof of postage"* through the Royal
Mail network, via its API, at no extra cost. legwork's Finding 5 had reasoned its
way to exactly this: under CPR 6.26 what you must certify is the date of posting,
not delivery, and Signed For does not prove service. legwork identified the right
question and then never searched for a provider answering it. That is a Gather
gap rather than a Frame gap, and it is the sharper kind, because the run's own
best finding is what made the thing worth looking for.

## What this does not change

No eval case was added. The README's rule is to grow the working set when a new
failure is observed in a real run, and the failure observed here is already what
case 6 (`get-through-a-blocked-primary-source`) is for. Case 6 passed on its own
terms in the 2026-09-06 run - the paid rungs were climbed. What this run found is
that the ladder case 6 tests was missing a rung, which is a defect in the ladder
and not in the case. The case will now exercise the new rung without being
rewritten.

The comparator arm is not being added to the harness. One run at $0.95 answered
the question it was run to answer. Repeating it on a schedule would buy a number
that moves with Perplexity's retrieval rather than with legwork's methodology,
and the README is explicit that a measurement habit which stops discriminating is
worse than none.

## The run was repeated at full strength, because the first one was not

The first call passed only `model` and `messages`. `sonar-deep-research` also
accepts `reasoning` effort and `web_search_options.search_context_size`, and both
default to medium. On a comparison whose headline number is *coverage* - 19
sources against legwork's 70 - those are the two settings most likely to move the
result, so the first arm could not carry the claim on its own.

Repeated the same day with `reasoning: {effort: high}` and
`web_search_options: {search_context_size: high}`. 458.5s, $0.85, 9,840 words, 19
citations.

**The settings changed what it read and not what it concluded.** Only **2 of 19**
sources are shared with the first run; the other 17 are different pages. Same
count, near-disjoint sets, same answer.

| | first run (defaults) | high effort, high search context |
|---|---|---|
| Sources | 19 | 19, of which 2 shared |
| Words | 12,652 | 9,840 |
| Found Intelliprint | No | **No** |
| Found Docsaway, PC2Paper, PostGrid, GOV.UK Notify | No | **No** |
| Primary recommendation | Click & Drop / ShipEngine | **Royal Mail Pro Shipping / ShipEngine** |
| Answered the price question | Yes, wrongly | **No** |

It corrected one of its own errors: Postworks is now ruled out properly -
*"does not advertise Signed For or Recorded Delivery in its public marketing nor
document an API that would return Royal Mail tracking numbers"* - where the
first run had recommended it on a misread price.

It also got worse on the half of the brief that asked for prices, and says so
plainly: *"the publicly accessible material reviewed provides limited direct
pricing information."* The first run gave figures that were wrong; this one gives
none. Neither delivers the rate card legwork published from a vendor's own page.

And it repeats the category error. Royal Mail's Pro Shipping API and ShipEngine
buy Signed For postage and produce a label for an item **you** print and hand
over. The brief asked for an API that posts a letter. Two runs, two settings,
near-disjoint evidence, the same wrong shape of answer - which is the useful
result here, because it says the miss is structural rather than a sampling
accident.

**One thing not proven.** `reasoning_tokens` came back 0 and the `reasoning`
field empty on both runs, despite `include_reasoning: true` on the second, so
there is no direct evidence the effort setting took effect. The near-total change
of sources is evidence the search-context setting did. Recorded rather than
argued away.

**And one practical note for anyone repeating this:** the high-effort call
exceeds OpenRouter's 300-second non-streaming timeout and returns 504. It has to
be run with `stream: true`.

## Reproducing

Two OpenRouter calls to `perplexity/sonar-deep-research`, one user message
carrying the brief and no other context: the first at default parameters, the
second at high reasoning effort and high search context, streamed. The brief
withheld legwork's conclusion, its provider list and its findings - both arms had
to find Intelliprint on their own, and neither did.

Generation ids `gen-1790068776-7sGGiG1YOuDML7DqEDKS` and
`gen-1790078320-rBojmpk3GRf4cDPOUCOQ`. $1.80 the pair.
