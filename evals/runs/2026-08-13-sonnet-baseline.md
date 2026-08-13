# Legwork eval run - 12 August 2026

First baseline. Writer model: Claude Sonnet, both arms. Skill at
`dbhq-uk/legwork-skill@feat/enforce-and-measure`.

## Harness

Each case runs twice: a **skill arm** (fresh agent, legwork available, prompt
given verbatim) and a **baseline arm** (fresh agent, explicitly forbidden from
loading any skill, same question). Both write to
`/home/devops/legwork-evals/20260812/`, never into the real `docs/research/`.

### Harness flaw found on the first run

Forbidding writes to `docs/research/` makes legwork's **refresh-in-place** path
impossible, because a refresh by definition updates the existing folder. Case 3
is the only case with a prior run, so it is the only one affected, and its
`created_new_run_folder` result must be read as a harness artefact rather than a
skill failure. Fix before the next run: copy `docs/research/` into the eval
output base so the prior run is present and writable.

---

## Case 3 - answer from the index instead of researching again

**Skill arm.** Skill activated on the literal `legwork:` prefix. Read
`docs/research/index.md` before searching, found
`Plugin_Gallery_Distribution_Research_20260714` as an exact match, and answered
from it, naming the run and its date and keeping its confidence bands.

It then did something the eval did not anticipate and which is defensible: the
prior run was about 30 days old and its own text said to re-check if more than a
few weeks passed, so it ran a **quick-level refresh**, re-fetching three live
primary sources. All three were unchanged, so nothing was superseded. Four web
searches, where the ideal answer is zero.

| Expectation | Result |
|---|---|
| Reads the research index before searching | satisfied |
| Recognises an existing run covers the question | satisfied |
| Answers from that report rather than re-running | satisfied - refreshed rather than re-ran |
| States the answer comes from a run of a given date | satisfied |
| Preserves the original confidence bands | satisfied |
| Does not create a second run folder | **not satisfied - harness artefact** |

**Verdict: pass, with the last row void.** The staleness-triggered refresh is
correct behaviour under the skill's own rules, and the expectation as written
does not allow for it. Reword it: *"does not re-run research that a prior run
already settled, and if it refreshes, refreshes in place"*.

### Defect this case surfaced

`check.py --format` defaults to `report`. The agent gated a **brief** with the
default, failed on four missing report-only sections, and only then passed
`--format brief`. The failure was spurious and cost a cycle.

`finish.py` already infers the format from the document, and the Stop hook was
fixed to do the same before it shipped. `check.py` is now the only entry point
carrying the trap, and it is the one the methodology tells people to run.

**Action: default `check.py --format` to `auto` and infer.** Not applied during
this run - changing the instrument mid-measurement would invalidate the arms
still in flight.

---

## Case 4 - return nothing rather than hedged length

**Baseline arm (no skill).** Refused to give a number, said the question could
not be answered from public data, cited sources inline, and offered adjacent
evidence instead - broad AI-adoption survey figures and list pricing for named
tools at roughly 7 to 59 US dollars per user per month. Six searches, two pages
fetched, 1,167 words.

It flagged its own weaknesses unprompted: one source was 403-blocked so an
anecdote rests on a search snippet only, and it did not try paywalled market
research. Its own summary of the output was that it was "fairly long/padded with
a sourcing table and a 'why I'm not estimating' section - could have been
tighter".

**This is the most useful result so far, and it is a problem with the case.**
The honest refusal is what case 4 was built to test, and an unaided Sonnet
produced it without the skill. On the headline expectation - do not fabricate a
number - the case does not discriminate between the arms at all.

What may still discriminate is **shape**: legwork specifies a `## Could not
answer` section, a `Closest thing found:` line, no findings, and explicitly no
hedged length. The baseline delivered the right verdict in the wrong form, at
1,167 words, and knew it. If the skill arm lands the same verdict in the
prescribed shape and materially shorter, the case measures something real -
just not the thing its name claims.

Pending the skill arm before rewriting it. The candidate rewrite is to score
**form and length given a correct refusal**, and to drop "does not fabricate a
number" to a precondition rather than an expectation, since both arms clear it.

## Case 2 - rebuild an enumeration rather than lifting it

**Baseline arm (no skill).** 11 searches, 13 pages fetched, six providers
compared, a table, inline citations, and a recommendation. It opened nine
vendor-owned pricing pages and used seven aggregators. Supabase, Neon and
DigitalOcean headline figures were confirmed on the vendor's own page.

So the baseline **largely rebuilt the enumeration from the items on its own**.
The enumeration rule is the highest-value import of the last cycle, and on this
task an unaided Sonnet substantially does it unprompted. That is the second case
running in this batch where the baseline is stronger than the case assumed.

Where the baseline actually broke is narrower and more interesting. Two figures
did not come from a vendor page, and it said so:

- Render's entry tier is reported as 6 or 7 US dollars per month depending on
  the source, and Render's own pricing page would not render via fetch, so both
  numbers rest on aggregator snippets that disagree with each other.
- AWS `db.t4g.micro` in London has no figure from AWS directly. The baseline
  produced one anyway - roughly 13 to 14 US dollars per month - by taking an
  observed 16% regional premium from **a different instance size** and applying
  it to a confirmed us-east-1 rate.

That second one is the real target. It is a derived estimate presented inside a
pricing comparison, and it is exactly what legwork's figure-tracing gate exists
to catch: a decimal in a cited sentence that appears on no page that was opened.
The baseline was honest about it in a notes field the user would never see; the
question is whether the skill arm keeps it out of the table, labels it as
inference, or trips the gate on it.

**Candidate rewrite for this case.** The discriminator is not "did it open
vendor pages" - both arms do. It is *what happens to the figure that cannot be
sourced*: excluded, labelled as inference, or silently tabled as fact.

## Case 1 - gate compliance on a finished run

**Baseline arm (no skill).** 19 searches, 5 pages fetched, 17 banks named across
the CMA9 and beyond, cited inline, with a precise uncertainty section.

It named its own weakest evidence without being asked: the Barclays, Lloyds and
Santander developer portals returned 403 or socket errors to automated fetch, so
those rows rest on search-result snippets quoting the sites rather than a
first-hand read. It also flagged that it could not confirm Revolut's current UK
banking licence status.

Note the ratio - **19 searches to 5 fetches**. Three of the pages that mattered
most were blocked, and the baseline had no way through them. Legwork's Bright
Data fallback exists for exactly this, so "gets further on blocked primary
sources" is a discriminator this case should measure and does not currently
mention.

---

## The pattern across all three baselines

This is the finding of the run so far, and it was not one of the four things
being tested.

**Every baseline arm was strong.** Unaided Sonnet, with no skill loaded, in all
three cases: searched thoroughly, opened vendor-owned primary sources where it
could, cited inline, refused to invent a figure it could not support, and
volunteered its own weakest evidence unprompted. Case 4's baseline declined to
give a number at all. Case 2's baseline rebuilt most of the enumeration from
vendor pricing pages on its own. Case 1's baseline named exactly which rows were
snippet-only.

Three of the four cases were built on the assumption that these behaviours are
what legwork adds. On this evidence they are substantially the model's floor,
not the skill's contribution.

**What is left, and it is not nothing.** In all three baselines the honest
caveat lives in a notes field, a closing paragraph, or a JSON blob the user
never sees. Nothing about it is checkable, countable, or enforceable:

- Case 2's baseline put a figure in a pricing table that it derived by applying
  a 16% regional premium taken from a different instance size. It disclosed this
  in a note. A reader of the table sees a price.
- Case 1's baseline built three rows from snippets and disclosed it in a
  section. A reader of the table sees a requirement.

Legwork's claim was never that it makes a model more honest. It is that it makes
honesty **land in an artefact a machine can check** - a fetch log, a traceable
figure, a confidence band, a gate that refuses. The baselines suggest that is
the whole of the marginal value, and the eval set should be rewritten to measure
that rather than the diligence the model already has.

Pending the remaining skill arms before committing to that conclusion.

---

## Case 4 paired result

| | baseline | skill |
|---|---|---|
| Verdict | could not be answered | could not be answered |
| Searches | 6 | 11 |
| Pages fetched | 2 | 8, including Bright Data on blocked pages |
| Words | 1,167 | 865 |
| Shape | prose, sourcing table, "why I'm not estimating" section | `## Could not answer`, `Closest thing found:`, zero findings |
| Narrower question offered | no | yes |
| Gate | n/a | passed first attempt |
| Filed for reuse | no | yes |

**The hypothesis held.** Same verdict, and the case does not discriminate on
"did it refuse to fabricate" - both arms refused. It discriminates hard on
everything after the refusal.

The skill arm did roughly twice the work and produced a quarter less document:
865 words against 1,167. That is the "depth raises rigour, never length" claim
behaving as designed, and it is the first time it has been measured rather than
asserted.

Three differences matter more than the word count:

- **It got further on blocked sources.** Two primary fetches returned nav-shell
  content rather than body text on two attempts each, one via Bright Data. The
  skill arm declined to cite figures from either and recorded them as gaps. The
  baseline, on the same class of problem in case 1, had no fallback at all.
- **The refusal is checkable.** `## Could not answer` with a `Closest thing
  found:` line and zero `Finding` headers is a shape `check.py` validates. The
  baseline's refusal was correct and unverifiable.
- **It gated itself, first attempt, and filed the result.** A future session
  asking this question finds "we looked and nothing held" instead of paying for
  the search again. This is Finding 3 of the research report - runs that never
  reach the index - not reproducing under the new regime.

The closest evidence it found is also better than the baseline's: a real UK
accountant forum thread where two- and three-person practices describe
*trialling* rather than buying, with no price mentioned in 22 replies. The
baseline offered category list pricing that no UK practice is documented as
having paid, which is a weaker answer wearing more confidence.

**Case 4 stands, with its scoring basis rewritten.** Drop "does not fabricate a
number" to a precondition. Score form, length given a correct refusal, gate
result, and whether the run was filed.

---

## Case 1 paired result - the arms disagree on the answer

| | baseline | skill |
|---|---|---|
| Searches | 19 | 11 orchestrator + 8 retrieval subagents |
| Distinct pages fetched | 5 | 30 |
| Fetch log | none | 34 rows, **all 34 carrying a quote** |
| Receipt line | n/a | present |
| Confidence bands | n/a | on all 5 findings |
| Gate | n/a | passed, 2 non-blocking warnings, addressed in Limitations |
| Filed for reuse | no | yes |

**The two arms give contradictory answers to the user's actual question.**

- Baseline: "nearly all let you self-register a developer/app account for
  sandbox access with no FCA check".
- Skill: only **HSBC Group and NatWest Group** let an unauthenticated developer
  register and call the sandbox with no eIDAS certificate and no FCA-regulated
  TPP status. Every other bank checked gates the *sandbox* behind the same Open
  Banking Directory enrolment and Software Statement Assertion machinery that
  gates production.

These cannot both be true, and they are not a nuance apart - they are opposite
answers to "what does each one require before you can call it". The baseline
reached its version having fetched five pages, three of which mattered and were
403-blocked, and generalised from search snippets. The skill arm reached the
opposite version having opened thirty pages with a quote recorded on every one.

Neither has been adjudicated here. On evidence quality it is not close.

The skill arm also found something the baseline missed entirely: Virgin Money's
Open Banking registration is being retired into Nationwide's from 3 April 2026
following the merger. And where it could not verify, it said so structurally
rather than in a note - Barclays returned 403 to both WebFetch and Bright Data
on every page but its landing page, and Starling's docs are client-rendered, so
both rows are `[unknown]` in the matrix rather than filled from a 2022
third-party guide.

### This corrects the conclusion drawn from the baselines alone

Earlier in this run, with three baselines in and one skill arm, the working
conclusion was that the baselines were strong enough that legwork's marginal
value was **checkability rather than finding more**.

Case 1 refutes that. The skill arm found more, found it from primary sources,
and reached a materially different answer on the central question. Six times the
pages fetched is not a presentational difference.

The honest revision: the baselines are strong on *disposition* - they will not
fabricate, and they disclose their weak spots. They are weak on *reach*. An
unaided arm that hits a 403 on the three pages that matter writes a confident
generalisation from snippets, discloses the snippet reliance in a closing
section, and produces an answer that is wrong in its headline. That is a worse
failure than padding, and it is the one legwork actually prevents.

---

## Case 2 paired result - what happens to the figure that cannot be sourced

| | baseline | skill |
|---|---|---|
| Providers compared | 6 | 8 |
| Vendor pricing pages opened | 9 | 8 |
| Aggregators used | 7 | 2 |
| Fetch log | none | 39 rows |
| Blank cells | n/a | 0 |
| Gate | n/a | passed on second run |
| Recommendation | Supabase | Neon, then DigitalOcean or Crunchy Bridge at scale |

**The predicted discriminator is the one that fired.** Both arms met the same
two unsourceable figures. They handled them oppositely.

- **Baseline:** AWS `db.t4g.micro` in London had no figure from AWS. It produced
  one anyway - roughly 13 to 14 US dollars per month - by applying a 16%
  regional premium observed on *a different instance size*. It went in the
  table. The derivation was disclosed in a notes field.
- **Skill:** no aggregator-only price was presented as established fact.
  DigitalOcean's free-trial credit, seen only on a third-party blog, is marked
  in the matrix as unverified against a DigitalOcean-owned page. Render's
  contested 6-versus-7-dollar tier is flagged unconfirmed in Limitations rather
  than asserted. Render's pricing page is JS-rendered and could not be fetched,
  and that is stated rather than worked around.

The arms also disagree on the recommendation, and the skill arm's reason is one
the baseline never surfaced: **Render and Railway are ruled out on UK and EU
region grounds**. For a UK startup that is decision-relevant and invisible in a
price table. The baseline compared Render on price and recommended Supabase.

### The self-review caught real defects before the gate did

The draft-level adversarial re-read shipped in the last cycle, and this is the
first evidence of it working. Before gating, the skill arm found and fixed: one
broken or mismatched citation, **two sources quoted in the draft that were never
logged to the fetch log**, and one citation misattributed to the wrong
DigitalOcean page.

Those two unlogged sources are exactly what the anti-fabrication gate exists to
catch. The re-read caught them first, which is cheaper.

### An instruction that did not fire

The skill arm reported that the level line - "Running standard..." - was never
emitted before Phase 1. Work went straight from skill invocation into tool
calls. The level was correct and applied consistently, and appears in the
report's receipt line, so nothing downstream broke.

It is still a rule that is stated plainly in `SKILL.md`, near the top, and did
not fire. That is Finding 2 of the research report reproducing under
observation, on the cheapest possible instruction, in a run that otherwise
followed the skill closely. It is one data point, not a measurement, but it is
the right shape to watch.

---

## Verdict

Four cases, eight arms, one writer model. Not a benchmark - a first baseline.

**Legwork earns its place, and not for the reasons the eval set assumed.**

| Case | Discriminates? | What actually separates the arms |
|---|---|---|
| 1 | **strongly** | Reach. 30 pages against 5, and a contradictory headline answer |
| 2 | **strongly** | What happens to an unsourceable figure, and non-price decision factors |
| 3 | weakly | Both find the prior run; the skill files and refreshes it |
| 4 | moderately | Same verdict, checkable shape, 26% shorter, filed for reuse |

**What was wrong in the eval set, corrected in this commit.** Three of four
cases were built on the assumption that legwork's contribution is diligence -
opening primary sources, refusing to fabricate, disclosing uncertainty. The
baselines do all three unprompted. Those expectations are now preconditions;
the scored expectations are the ones that measure reach, the fate of an
unsourceable figure, checkable form, and whether the run survives for reuse.

**What the run vindicated.** The gate passed on all three skill arms - once on
first attempt, twice on second - against a starting position where **no run in
`docs/research/` had ever passed it**. Every skill arm wrote a fetch log, a
receipt line and confidence bands. Every one filed itself. The draft-level
re-read caught two unlogged sources before the gate saw them. On this evidence
the enforcement work in this PR does what it was meant to do.

**What it exposed.** `check.py` defaulted to report format and failed a brief
for four sections a brief never has - fixed here, with tests. The level
announcement did not fire in one of three runs. And the eval harness itself
needs `docs/research/` copied into the output base so the refresh-in-place path
is reachable.

**Not yet done: the model sweep.** Every arm here is Sonnet. Legwork's own
model carve-out - cheap models for snippet gathering, the orchestrator's model
for rebuilding an enumeration - is still borrowed from someone else's benchmark.
Case 2 is the case that tests it and it has not been run on Haiku or Opus.

---

# Model sweep - case 2 on Haiku

## The carve-out is validated, emphatically

| | Haiku | Sonnet |
|---|---|---|
| Providers compared | 7 | 8 |
| Vendor pricing pages opened | **3** | 8 |
| Aggregators used | 1 | 2 |
| Fetch log rows | **9** | 39 |
| Retrieval subagents dispatched | **0** | 9 |
| Blank cells | 0 | 0 |
| `[unknown]` cells | **0** | 0 |
| Gate result | pass | pass |

Haiku opened three vendor pricing pages out of seven providers and filled the
other four rows from one comparison article plus search snippets. It reported
this honestly when asked: DigitalOcean, AWS RDS, Heroku and Render prices all
came from an aggregator, and the 16GB production figures were "not independently
verified on vendor pages".

**And it presented zero `[unknown]` cells.** Sonnet, on the same question with
the same skill, refused to state any aggregator-only price as fact and marked
the ones it could not source. Haiku filled the grid.

This is the enumeration failure the rule exists to prevent - a table lifted out
of one review is one source, not one per row - reproduced exactly, on the
cheaper model, with the rule loaded and visible. hec-ovi's finding replicates.

It also ignored the fan-out entirely: **zero retrieval subagents** against
Sonnet's nine.

## The serious part: the gate passed it, and the hook did not block it

The run reported `gate_result: pass`, truthfully. Verified directly against the
shipped artefact:

```
warning  no fetch log supplied, so cited URLs cannot be checked
warning  Neon: the row states values but carries no citation anywhere
warning  Supabase: the row states values but carries no citation anywhere
warning  Heroku: the row states values but carries no citation anywhere
warning  Render: the row states values but carries no citation anywhere
warning  Railway: the row states values but carries no citation anywhere
PASS
```

**A comparison matrix in which five of seven rows cite nothing at all passed the
gate.** At deep level the identical report fails with those same five as errors.

Three distinct defects, in order of seriousness:

**1. The Stop hook is level-blind, so it enforces structure only.** It reads
`LEGWORK_DEFAULT_MODE`, which is unset, so it gates at standard - and at
standard the entire evidence, independence and matrix layer is warnings. The
centrepiece of the enforce cycle fires at the weakest available setting. Run
against this report, the hook stayed silent.

The fix is not to force deep on everything. It is to gate at **the level the
report itself claims in its receipt line**. A run that announces standard gets
standard; a run that announces deep gets deep; and a run whose receipt says deep
can no longer pass by being checked as standard.

**2. Fetch-log discovery is base-name-only.** Haiku wrote `sources.tsv` rather
than `<base>.tsv`, so `check.py` never found it and skipped the evidence layer
entirely. Its absence is only a warning at standard, so nothing surfaced. The
gate should fall back to any single `.tsv` beside the report before concluding
there is no log.

**3. A matrix row stating values with no citation should be structural.** The
grading argument in `quality-gates.md` is that structural problems make a
document unusable regardless of how well researched it is. A confident grid
citing nothing is exactly that. It is currently graded as evidence.

**This was found only because the sweep ran.** Three Sonnet arms and four cases
did not surface it, because Sonnet never produced a matrix weak enough to expose
how permissive standard level is.

---

# Model sweep - the three-way result

Same prompt, same skill, same day. Only the orchestrator model changed.

| | Haiku | Sonnet | Opus |
|---|---|---|---|
| Providers compared | 7 | 8 | **14** |
| Vendor pricing pages opened | 3 | 8 | **32** |
| Fetch log rows | 9 | 39 | **96** |
| Retrieval subagents | **0** | 9 | 8 |
| `[unknown]` cells | 0 | 0 | **6** |
| Aggregator-only prices in the grid | **4 of 7 rows** | none | none |
| Options examined and explicitly dropped | 0 | not recorded | **7, with reasons** |
| Largest party share | not run | passed | 13% |

**The carve-out is confirmed, and the shape of the confirmation is the
interesting part.** The `[unknown]` row inverts: Haiku 0, Sonnet 0, Opus 6. More
capability produced *more* admitted ignorance, not less. Haiku filled every cell
confidently from one aggregator; Opus opened thirty-two vendor pages and still
marked six cells unknown, each with a footnote saying why.

Opus also did the thing the enumeration rule is actually for. It refuted two
aggregator figures against vendor rate cards rather than repeating them - an EU
roundup's "Neon 30 to 80 dollars a month" against Neon's own rate card at 172.26
for the reference workload, and a competitor-authored benchmark implying about
265 dollars for Tiger Data, which it excluded and left `[unknown]`. It reached
AWS and Azure through vendor-owned machine-readable price endpoints when the
human-facing pages would not render server-side. Where it could not get in at
all - ICO guidance, 403 to both WebFetch and Bright Data - it banded the finding
Moderate and said so in the confidence line and the Limitations.

### The draft-level re-read is now the best-evidenced rule in the skill

Opus's self-review, before gating, found and fixed five real defects:

- a finding heading claiming the cheap band excluded hyperscalers, which its own
  AWS data contradicted
- a Synthesis assertion about DigitalOcean's corporate stability that no finding
  supported
- an executive summary saying "three providers are cheaper" when it was two, and
  naming the wrong two
- **a receipt line that was asserted rather than counted** - recounted from the
  log
- an uncited self-hosting break-even figure

That fourth one is Finding 3 of the research report - a run reporting compliance
it did not achieve - caught by the skill's own machinery before it shipped.

## Fixes shipped from the sweep

All three verified against the actual failing artefact, not a synthetic one.

1. **The hook gates at the level the report claims.** It reads the level from
   the receipt line, falling back to the environment default only when there is
   no receipt. A run announcing deep can no longer pass by being checked as
   standard.
2. **Fetch-log discovery falls back to the only `.tsv` beside the report.** Two
   logs stay ambiguous and neither is guessed.
3. **An uncited matrix row is structural at every level.** It is not a judgement
   about evidence strength, it is the absence of evidence, and the prose
   equivalent - "no inline `[N]` citations in the body" - has always been
   structural.

Verified after the change: the Haiku report now fails and the hook blocks it,
every other eval run still passes, all six must-fail fixtures still fail for
their own reason, and both must-pass fixtures still pass. 221 tests.
