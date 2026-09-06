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

**Yes, and that is the point.** Four paths, in this order:

1. **Your agent's built-in `WebSearch` and `WebFetch`.** Preferred, and used for
   the overwhelming majority of work. No setup, no key, no per-request cost. The
   requests go wherever the research leads - arbitrary public sites
2. **`fetch.py`, a direct request from your machine.** One page per invocation,
   on explicit instruction, with a browser user agent. No cookies are sent or
   stored, no credentials are read, no JavaScript is executed, and nothing is
   cached between runs. It does **not** consult `robots.txt`: it opens a single
   named page the way a browser would, rather than crawling. That is a
   deliberate choice, stated here so you can disagree with it - if you need
   robots-respecting behaviour, remove `fetch.py` from the ladder in
   `SKILL.md` and the run falls back to `WebFetch`
3. **`platforms.py`, public APIs that need no key.** Hacker News, Stack
   Exchange, GitHub, npm, PyPI, Wikipedia, Google News, a site's own RSS feed,
   and the Internet Archive. Your query reaches those services. `GITHUB_TOKEN`
   is used if it is already in your environment; it is never required, never
   logged, and never written to disk
4. **Bright Data, optionally, as a fallback.** `bd_search.py` is used only when
   the paths above genuinely cannot do the job: bot-blocked, paywalled or
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
- Writes page text to a temporary directory (`$TMPDIR/legwork/`) during a run,
  so figures and quotes can be checked against the page. It is scratch: it never
  enters the output folder, and the fetch log stores only the quote and the
  numeric tokens
- Stores no cache of fetched pages between runs

### Credentials

Only a Bright Data API key, and only if you choose to use that fallback. It is
read from the environment; the skill does not write it to disk.

## Evidence handling

Every claim in the output states how well it is supported, and the skill says
when the evidence cannot settle a question. That matters for security review
too: it does not launder a single blog post into a confident assertion.
