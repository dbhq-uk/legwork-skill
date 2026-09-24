# Methodology

The detail behind steps 2 to 5 of the run. `SKILL.md` holds the rules and the
commands; this file holds what they look like in practice, and why. It does not
repeat them, so read the step in `SKILL.md` first.

## Contents

- [Frame](#frame) - good angles, and falsifiers worth naming
- [Gather](#gather) - queries, platforms, copies on another host, quotes, lists, source kinds
- [Challenge](#challenge) - the disconfirming case, independence, concentration, age, origin
- [Write](#write) - comparisons, confidence, credit, citations, the read against itself

Read the section for the step you are on. Reading all four before starting costs
context you will want later, and Write tells you nothing useful while you are
framing.

---

## Frame

### The decision

If the user gave you a topic, infer the decision from context and state your
inference in the Introduction rather than asking.

### Good angles

Good sub-questions are independent lines of enquiry, not rephrasings. "What does
the incumbent charge" and "what do buyers say they will pay" are two angles.
"What is the price" and "how much does it cost" are one angle asked twice, and
counting them separately is how a run fools itself into thinking it has
corroboration.

### Falsifiers

"If the platform ships this natively, the gap closes." "If practices already pay
more than we assumed, the ceiling argument dies."

This is the most valuable output of Frame. It gives Challenge something concrete
to hunt for, and it becomes the substance of Limitations instead of generic
hedging.

At **deep**, add second-order angles: who has tried this before and what
happened, what the incumbent would do in response, what the adjacent market says.

---

## Gather

### Queries

The three variants, for the angle "what does Acme charge":

- plain: `acme pricing 2026`
- targeted: `site:acme.example pricing`, or `"per user per month" acme`, or
  `acme price list filetype:pdf`
- negative: `acme price increase 2026`, `why we left acme`

**Year-pin dated material only.** A query that silently searches the wrong year
poisons everything downstream of it: the sources are real, the figures trace,
and the whole finding is a year stale. But an evergreen primary page does not
carry a year, and pinning it pulls in round-ups written about the page instead
of the page itself.

### Platforms by question

`platforms.py` returns the record rather than a page about it, with the
platform's own numbers attached.

| The angle is about | Ask |
|---|---|
| Sentiment, practitioner experience | `hn`, `stackexchange`, `githubissues` |
| Adoption | `github`, `npm`, `pypi` |
| Dated news, with real country control | `news` |
| What a vendor shipped and when | `feed` |
| What a dead or changed page used to say | `wayback` |

### Thin

Thin means fewer than two independent parties after three variants. Still thin
after the paid search rungs is a finding in its own right: say what was searched.

### A copy on another host

`fetch.py`, `WebFetch` and a paid scrape all ask the same host for the same URL,
so a publisher refusing by policy refuses all three, and climbing further can
only fail. Measured on 2026-09-22: two Royal Mail price-guide PDFs returned 403
to every route, while a search for the guide's own title found a third party's
copy at rank 1, which opened on the free rung with 400 numeric tokens in it.

Where to look: a trade body, a supplier, a consultancy, or a regulator reposting
a price list, a standard or a filing.

Three conditions make the copy safe to use:

- **It is a different party.** Log and cite the host that served it. Crediting it
  to the original publisher would claim a read that never happened.
- **It is the same document.** Check it carries the original's effective date or
  version before using a figure from it.
- **The refusal is recorded.** Limitations says the original refused you, so the
  reader knows the figure came second-hand.

### Take the quote as you read

The quote is the sentence you would point at if someone asked "what makes you
say that". Taking it later means refetching, and in six months the page may not
say the same thing, or exist at all.

The gate fails a finding that has neither a traceable figure nor a quote on any
of its cited sources. Not because the finding is wrong, but because nothing about
it can be checked.

### Rebuild lists from their items

A table lifted whole out of one review, roundup or analyst note is **one source,
not one source per row**. It is the easiest way for a run to look thoroughly
evidenced while resting on one document, and competitor scans and pricing
comparisons are exactly this shape.

Log the aggregator if you used it, then log each item you opened under the same
angle. `independence.py` then sees what is actually there: several parties
rather than one.

If rebuilding is genuinely impossible - the items are paywalled, or the
aggregator is the only party that ever collected them - say so in the finding
and lower the band. A single-origin list labelled as one is honest; the same
list presented as corroborated is not.

### Source kinds

The kind is inferred from the URL when omitted, but inference returns `unknown`
for anything it does not recognise.

The distinction that matters most is **vendor primary versus vendor marketing**.
A pricing page and a "why customers love us" page are both on the vendor's
domain. One is the best evidence available for what something costs; the other
is the worst evidence available for whether it is any good. The same goes for
complaints: the complaint itself is primary evidence of sentiment, and an article
about the complaints is not.

### Depth

- **quick**: search snippets. Open a page only to pin a specific figure.
- **standard**: open every source a finding rests on.
- **deep**: a primary source for every finding. The vendor's own pricing page,
  not the analyst's summary of it. The filing, not the article about the filing.
  Paid usage rises here on its own, because primary sources are the ones most
  likely to block you.

---

## Challenge

### The disconfirming case

A finding that survives a real attempt to break it is worth more than one that
was never attacked, and the reader should be able to see the attempt. That is
why what the disconfirming search finds goes inside the finding.

### What counts as one voice

`independence.py groups` collapses three things into one voice: the same page
reached twice, every page on one party's own domains, and near-duplicate
headlines across outlets. What comes out is the number of independent groups
actually behind the work.

Corroboration is then the number of those groups reached from **different
angles**. Five sources from one line of enquiry score 1, however many publishers
they span, because your own fan-out produced all five. If a finding you believed
was strong scores 1, that is the check working.

### Concentration across the run

A report can pass on every finding and still rest mostly on one party, which is
why `portfolio` looks at the run as a whole. The limits are in
`quality-gates.md`. The two failures need different fixes:

- **One party is over half the run.** That is a Gather problem, not a writing
  problem. Find a different party, or say plainly in Limitations that the picture
  is largely one party's account of itself.
- **One group is most of the run.** The run has found one story, repeated. Look
  for a second story rather than a seventh copy of the first.

### Evidence that has gone off

`finish.py` names the claim kinds whose evidence has aged. **Stale** needs a
newer source, or a sentence saying the figure is the most recent available and
how old it is. **Undated** needs the date recorded: a source with no date is not
necessarily old, but nobody can tell.

### The origin audit

Grouping catches near-duplicate headlines, but not "everyone is quoting the same
figure from the same place". For every Strong finding at deep, read the sources
and see where the number came from.

---

## Write

Write section by section, each write under about 2,000 words, so no single tool
call risks truncation.

### Comparisons

Decide the field list **before** fanning out, or each option comes back
described in its own terms and the grid cannot be assembled: one agent reports a
monthly price, another an annual one, a third "contact us".

Then write the findings from the grid rather than restating it. The matrix says
what each option does; the findings say which one to pick and why.

### Confidence

The band follows from the evidence, not from how much you would like the
finding to be true. The gate enforces the bands; what it cannot enforce is the
honesty of the reach.

When every finding falls below the floor, name the closest signal in the
could-not-answer shape. It tells the reader the search actually ran, and it
usually points at the narrower question that would work.

### Credit

The failure looks harmless: "Acme's 2026 market review reports that the segment
has four vendors, with pricing from 20 to 90 dollars per seat [3]." Every fact
there may be right and every figure traceable. But the sentence sources the whole
finding to the review, including the parts that came from four vendors' own
pricing pages, and neither the reader nor the independence check can tell which
is which.

Write it the other way round: state what is known, then attribute each part where
it belongs. A vendor's price belongs to that vendor's pricing page, even when a
review is where you first saw it collected. Credit the aggregator for what is
genuinely its own: its selection, its pooled analysis, its argument.

### Citations

- Label inference as inference. "This suggests" is fine; presenting it as fact is
  not.
- "No source addresses X directly" is a finding. A fabricated citation is a
  defect the gate catches anyway.
- Prose first. Bullets are for genuine lists, not for delivering content.

### Read the finished draft against itself

Challenge tests each finding as it is gathered. But findings interact, and
nothing has yet read the assembled document as a whole. Do that once, before the
gate:

1. Could the central recommendation be wrong, and what would have to be true?
2. Which high-impact claim rests on a single party, however many URLs back it?
3. Does any finding contradict another, or quietly assume one is false?
4. Does the Synthesis claim anything no individual finding supports?
5. Does any finding open by attributing itself to one document?
6. **Did a finding change what the answer has to do?** If one shows the decision
   turns on something no sub-question asked - a legal test, a hidden
   requirement, a constraint - go back and search for options that meet it
   before you recommend anything. On 2026-09-22 a run worked out that proof of
   posting, not proof of delivery, was what the law required, and never
   searched for a provider selling proof of posting. One existed.

**Find at least three issues, or read it again.** A pass that finds nothing on a
document this size has almost always not been run. Fix what you find. Where an
issue is real but cannot be fixed within the run, name it in Limitations.

Then finish the run: steps 6 and 7 in `SKILL.md`.
