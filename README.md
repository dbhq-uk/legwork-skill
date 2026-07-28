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

Ask a real question, get a findings memo where every factual claim carries an inline `[N]` and the bibliography is complete. Legwork picks a research depth, announces it, and starts - no questionnaire before it will do anything.

## What makes it different

**Free by default, paid only when needed.** Retrieval runs on the host's built-in `WebSearch` and `WebFetch`. The Bright Data CLI is a *fallback*, used only where the built-ins genuinely cannot do the job - bot-blocked or paywalled pages, Reddit threads, geo-specific SERP. A run against ordinary sources makes **zero** paid calls.

**It does not ask permission to begin.** It infers a mode, says which one it picked, and goes. Redirect it mid-run if it guessed wrong; that costs far less than a blocking question on every research request.

**Cost scales with the question.** A five-minute lookup does not earn a full evidence ledger, a network validation pass, or an eight-section report. A high-stakes one gets all three.

**Brief by default.** The deliverable for quick and standard modes is a findings memo of 800-2,500 words, not a formal report. Brief drops scaffolding, never rigour - every claim still carries its `[N]`.

**The gates are real.** `validate_report.py` will fail a report that does not meet its structural contract, and `verify_claim_support.py` will not let an `unsupported` claim ship in deep mode. The test suite includes a fixture that is *supposed* to fail validation, so the gate is proved to bite rather than assumed to.

## Install

### As a Claude Code plugin (recommended)

```
/plugin marketplace add dbhq-uk/marketplace
/plugin install legwork@dbhq
```

### Local install (Claude Code or Codex)

```bash
git clone https://github.com/dbhq-uk/legwork-skill.git
cd legwork-skill
./install.sh          # Claude Code: symlinks into ~/.claude/skills (edits are live)
./install-codex.sh    # Codex: installs into ~/.codex/skills
```

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

### Modes

| Mode | Duration | Format | Artifacts | Gates |
|------|----------|--------|-----------|-------|
| quick | 2-5 min | brief | report only | validate + offline citations |
| standard **(default)** | 5-10 min | brief | + sources, evidence | validate + offline citations |
| deep | 10-20 min | report | + claims ledger | + network citations, claim-support |
| ultradeep | 20-45 min | report | + claims ledger | + network citations, claim-support |

Set a different default with `export LEGWORK_DEFAULT_MODE=deep`.

### Tuning it to your field

The credibility scorer flattens unknown domains to 55/100. Register the ones you actually trust in `~/.legwork/domains.json`:

```json
{
  "high": ["mytrustedjournal.org", "internal-wiki.company.com"],
  "moderate": ["someindustryblog.dev"],
  "low": ["contentfarm.example"]
}
```

These merge over the built-in tiers and apply to subdomains. Your entries win outright - list a built-in "high" domain under `low` and it scores low. Point `$LEGWORK_DOMAINS` elsewhere to override the path.

## Search backend

| Situation | Provider |
|-----------|----------|
| Normal search and page reads | `WebSearch` / `WebFetch` (free) |
| Page is bot-blocked, paywalled, or JS-heavy | Bright Data `-m scrape` |
| Reddit thread | Bright Data `-m reddit` (billed per record) |
| Geo-specific or vertical SERP (`--country`, news, images) | Bright Data SERP |
| Coverage still thin after 2-3 query variants | Bright Data SERP |

On any failure the wrapper emits JSON to stderr and exits non-zero, and the skill falls back to the built-ins. Auth and quota failures map to exit code `2`, so you are told to re-authenticate rather than left silently degraded.

## Output

Written to `<output-base>/[Topic]_Research_[YYYYMMDD]/`, where `<output-base>` is `$LEGWORK_OUTPUT`, else `<git-root>/docs/research/`, else `$PWD/docs/research/`.

| File | Modes |
|------|-------|
| Markdown deliverable (brief or report) | all |
| `run_manifest.json` | all |
| `sources.jsonl` - stable source registry (sha256 IDs) | standard+ |
| `evidence.jsonl` - append-only quotes + locators | standard+ |
| `claims.jsonl` - claim ledger with support status | deep/ultradeep |
| HTML / PDF | on explicit request only |

Source IDs are content-derived, so they survive renumbering, context compaction and continuation agents. Display numbers `[N]` are assigned at render time and never stored.

## Scripts

All standard library only, Python 3.9+.

| Script | Purpose |
|--------|---------|
| `validate_report.py --report P --format brief\|report` | Structural gate (local, no network) |
| `verify_citations.py --report P [--offline]` | Citation checks. `--offline` is zero-network; the network pass is 8-way concurrent and cached |
| `citation_manager.py` | `init-run`, `register-source(s)`, `assign-display-numbers`, `export-bibliography` |
| `evidence_store.py` | `init`, `add`, `add-batch`, `list`, `export` |
| `source_evaluator.py score` | Credibility scoring and re-ranking; user-extensible domain tiers |
| `extract_claims.py` → `verify_claim_support.py` | Claim ledger + support verification (deep/ultradeep) |
| `bd_search.py` | Bright Data fallback wrapper |
| `md_to_html.py`, `verify_html.py` | HTML rendering (on request) |

**Use the batch forms** (`register-sources --jsonl-file`, `add-batch --jsonl-file`): they build the dedup index once instead of spawning a subprocess and rescanning the file per record.

## Tests

```bash
python3 -m pytest skills/legwork/tests/ -v      # 105 tests, no network required
```

CI runs the suite across Python 3.9-3.13, plus an end-to-end smoke job that pushes the shipped fixtures through the real gates, runs a full research lifecycle, and asserts setup succeeds with no Bright Data CLI present.

## Known limitations

- **Publish dates are often missing** from SERP results, which flattens the recency signal to 50/100. Backfill from page meta tags where you have the page anyway.
- **The Reddit pipeline is slow** (10-60s typical, occasionally minutes) and billed per record. Prefer top-relevance threads.
- **Trustpilot cannot be scraped** - the Unlocker zone blocks it and there is no pipeline equivalent. Use SERP snippets and quote only what the snippet shows.

## Development

See [`docs/dev-setup.md`](docs/dev-setup.md). Design rationale is in [`docs/design-notes.md`](docs/design-notes.md).

## License

[MIT](LICENSE) © 2026 DBHQ Consulting Ltd
