# 2026-09-22 - a paid research model as the third arm

**Question run:** which UK API posts a physical letter as Royal Mail Signed For and hands back the tracking number.
**Arms:** legwork's real run of 2026-09-17, against `perplexity/sonar-deep-research` via OpenRouter, given the same question and nothing else.
**Cost of the comparator arm:** $0.95, 7.1 minutes, 18,182 completion tokens.

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

**A second, smaller miss, and the comparator found it by accident.** Postworks
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

## Reproducing

The comparator arm was a single OpenRouter call, `perplexity/sonar-deep-research`,
default parameters, one user message carrying the brief and no other context. The
brief withheld legwork's conclusion, its provider list and its findings - the arm
had to find Intelliprint on its own, and did not.
