# The retrieval subagent brief

Retrieval is the one phase worth parallelising. It is also the phase where a
vague brief costs the most, because a subagent that guesses wrong produces
evidence that looks fine and is not.

**A subagent has zero context.** It cannot see this skill, the conversation, the
decision being made, or what the other subagents are doing. Everything it needs
goes in the brief. If a brief could be misread, it will be.

One subagent per angle is the natural split. It also keeps angle attribution
honest, because each agent only ever writes its own angle.

## Which model

Retrieval is mechanical, so it does not need the orchestrator's model - but this
is not unconditional, and getting it wrong quietly costs recall.

- **Snippet gathering, SERP triage, pinning a figure on a page you already know
  about**: a cheap model is fine. Pass the override explicitly every time; never
  let a subagent inherit the session model by accident.
- **Deep-level primary-source work, and anything that rebuilds an enumeration**
  (every competitor, every plan, every release): use the orchestrator's model.
  Rebuilding a list means opening a dozen pages and keeping every figure exact
  across all of them, and small models drop rows on exactly that task while
  reporting success.

The tell is the *shape* of the angle, not its importance. "What does Acme charge"
is cheap. "What does every vendor in this segment charge" is not.

## The brief

Fill every `{placeholder}`. Nothing here is optional: each line is in the template
because leaving it out produced a specific, repeated failure.

```
You have zero prior context. Everything you need is in this brief.

Today's date is {YYYY-MM-DD}. Use that year in searches; do not rely on your own
sense of what year it is.

## Your angle

{the single sub-question this agent is answering, verbatim from Phase 1}

This is the only question you are answering. Do not broaden it, and do not answer
a neighbouring question because it came up.

## Effort

{n} to {m} searches. {"This is one narrow fact - stop once you have it, from two
independent sources." | "This is a multi-option comparison - spread the effort
across the options rather than going deep on the first one."}

## How to work

1. Search, year-pinned. Read the results before opening anything.
2. Open the sources that would actually settle the question. Snippets are enough
   to establish that something exists; open the page when a figure or an exact
   wording depends on it.
3. Where the answer is a LIST - every vendor, every plan, every release - open the
   listed items themselves and rebuild the list from them. A table copied out of
   one roundup is one source, not one per row. Return the roundup too, marked as
   such, but do not let it stand in for the items.
4. Take the sentence that made each source worth citing, verbatim, as you read it.
   Do not reconstruct it afterwards.
5. Record the publication date of every source. If a page carries no date, say so
   rather than guessing one.

## What to return

One JSON object per source, and nothing else:

{"url": "...", "kind": "...", "angle": "{the angle above, unchanged}",
 "date": "YYYY-MM-DD or empty", "title": "...", "quote": "the verbatim sentence"}

Then one final object recording what you could NOT establish:

{"gaps": ["what you searched for and did not find",
          "any reading of the evidence that points the other way"]}

The gaps object is required and must not be empty. "Nothing found on X" is a
result the orchestrator needs; silence reads as "X was never asked".

## Rules

- Never invent a URL. Every URL you return must have come from an actual result.
- Never return a URL you did not open when the claim depends on the page's exact
  wording or figures.
- No narrative summary, no recommendations, no reasoning about what it all means.
  That is the orchestrator's job and your prose will not be used.
- `kind` must be one of the values from `sources.py kinds`. If none fits, use
  `unknown` rather than the closest-looking one.

Your final message is the JSON objects above and nothing else. Anything before the
first object is discarded.
```

## Why the last line is the last line

Models weight the final instruction heavily, and a subagent that ends its brief on
anything else tends to return its working notes wrapped around the data. Keep the
return-only rule literally last.

## When the return comes back

The subagent's structured output is not evidence yet. Before logging any of it:

- **Strip anything that is not a JSON object.** Do not push a preamble downstream.
- **Check the gaps object exists and is not empty.** An empty gaps list on a
  non-trivial angle almost always means the agent never looked for the negative
  case. Fill it yourself with one focused search, or re-spawn.
- **Check the angle string is unchanged.** An agent that rewrote its own angle
  breaks the corroboration count, which is the one thing legwork cannot recover
  after the fact.
- **Check dates are present.** Undated sources are the gate's problem later; they
  are cheaper to fix now, while the page is still open.

Then log each row with `sources.py log` and work from the log. **Never paste a
subagent's transcript into the synthesis.**

Small gaps are cheaper to fill yourself than to re-spawn for. Re-spawn when a
whole angle came back thin, and name the specific gap in the new brief.
