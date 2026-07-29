# [Question as a statement - the answer, not the topic]

<!--
BRIEF FORMAT - the default deliverable for quick, and for standard when the question
is small.

WHAT THIS IS: a findings memo, 800-2,500 words. It answers the question and shows its
receipts. It is NOT a shrunken formal report: it drops the Executive Summary /
Introduction scaffolding entirely, because at this length the scaffolding IS the
content.

WHAT IT KEEPS (non-negotiable - brief drops ceremony, never rigour):
  - Every factual claim carries an immediate [N] citation
  - Every finding states its confidence
  - Complete bibliography: every [N] used, no ranges, no placeholders, no truncation
  - Honest limitations
  - Prose-first (>=80%); bullets only for genuinely enumerable things

VALIDATE WITH:
  python3 scripts/check.py --report [path] --format brief --level [quick|standard|deep]

WHEN TO USE THE FULL REPORT INSTEAD: deep level, or when the user asks for "a full
report" / "write it up properly". Then use report_template.md.

TITLE GUIDANCE: lead with the finding, not the subject. Not "Vector Database
Comparison" but "Postgres+pgvector covers our scale; a dedicated vector DB doesn't pay
for itself until ~10M embeddings".
-->

*[level] · [N] angles · [N] sources ([N] via Bright Data) · [N] disconfirming searches · [what changed]*

**Question:** [The research question, verbatim as asked]
**Scope:** [What's in, what's out. Assumptions made. 1-2 sentences.]

---

## Answer

[2-4 sentences. The direct answer to the question, with the load-bearing citations [1][2].
If the honest answer is "it depends", say what it depends on. If the evidence doesn't
support a confident answer, say that here rather than burying it in Limitations.]

---

## Findings

### Finding 1: [The finding as a claim, not a topic label]

**Confidence: Strong|Moderate|Weak** - [one sentence naming what backs it, in plain
English: "the vendor's own pricing page, plus two independent user reports from separate
searches", or "three articles that all cite the same estimate"]

[150-400 words of prose. Lead with the specific claim, then the evidence that supports
it. Exact numbers, embedded in sentences: "throughput fell 34% above 500 concurrent
connections [3]" - not "performance degraded significantly". Every factual sentence
gets its [N] in the same sentence.

Where sources disagree, say so and say which you weight more heavily and why. A finding
that names its own uncertainty is worth more than one that hides it. If a disconfirming
search turned something up, it goes here, in the finding it bears on - not in a
caveats paragraph at the end.]

### Finding 2: [Second finding]

**Confidence: ...** - [...]

[...]

### Finding 3: [Third finding]

**Confidence: ...** - [...]

[...]

<!-- 3-6 findings. More than 6 and you're writing a report - switch formats. Fewer
     than 3, say so honestly rather than padding. Anything below the floor is not a
     finding: put it in Limitations as a sentence. -->

---

## So What

[200-500 words. The part the reader actually acts on.

- What follows from the findings for the reader's specific situation?
- What should they do, and what would change that recommendation?
- What's the second-order implication nobody in the sources states outright?

This is your synthesis, not the sources' - so mark it as such. "This suggests..." /
"On the evidence above, the reasonable move is..." Distinguish clearly between what the
sources say and what you conclude from them.]

---

## Limitations

[2-4 sentences, honest and specific. Start from the falsifiers you named in Phase 1 -
those are the real limitations, not generic hedging. Then:

- What couldn't be verified, and why (paywalled, no primary source, contested)
- Where the evidence is thin (single-group claims, no counter-perspective found)
- Recency: is anything here likely to be stale, and how fast does this field move?
- Any bias in the source pool (all vendor pages, all US-centric, all proponents)

"No sources found addressing X directly" is a legitimate and valuable finding. Say it
rather than fabricating coverage.]

---

## Bibliography

<!--
ZERO TOLERANCE. Every [N] cited above appears here, individually, in full.
NO ranges ([3-9]). NO "additional sources". NO truncation. NO "etc."
A brief with a broken bibliography is worse than no brief: it looks sourced but isn't.

Every URL here must also appear in the run's .tsv fetch log - the gate checks it, and a
citation to a page nobody opened is a fabricated citation.

Format: [N] Author/Org (Year). "Title". Publication. URL
-->

[1] [Author/Org] (Year). "[Title]". [Publication]. [URL]
[2] ...
[3] ...
