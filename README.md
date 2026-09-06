<div align="center">

<img src="assets/logo.svg" alt="Legwork skill for Claude Code, by DBHQ" width="420">

# Legwork

**Multi-source research that shows its working - every claim tied to a source you can check**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude_Code-Plugin-blueviolet)](https://code.claude.com/docs/en/plugins)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20WSL-lightgrey)]()

A free, open-source tool by [DBHQ](https://dbhq.uk)

</div>

---

Research that settles a decision. Ask a real question, get a memo where every factual claim carries an inline `[N]`, every finding states how well it is supported, and a claim that cannot be supported does not ship. Legwork picks a level, announces it, and starts - no questionnaire before it will do anything.

## What makes it different

**A source is judged by the claim it backs, not by its domain.** A vendor's own pricing page is the best evidence available for what something costs and the worst evidence available for whether anyone likes it. Legwork scores fitness per claim kind rather than keeping a list of respectable websites, and recency decays at a rate set by the claim: a two-year-old price is worthless, a two-year-old filing is fine.

**Three sources only count if they could have disagreed.** Pages on one vendor's domains are one voice. Syndicated copies of one wire story are one story. And because Legwork's own search fan-out inflates the number of sources behind a finding, corroboration is counted on the layer it does not amplify: independent groups reached from *different search angles*. Five sources from one query score one confirmation, however many publishers they span.

**It can tell you it could not answer.** If nothing clears the evidence floor, the run says so and names the closest thing it found, rather than producing four thousand hedged words. An honest empty answer is a result.

**Free by default, paid only when needed.** Retrieval runs on the host's built-in `WebSearch` and `WebFetch`. The Bright Data CLI is a *fallback*, used only where the built-ins genuinely cannot do the job - bot-blocked or paywalled pages, Reddit threads, geo-specific SERP. A run against ordinary sources makes **zero** paid calls.

**It does not ask permission to begin.** It infers a level, says which one it picked, and goes. Redirect it mid-run if it guessed wrong; that costs far less than a blocking question on every research request.

**The gates are real.** `check.py` fails a report that cites a page nobody opened, cites a page it only ever saw in a search result, quotes a figure that appears on no page that was fetched, rests a finding on nothing anyone recorded, or claims strong support from a single line of enquiry. The suite ships fixtures that are *supposed* to fail - one per failure mode - so the gate is proved to bite rather than assumed to.

**A quote is checked against the page it came from.** Pages opened by `fetch.py` leave their text on disk for the run, so a recorded quote is verified verbatim and a misquote is reported at the moment it is logged, not left for a reader to discover.

## Install

### As a Claude Code plugin (recommended)

```
/plugin marketplace add dbhq-uk/marketplace
/plugin install legwork@dbhq
```

### Any agent (Cursor, Copilot, Windsurf, Gemini, Cline and more)

```bash
npx skills add dbhq-uk/legwork-skill
```

The [skills.sh](https://skills.sh) CLI installs into whichever agent directories it finds, so this works outside Claude Code and Codex too.

### Local install (Claude Code or Codex)

```bash
git clone https://github.com/dbhq-uk/legwork-skill.git
cd legwork-skill
./install.sh              # Claude Code: symlinks into ~/.claude/skills (edits are live)
./install.sh --with-hook  # ...and gate every report automatically (see below)
./install-codex.sh        # Codex: installs into ~/.codex/skills
```

**`--with-hook` is the one worth taking.** It registers a `Stop` hook that runs the gate on any legwork report written during a session and refuses to end the turn on one that fails. Without it the gate fires only when the agent remembers to run it, at the end of a long run - and measured against real runs, that is often enough not to happen. It edits `~/.claude/settings.json`, backing it up first, which is why it is opt-in rather than the default.

**No virtualenv, no packages.** Every script is Python standard library only, on 3.9 or newer. That is the whole dependency list.

Optional, for the fallback provider:

```bash
npm install -g @brightdata/cli   # or: curl -fsSL https://cli.brightdata.com/install.sh | sh
brightdata login                 # or: export BRIGHTDATA_API_KEY=...
```

Setup succeeds without it - you simply lose fallback scraping.

## Usage

```
legwork: tradeoffs of pgvector vs a dedicated vector DB at our scale
research in deep mode: regulatory exposure of shipping this feature in the EU
quick: what changed in the EU AI Act in the last six months?
```

Add `brief` or `full report` to override the deliverable format.

### Levels

Depth raises rigour. It never raises length.

| Level | Duration | Format | What the extra effort buys |
|---|---|---|---|
| quick | 3-5 min | brief | SERP snippets; fetch only to pin a figure |
| standard **(default)** | 8-12 min | brief or report | Direct-fetch the top sources per finding; one disconfirming search each |
| deep | 20-40 min | report | A primary source for every finding, a per-finding disconfirming pass, and an origin audit |

Set a different default with `export LEGWORK_DEFAULT_MODE=deep`.

## Search backend

Two ladders, free rungs first.

**To search:**

| Situation | Provider |
|-----------|----------|
| Every angle, three query variants | `WebSearch` (free) |
| The answer is a record a platform holds - a thread, a package, a repository, a dated news item, a vendor's changelog | `platforms.py` (free, keyless) |
| Thin after three variants, or geo-specific | Bright Data SERP on a second engine, with `--country` and `--language` |
| Two engines still thin | Bright Data `-m discover`, intent-ranked |

**To open a page:**

| Situation | Provider |
|-----------|----------|
| Every page you intend to cite | `fetch.py` (free, direct, returns page text) |
| Blocked and not worth paying for | `WebFetch` (free) |
| Bot-blocked, paywalled, 403 | Bright Data `-m scrape` |
| A client-rendered shell | Bright Data `-m render`, a real browser |
| A platform that blocks everything above | Bright Data `-m pipeline`, billed per record. Reddit is the one where this is the only route |

**The ten free platforms** (`platforms.py list`): Hacker News, Stack Exchange,
GitHub repositories and issues, npm, PyPI, Wikipedia, Google News with real
country and language control, any site's own RSS or Atom feed, and the Wayback
Machine. Every row carries the platform's own numbers - points, weekly
downloads, stars, answer counts - which is the evidence a search snippet cannot
give you.

On any failure the wrapper emits JSON to stderr and exits non-zero, and the skill falls back to the built-ins. Auth and quota failures map to exit code `2`, so you are told to re-authenticate rather than left silently degraded.

Scrapes are capped at `--max-chars 8000` by policy (the wrapper's own default is 20000). A research run reads dozens of pages and almost none of them need twenty thousand characters in context to yield the sentence you are after.

Retrieval subagents run on a cheaper model than the orchestrator and return structured evidence only - `{url, kind, angle, date, title, quote}` - never prose, and never a transcript pasted into the synthesis. One agent per search angle, which also keeps the angle attribution honest.

## Output

Written to `<output-base>/[Topic]_Research_[YYYYMMDD]/`, where `<output-base>` is `$LEGWORK_OUTPUT`, else `<git-root>/docs/research/`, else `$PWD/docs/research/`.

Two files, sharing the folder's base name so they group and sort together:

```
Outlook_Email_SaaS_Research_20260728/
  Outlook_Email_SaaS_Research_20260728.md     the deliverable
  Outlook_Email_SaaS_Research_20260728.tsv    the fetch log
```

**Markdown only.** No HTML, no PDF.

**And the answer comes back in the conversation**, not only as a path: the
receipt line, a brief in full or a report's summary and finding headings with
their confidence bands, then the file for the full text and the evidence log.

The fetch log is one row per retrieval: URL, source kind, the search angle that surfaced it, the query that found it, how it was retrieved, the numeric tokens found on the page, and one verbatim sentence - the line that made the source worth citing.

That last field earns its place twice. Around **half of real findings carry no figure at all**, so without a quote they would be backed by nothing but proof that somebody opened the page; the gate now fails a finding that has neither a traceable figure nor a quote on any source it cites. And it is the only part of the evidence that survives the page changing or going dead six months later.

## Scripts

All standard library only, Python 3.9+.

| Script | Purpose |
|--------|---------|
| `fetch.py "<url>" --find TERM` | Open a page directly and keep its text; reads the publication date; exits 3 on a block or a client-rendered shell |
| `platforms.py list \| search --on X` | Ten free platform-native sources, returning records rather than pages about them |
| `sources.py kinds \| log \| receipt \| score \| stale \| resume` | The source-kind vocabulary, the fetch log, the retrieval receipt, fitness scoring per claim kind, staleness, resume |
| `independence.py groups \| check \| portfolio` | Collapse sources into independent voices; angle-aware corroboration; run-wide concentration |
| `check.py --report P --level L` | The shippability gate: structural, evidence, independence, matrix |
| `finish.py --report P --level L` | Gate, staleness sweep and index filing in one call |
| `index.py add \| list` | The research index across runs |
| `matrix.py check --report P` | Comparison-matrix completeness |
| `bd_search.py` | Bright Data fallback: SERP on a second engine, intent search, scrape, browser render, pipelines |

## Tests

```bash
python3 -m pytest skills/legwork/tests/ -v      # no network required
```

CI runs the suite across Python 3.9-3.13, plus an end-to-end smoke job that pushes the shipped fixtures through the real gates in both directions - asserting that sound deliverables pass *and* that each broken one is rejected for its own specific reason - runs a full log-to-gate lifecycle, and asserts setup succeeds with no Bright Data CLI present.

One CI job exists solely to guard the property the independence layer is for: six distinct publishers logged against a single search angle must still fail a corroboration bar of two. A unit test that calls the gate directly cannot catch a gate that never binds in production.

## Evaluations

Tests prove the maths is right. They cannot prove the skill changes what an agent does, and a rule that never fires is indistinguishable from a rule that is absent.

[`evals/`](evals/) holds four behaviour cases in the standard `{prompt, expected_behavior[]}` shape, each reproducing a failure observed in a real run rather than an imagined one: a run that reports gate compliance it did not achieve, an enumeration lifted whole from one aggregator, a settled question researched again from scratch, and padding where nothing cleared the floor.

Each case runs twice - once with the skill and once without. The baseline arm is not decoration: it is the only thing that catches the skill being confidently wrong, because an agent working without legwork will sometimes reach a source or a capability legwork's instructions assert does not exist. [`evals/README.md`](evals/README.md) has the protocol and the scoring.

## Known limitations

- **Publish dates are often missing** from SERP results. Legwork reports an unknown date rather than assuming one, but the recency signal is weaker for those sources. Backfill from page meta tags where you have the page anyway.
- **Source kinds are inferred conservatively** when you do not pass `--kind`: an unrecognised URL is logged as `unknown` and scored below commentary, because a confident wrong guess silently moves a source between tiers.
- **The Reddit pipeline is slow** (10-60s typical, occasionally minutes) and billed per record. Prefer top-relevance threads.
- **Trustpilot cannot be scraped** - the Unlocker zone blocks it and there is no pipeline equivalent. Use SERP snippets and quote only what the snippet shows.

## Development

See [`docs/dev-setup.md`](docs/dev-setup.md). Design rationale is in [`docs/design-notes.md`](docs/design-notes.md).

## License

[MIT](LICENSE) © 2026 DBHQ Consulting Ltd
