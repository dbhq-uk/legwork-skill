# [The answer as a statement, not the topic]

<!--
REPORT FORMAT - the deliverable for deep, and for standard when the question warrants
it.

WHAT THIS IS: the full shape, for a decision worth documenting. No word target. Stop
when the question is answered - a question fully answered in 3,000 words ships at
3,000 words. Padding to a length band is the failure this format is most prone to.

VALIDATE WITH:
  python3 scripts/check.py --report [path] --format report --level [standard|deep]

TITLE GUIDANCE: lead with the answer. Not "Plugin Distribution Research" but "Where to
publish the DBHQ plugins, and why the official marketplace is not it".

IF NOTHING CLEARS THE FLOOR: do not use this template. Use the "could not answer"
shape at the bottom of this file.
-->

*[level] · [N] angles · [N] sources ([N] via Bright Data) · [N] disconfirming searches · [N] findings downgraded, [N] dropped below floor*

## Executive Summary

[200-400 words. The answer, what it rests on, and what would overturn it. Someone who
reads only this section should be able to act. Load-bearing citations included [1][2];
this is a summary of evidence, not a preamble to it.]

## Introduction

[Scope and framing. Cover:

- **The decision.** Not the topic - the decision this research exists to settle. If it
  was inferred rather than stated, say so here.
- **The sub-questions.** The angles the research actually ran, named, so the reader can
  see what was and was not asked.
- **Assumptions.** Any high-materiality assumption made in scoping, stated plainly
  rather than left implicit.
- **What would change the answer.** The falsifiers. These are what Challenge hunted
  for, and they set up the Limitations section.]

## Findings

### Finding 1: [The finding as a claim someone can act on]

**Confidence: Strong|Moderate|Weak** - [one sentence naming what backs it: "the vendor's
own pricing page, plus two independent user reports from separate searches", or "three
articles that all cite the same estimate"]

[Prose. Lead with the claim, then the evidence. Exact figures embedded in sentences with
their citation in the same sentence: "the listed price is $30 per user per month [1]",
never "pricing is high".

Where a disconfirming search found something, it goes here, in the finding it bears on.
A finding that visibly survived an attempt to break it is worth more than one that was
never attacked.

Where sources disagree, say so, and say which you weight more heavily and why.]

### Finding 2: [...]

**Confidence: ...** - [...]

[...]

<!-- Findings are as many as the evidence supports. Anything below the floor is not a
     finding - it belongs in Limitations as a sentence. Do not promote a weak signal to
     a numbered finding to fill the section. -->

## Synthesis

[What the findings mean together that none of them says alone. This is your analysis,
not the sources', and it must be marked as such: "this suggests", "taken together".

The useful move here is usually the second-order one - the implication none of the
sources states outright because each only saw its own part.]

## Limitations

[Honest and specific. Start from the falsifiers named in the Introduction: which of them
could you not test, and what would it take?

Then the gaps: what could not be verified and why (paywalled, no primary source,
contested); where the evidence is thin (single-group claims, no counter-perspective
found); recency, and how fast this field moves; bias in the source pool (all vendor
pages, all US-centric, all proponents).

Anything that fell below the floor goes here, named, in a sentence.

"No source addresses X directly" is a legitimate and valuable statement. Write it rather
than fabricating coverage.]

## Recommendations

[What to do, in priority order, each traceable to a finding. Say what would change each
recommendation - a recommendation with no stated trigger for reversing it is an opinion
wearing a suit.

Distinguish what to do now, what to do if a named condition holds, and what to stop
worrying about.]

## Bibliography

<!--
ZERO TOLERANCE. Every [N] cited above appears here, individually, in full.
NO ranges ([3-9]). NO "additional sources". NO truncation. NO "etc."

Every URL here must also appear in the run's .tsv fetch log - the gate checks it, and a
citation to a page nobody opened is a fabricated citation.

Format: [N] Author/Org (Year). "Title". Publication. URL
-->

[1] [Author/Org] (Year). "[Title]". [Publication]. [URL]
[2] ...

---

<!--
=============================================================================
THE "COULD NOT ANSWER" SHAPE

Use this INSTEAD of everything above when no finding cleared the floor. Do not pad, do
not lower the bar, and do not ship weak findings dressed as strong ones.

An honest empty answer preserves trust in every run that does produce findings. Naming
the closest sub-floor signal matters: it shows the search actually ran, and it usually
points at the narrower question that would work.
=============================================================================

# [The question, as asked]

*[level] · [N] angles · [N] sources ([N] via Bright Data) · [N] disconfirming searches*

## Could not answer

[What was searched, across which angles, and why nothing held. Be specific: "every
source on pricing traced back to one vendor's marketing", "no independent practitioner
evidence surfaced across six angles". The reader should finish this paragraph knowing
the work was done.]

Closest thing found: [the strongest sub-floor signal, named, with why it fell short.]

## Bibliography

[1] ...
-->
