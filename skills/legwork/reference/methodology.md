# Methodology

Four phases. Read this at the start of a run; the level table in `SKILL.md` says
which parts apply.

---

## Phase 1: Frame

Turn the request into three things. Write them down before searching, because
everything downstream keys off them.

### 1. The decision

Not the topic. The decision. "Outlook triage" is a topic; "should we build
Outlook triage for small accounting practices, or is the gap too narrow" is a
decision. If the user gave you a topic, infer the decision from context and state
your inference in the Introduction rather than asking.

### 2. The sub-questions that would settle it

Between two and eight, depending on level. Each must be answerable by evidence,
and each becomes an **angle** recorded against every source it surfaces.

Good sub-questions are independent lines of enquiry, not rephrasings. "What does
the incumbent charge" and "what do buyers say they will pay" are two angles.
"What is the price" and "how much does it cost" are one angle asked twice, and
counting them separately is how a run fools itself into thinking it has
corroboration.

### 3. What would change the answer

Name the falsifiers explicitly. "If the platform ships this natively, the gap
closes." "If practices already pay more than we assumed, the ceiling argument
dies."

This is the most valuable output of the phase. It gives Challenge something
concrete to hunt for, and it becomes the substance of the Limitations section
instead of generic hedging.

At **quick** level, skip the falsifiers. At **deep**, add second-order angles:
who has tried this before and what happened, what the incumbent would do in
response, what the adjacent market says.

---

## Phase 2: Gather

Work sub-question by sub-question. For each one:

1. Search with the built-in `WebSearch`.
2. Decide which results are worth opening. Snippets are often enough to establish
   a claim and a source; only fetch in full the sources that will anchor a
   finding.
3. `WebFetch` those. If a fetch fails and the page genuinely matters, fall back
   to `bd_search.py`.
4. **Log every retrieval** with `sources.py log`, giving the sub-question as
   `--angle`, the correct `--kind`, and - for anything you intend to cite - the
   sentence that made it worth citing as `--quote`.

### Capture the quote as you read, not afterwards

The quote is the sentence you would point at if someone asked "what makes you say
that". Take it at the moment you decide the source is worth citing; reconstructing
it later means refetching, and in six months the page may not say the same thing
or exist at all.

Around half of real findings carry no figure, so for those the quote is the only
evidence recorded. The gate fails a finding that has neither a traceable figure
nor a quote on any of its cited sources - not because the finding is wrong, but
because nothing about it can be checked.

### Getting the source kind right

`sources.py kinds` prints the vocabulary and which claims each kind suits. The
kind is inferred from the URL when omitted, but inference returns `unknown` for
anything it does not recognise, and `unknown` scores below commentary. Pass
`--kind` when you know.

The distinction that matters most is **vendor primary versus vendor marketing**.
A pricing page and a "why customers love us" page are both on the vendor's
domain; one is the best evidence available for what something costs, the other is
the worst evidence available for whether it is any good.

### Depth changes what you reach for, not how much you write

- **quick**: SERP snippets. Fetch only to pin a specific figure.
- **standard**: direct-fetch the top sources per finding.
- **deep**: get a primary source for every finding. The vendor's own pricing
  page, not the analyst's summary of it. The filing, not the article about the
  filing. This is where Bright Data usage rises, because primary sources are
  disproportionately the ones that block you.

### Stop conditions

Stop gathering on a sub-question when a further search returns nothing new, or
when the sub-question is answered by primary evidence. Do not gather to a quota.

---

## Phase 3: Challenge

A finding that has only been supported has not been tested.

### Look for the disconfirming case

For each finding, run at least one search designed to find evidence **against**
it, using the falsifiers from Phase 1. Search the negative directly: "X
limitations", "why we stopped using X", "X alternatives", "X price increase".

If disconfirming evidence exists it belongs inside the finding, not in a caveats
paragraph at the end. A finding that survives a real attempt to break it is worth
more than one that was never attacked, and the reader should be able to see the
attempt.

At **quick** level this phase is grouping only, no searches.

### Group the sources

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/independence.py groups --tsv "$OUT/$BASE.tsv"
```

Three things collapse into one voice: the same page reached twice, every page on
one party's own domains, and near-duplicate headlines across outlets. What comes
out is the number of **independent groups** actually behind the work.

### Check corroboration per finding

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/independence.py check \
  --tsv "$OUT/$BASE.tsv" --urls "https://a.example/x,https://b.example/y" --min 2
```

Corroboration is the number of independent groups reached from **different
angles**. Five sources from one line of enquiry score 1, however many distinct
publishers they span, because our own fan-out produced all five.

If a finding you believed was strong scores 1, that is the system working. Either
go and find a genuinely different angle, or downgrade the confidence.

### At deep level: the origin audit

For any finding claiming Strong, check whether the corroborating sources trace
back to a single origin. Three articles citing the same analyst estimate is one
estimate. Grouping catches near-duplicate headlines but not "everyone is quoting
the same figure from the same place", so read the sources and see where the
number came from.

---

## Phase 4: Write

Pick the format (`SKILL.md` says which per level), then write section by section,
each write under roughly 2,000 words so no single tool call risks truncation.

### Findings carry their own claim

`### Finding 3: Microsoft is the biggest risk, but the gate is 96% wide` is worth
more than `### Finding 3: Platform risk`. State the finding in the heading; the
section then supports it.

### Assign confidence honestly

The band follows from the evidence, not from how much you would like the finding
to be true:

| Band | Requires |
|---|---|
| **Strong** | Primary-tier evidence for the central claim, and corroboration of 2 or more |
| **Moderate** | Primary evidence but a single group, or secondary evidence with corroboration of 2 or more |
| **Weak** | Commentary only, or everything traces to one origin |
| Below floor | Nothing above marketing or hearsay tier, or the only voice is the subject describing itself |

Below-floor material does not become a finding. It can be a sentence in
Limitations.

If **every** finding is below floor, write the "could not answer" shape described
in `SKILL.md`. Naming the closest sub-floor signal matters: it tells the reader
the search actually ran, and it usually suggests the narrower question that would
work.

### Citation discipline

- Every factual claim carries `[N]` in the same sentence.
- Never write "research suggests", "studies show" or "experts believe". Name the
  source or drop the claim.
- Label inference as inference. "This suggests" is fine; presenting it as fact is
  not.
- If you could not find something, say so. "No source addresses X directly" is a
  finding. A fabricated citation is a defect the gate will catch anyway.
- Prose first. Bullets are for genuine lists, not for delivering content.

### Then gate it

Run `check.py` at your level, fix what it reports, re-run. After two failed
cycles, stop and tell the user what is wrong rather than continuing to patch.
