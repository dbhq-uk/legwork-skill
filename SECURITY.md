# Security

## Reporting a vulnerability

Email <dan@dbhq.uk> rather than opening a public issue. Include what you found,
how to reproduce it, and what an attacker could do with it. You will get a first
response within 48 hours.

## What this skill does

Legwork researches a question and produces a cited memo. Research means reading
the public web, so unlike the other skills in this collection it makes outbound
requests by design.

### Network

**Yes, and that is the point.** Two paths, in this order:

1. **Your agent's built-in `WebSearch` and `WebFetch`.** Preferred, and used for
   the overwhelming majority of work. No setup, no key, no per-request cost. The
   requests go wherever the research leads - arbitrary public sites
2. **Bright Data, optionally, as a fallback.** `bd_search.py` is used only when
   the built-in tools genuinely cannot do the job: bot-blocked, paywalled or
   JS-heavy pages, Reddit threads, and geo-specific or vertical SERPs

Bright Data is a third party, billed per record, and requires an API key **you**
supply. If you never configure one, that path is simply unavailable and the
skill uses the built-in tools alone.

### What leaves your machine

Search queries and the URLs being fetched. The research question itself reaches
the search provider as a query string. Do not run Legwork on a question whose
wording is itself confidential - the question is the thing most likely to leak.

### On disk

- Installs into `~/.claude/skills/legwork` or `~/.codex`, depending on the agent
- Writes the findings memo where you ask it to
- Stores no cache of fetched pages between runs

### Credentials

Only a Bright Data API key, and only if you choose to use that fallback. It is
read from the environment; the skill does not write it to disk.

## Evidence handling

Every claim in the output states how well it is supported, and the skill says
when the evidence cannot settle a question. That matters for security review
too: it does not launder a single blog post into a confident assertion.
