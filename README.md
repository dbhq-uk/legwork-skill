# Deep Research

A Claude Code skill for multi-source web research that produces citation-backed findings — tuned for **frequent, day-to-day research**, not occasional consulting deliverables.

See [docs/day-to-day-fix-list.md](docs/day-to-day-fix-list.md) for the design rationale behind the changes.

## What makes it different

**Free by default, paid only when needed.** Retrieval runs on the host's built-in `WebSearch`/`WebFetch`. The Bright Data CLI is a *fallback*, used only where the built-ins genuinely can't do the job. A run against unblocked sources makes **zero** paid calls.

**No prompt before it starts.** It picks a mode, announces it, and begins. Redirect it mid-run if it guessed wrong — that costs far less than a blocking question on every research request.

**Costs scale with mode.** A five-minute question does not get a full evidence ledger, a multi-minute network validation pass, or an 8-section report. A high-stakes one gets all three.

**Brief by default.** The deliverable for quick/standard is a findings memo (800–2,500 words), not a formal report. Brief drops scaffolding, never rigor: every claim still carries an inline `[N]`, and the bibliography is still complete.

## Installation

```bash
./install.sh deep-research     # from the repo root
```

That symlinks the skill into `~/.claude/skills/deep-research` and provisions a Python venv. The scripts are **stdlib-only** — no packages required.

Optional, for the fallback provider:

```bash
npm install -g @brightdata/cli   # or: curl -fsSL https://cli.brightdata.com/install.sh | sh
brightdata login                 # or: export BRIGHTDATA_API_KEY=...
```

Setup succeeds without it; you just lose fallback scraping.

## Usage

```
deep research the tradeoffs of pgvector vs a dedicated vector DB at our scale
research in deep mode: regulatory exposure of shipping this feature in the EU
quick: what changed in the EU AI Act in the last six months?
```

Add `brief` or `full report` to override the deliverable format.

### Modes

| Mode | Duration | Format | Artifacts | Gates |
|------|----------|--------|-----------|-------|
| quick | 2–5 min | brief | report only | validate + offline citations |
| standard **(default)** | 5–10 min | brief | + sources, evidence | validate + offline citations |
| deep | 10–20 min | report | + claims ledger | + network citations, claim-support |
| ultradeep | 20–45 min | report | + claims ledger | + network citations, claim-support |

Set a different default with `export DEEP_RESEARCH_DEFAULT_MODE=deep`.

### Tuning it to your research niche

The credibility scorer flattens unknown domains to 55/100. Register the domains you actually trust in `~/.deep-research/domains.json`:

```json
{
  "high": ["mytrustedjournal.org", "internal-wiki.company.com"],
  "moderate": ["someindustryblog.dev"],
  "low": ["contentfarm.example"]
}
```

These merge over the built-in tiers and apply to subdomains. User entries win outright — list a built-in "high" domain under `low` and it scores low. Point `$DEEP_RESEARCH_DOMAINS` elsewhere to override the path.

## Search backend

Retrieval is **built-in first**:

| Situation | Provider |
|-----------|----------|
| Normal search and page reads | `WebSearch` / `WebFetch` (free) |
| Page is bot-blocked, paywalled, or JS-heavy | Bright Data `-m scrape` |
| Reddit thread | Bright Data `-m reddit` (structured pipeline; billed per record) |
| Geo-specific or vertical SERP (`--country`, news, images) | Bright Data SERP |
| Coverage still thin after 2–3 query variants | Bright Data SERP |

Bright Data is invoked through `scripts/bd_search.py`:

```
bd_search.py "<query|url>" [--json] [-c N] [-m MODE] [--country XX] [--max-chars N]
```

Modes: `general, news, images` (SERP, native) · `academic, scholar, patents, people` (SERP, aliased to web) · `extract, scrape` (Web Unlocker; arg must be a URL) · `reddit` (dataset pipeline; arg must be a reddit.com URL).

On any failure the wrapper emits JSON to stderr and exits non-zero, and the skill falls back to the built-ins. Auth/quota failures map to exit code `2` so you get told to re-authenticate rather than silently degrading.

**Cost:** SERP and Web Unlocker bill per successful request; the Reddit pipeline bills per record. Nothing else in the skill costs money.

## Pipeline

`Scope → Plan → Retrieve (parallel) → Triangulate → Outline → Synthesize → Critique (loop-back) → Refine → Package`

Quick mode runs Scope → Retrieve → Package. See [reference/methodology.md](reference/methodology.md).

## Output

Written to `<output-base>/[Topic]_Research_[YYYYMMDD]/`, where `<output-base>` is `$DEEP_RESEARCH_OUTPUT`, else `<git-root>/docs/research/`, else `$PWD/docs/research/`.

| File | Modes |
|------|-------|
| Markdown deliverable (brief or report) | all |
| `run_manifest.json` | all |
| `sources.jsonl` — stable source registry (sha256 IDs) | standard+ |
| `evidence.jsonl` — append-only quotes + locators | standard+ |
| `claims.jsonl` — claim ledger with support status | deep/ultradeep |
| HTML / PDF | on explicit request only |

Source IDs are content-derived, so they survive renumbering, context compaction, and continuation agents. Display numbers `[N]` are assigned at render time and never stored.

## Scripts

All stdlib-only; Python 3.9+.

| Script | Purpose |
|--------|---------|
| `validate_report.py --report P --format brief\|report` | Structural gate (local) |
| `verify_citations.py --report P [--offline]` | Citation checks. `--offline` = zero network; the network pass is 8-way concurrent and cached |
| `citation_manager.py` | `init-run`, `register-source(s)`, `assign-display-numbers`, `export-bibliography` |
| `evidence_store.py` | `init`, `add`, `add-batch`, `list`, `export` |
| `source_evaluator.py score` | Credibility scoring / re-ranking; user-extensible domain tiers |
| `extract_claims.py` → `verify_claim_support.py` | Claim ledger + support verification (deep/ultradeep) |
| `bd_search.py` | Bright Data fallback wrapper |
| `md_to_html.py`, `verify_html.py` | HTML rendering (on request) |

**Use the batch forms** (`register-sources --jsonl-file`, `add-batch --jsonl-file`): they build the dedup index once, instead of one subprocess and one full file rescan per record.

## Tests

```bash
python3 -m pytest tests/ -v      # 105 tests, no network required
```

CI runs the suite across Python 3.9–3.13 plus an end-to-end smoke job (fixtures through the real gates, a full run lifecycle, and a setup run with no Bright Data CLI present).

## Known limitations

- **Publish dates are often missing** from SERP results, which flattens the recency signal to 50/100. Backfill from scraped page meta tags where you have the page anyway.
- **The Reddit pipeline is slow** (10–60s typical, occasionally minutes) and billed per record. Prefer top-relevance threads.
- **Trustpilot cannot be scraped** — the Unlocker zone blocks it and there is no pipeline equivalent. Use SERP snippets (`-m general "site:trustpilot.com ..."`) and quote only what the snippet shows.
- **Claude-only.** `reference/*.md` hardcodes `~/.claude/skills/...` paths and the skill isn't in `install-codex.sh`'s skill list.

## Files

```
deep-research/
├── SKILL.md                   # Skill entry point (mode/format/provider policy)
├── docs/day-to-day-fix-list.md  # Design doc for the day-to-day rework
├── setup.sh                   # venv; Bright Data CLI check is advisory
├── reference/                 # methodology, report-assembly, quality-gates, html, continuation
├── templates/                 # brief_template.md, report_template.md, mckinsey HTML
├── schemas/                   # source / evidence / claim / run_manifest
├── scripts/                   # see table above
└── tests/                     # 105 tests + fixtures
```

## License

MIT licensed.
