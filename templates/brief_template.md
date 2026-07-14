# [Question as a statement — the answer, not the topic]

<!--
BRIEF FORMAT — the default deliverable for quick and standard modes.

WHAT THIS IS: a findings memo, 800-2,500 words. It answers the question and shows its
receipts. It is NOT a shrunken formal report: it drops the Executive Summary /
Introduction / Methodology-Appendix scaffolding entirely, because at this length the
scaffolding IS the content.

WHAT IT KEEPS (non-negotiable — brief drops ceremony, never rigor):
  - Every factual claim carries an immediate [N] citation
  - Complete bibliography: every [N] used, no ranges, no placeholders, no truncation
  - Honest limitations
  - Prose-first (>=80%); bullets only for genuinely enumerable things

VALIDATE WITH:
  python scripts/validate_report.py --report [path] --format brief
  python scripts/verify_citations.py --report [path] --offline

WHEN TO USE THE FULL REPORT INSTEAD: deep/ultradeep modes, or when the user asks for
"a full report" / "write it up properly". Then use report_template.md.

TITLE GUIDANCE: lead with the finding, not the subject. Not "Vector Database
Comparison" but "Postgres+pgvector covers our scale; a dedicated vector DB doesn't pay
for itself until ~10M embeddings".
-->

**Question:** [The research question, verbatim as asked]
**Scope:** [What's in, what's out. Assumptions made. 1-2 sentences.]
**Mode:** [quick|standard] · **Sources:** [N] · **Date:** [YYYY-MM-DD]

---

## Answer

[2-4 sentences. The direct answer to the question, with the load-bearing citations [1][2].
If the honest answer is "it depends", say what it depends on. If the evidence doesn't
support a confident answer, say that here rather than burying it in Limitations.]

---

## Findings

### 1. [Finding as a claim, not a topic label]

[150-400 words of prose. Lead with the specific claim, then the evidence that supports
it. Exact numbers, embedded in sentences: "throughput fell 34% above 500 concurrent
connections [3]" — not "performance degraded significantly". Every factual sentence
gets its [N] in the same sentence.

Where sources disagree, say so and say which you weight more heavily and why. A finding
that names its own uncertainty is worth more than one that hides it.]

### 2. [Second finding]

[...]

### 3. [Third finding]

[...]

<!-- 3-6 findings. If you have more than 6, you're probably writing a report — switch
     formats. If you have fewer than 3, say so honestly rather than padding. -->

---

## So What

[200-500 words. The part the reader actually acts on.

- What follows from the findings for the reader's specific situation?
- What should they do, and what would change that recommendation?
- What's the second-order implication nobody in the sources states outright?

This is your synthesis, not the sources' — so mark it as such. "This suggests..." /
"On the evidence above, the reasonable move is..." Distinguish clearly between what the
sources say and what you conclude from them.]

---

## Limitations

[2-4 sentences, honest and specific. Name the actual gaps:

- What couldn't be verified, and why (paywalled, no primary source, contested)
- Where the evidence is thin (single-source claims, no counter-perspective found)
- Recency: is anything here likely to be stale, and how fast does this field move?
- Any bias in the source pool (all vendor blogs, all US-centric, all proponents)

"No sources found addressing X directly" is a legitimate and valuable finding. Say it
rather than fabricating coverage.]

---

## Bibliography

<!--
ZERO TOLERANCE. Every [N] cited above appears here, individually, in full.
NO ranges ([3-9]). NO "additional sources". NO truncation. NO "etc."
A brief with a broken bibliography is worse than no brief: it looks sourced but isn't.

Format: [N] Author/Org (Year). "Title". Publication. URL (Retrieved: YYYY-MM-DD)
Generate with: python scripts/citation_manager.py export-bibliography --dir [folder]
-->

[1] [Author/Org] (Year). "[Title]". [Publication]. [URL] (Retrieved: [YYYY-MM-DD])
[2] ...
[3] ...
