# Evaluations

## Contents

- [Why this exists](#why-this-exists)
- [The protocol](#the-protocol)
- [Scoring](#scoring)
- [How much to run](#how-much-to-run)
- [What these four cases cover](#what-these-four-cases-cover)

## Why this exists

Legwork asserts that its methodology works. Until this directory existed, it had
no evidence for that claim about itself.

The scripts have unit tests, and those tests prove the maths is right. They
cannot prove the skill changes what an agent does, which is a different question
and the only one that matters. A rule that is correct and never fires is
indistinguishable from a rule that is absent, and legwork has now been measured
producing exactly that outcome: reports that assert their level while failing
their own gate.

Every case in `evals.json` reproduces a failure that actually happened. None
were invented to fill the file.

## The protocol

Each case runs twice.

**The skill arm.** A fresh agent with legwork installed, given the case's
`prompt` verbatim and nothing else.

**The baseline arm.** A fresh agent with legwork *not* installed, given the same
prompt.

The baseline is not decoration. It is the only thing that catches the skill
being confidently wrong: an agent working without legwork will sometimes reach a
source, a capability or an answer that legwork's instructions assert does not
exist. A skill arm that beats a baseline arm on rigour while losing to it on
facts is a skill that has taught the agent something false.

Run both arms on every model the skill is expected to run on. Legwork's own
model carve-out - cheap models for snippet gathering, the orchestrator's model
for rebuilding an enumeration - is currently borrowed from someone else's
benchmark and has never been checked here. Case 2 is the one that tests it.

## Scoring

Score each entry in `expectations` as satisfied, absent, or contradicted.

Read the matched output before recording a result. Keyword matching is signal,
not conclusion: the same word can appear in both arms meaning different things,
and a phrase can be absent while the behaviour is plainly present. Spot-read
enough of each arm to know which happened.

Record three things per run, because they move independently and a change that
improves one often costs another:

| Recorded | Why |
|---|---|
| Expectations satisfied | Did the skill change behaviour |
| Wall-clock and tool calls | Did it change behaviour affordably |
| Gate result | Did the run's own machinery actually run |

An expectation that no arm ever satisfies is either badly written or describes a
rule the skill states but cannot deliver. Both are findings. Fix the expectation
or fix the skill; do not quietly drop the row.

## How much to run

Route depth by asking how the change could fail, not by running everything every
time.

A single-sentence factual correction with direct evidence behind it does not
need a paired eval on four cases; running one is how a measurement habit turns
into the same unenforced ritual it was meant to replace. A change to Frame,
Gather, Challenge or the gate does need one, because those are the parts whose
failure is invisible in the output.

Four cases is the working set, above Anthropic's floor of three. Grow it when a
new failure is observed in a real run, not on a schedule.

## What these four cases cover

| # | Case | The failure it reproduces |
|---|---|---|
| 1 | `gate-compliance-on-a-finished-run` | A run that reports compliance it did not achieve |
| 2 | `rebuild-an-enumeration-rather-than-lifting-it` | One aggregator table passed off as many sources |
| 3 | `answer-from-the-index-instead-of-researching-again` | Paying full price to re-answer a settled question |
| 4 | `return-nothing-rather-than-hedged-length` | Padding when nothing cleared the floor |

Case 1 is the most important. It measures whether the machinery runs at all,
and every other case's result is uninterpretable if it does not.

## Runs

| Run | Model | Result |
|---|---|---|
| [2026-08-13](runs/2026-08-13-sonnet-baseline.md) | Sonnet, both arms | First baseline. Cases 1 and 2 discriminate strongly, 4 moderately, 3 weakly |

### What the first run changed

Three of the four cases were originally built on the assumption that legwork's
contribution is diligence - opening primary sources, refusing to fabricate,
disclosing uncertainty. **The baseline arms did all three unprompted.** Those
are now recorded as `precondition` fields rather than scored expectations,
because an expectation both arms satisfy measures the model, not the skill.

What separates the arms is narrower and firmer: how far the run *reaches* when
primary sources block automated fetching, what happens to a figure that cannot
be sourced to a page anyone opened, whether the output is in a shape a machine
can check, and whether the run survives for the next session to reuse.

The run also found a defect in the gate itself - `check.py` defaulted to report
format and failed a brief for four sections a brief never has - which is exactly
what evals are for and what no amount of re-reading the source had caught.

**Known harness gap.** The runner must copy `docs/research/` into the eval
output base. Forbidding writes to the real one makes legwork's refresh-in-place
path unreachable, which contaminates case 3.
