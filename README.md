# Deep Research (Bright Data)

A Claude Code skill that runs multi-source web research and produces a citation-backed report.

The search backend is retargeted from `search-cli` (Brave/Serper/Exa/Jina/Firecrawl) to the **Bright Data CLI** (`@brightdata/cli`), which fronts Bright Data's SERP API + Web Unlocker. The skill's downstream relevance/rerank machinery (`source_evaluator.py`, Triangulate, Critique) is unchanged — Bright Data returns Google's SERP order, and the skill re-ranks on credibility on top.

## Installation

You need the Bright Data CLI on PATH. Install it once:

```bash
npm install -g @brightdata/cli
# or:  curl -fsSL https://cli.brightdata.com/install.sh | sh
```

That gives you `brightdata` (and an alias `bdata`).

Then, from the repo root:

```bash
./install.sh deep-research
```

That symlinks this directory into `~/.claude/skills/deep-research` and provisions a Python venv (used by the rest of the skill's scripts — no Python packages are required by the search wrapper itself).

## Credentials

The Bright Data CLI manages its own credentials. Sign up at [brightdata.com](https://brightdata.com/), then:

```bash
brightdata login        # interactive (opens a browser)
# or non-interactive:
export BRIGHTDATA_API_KEY=...
```

On first login the CLI auto-provisions the zones it needs (`cli_unlocker`, etc.), so you don't need to create any zones in the dashboard. `~/.claude/skills/deep-research/setup.sh` runs a live test against the CLI and offers to call `brightdata login` for you if you're not authenticated. To re-authenticate later:

```bash
~/.claude/skills/deep-research/setup.sh --reset
```

**When credentials go bad at runtime** (key revoked, plan exhausted, etc.), the wrapper exits with code `2` and an error message pointing back at `brightdata login`. Claude will surface the message instead of silently falling through to `WebSearch` forever.

## Usage

Tell Claude what you want:

```
deep research on the current state of quantum computing
deep research in ultradeep mode: compare PostgreSQL vs Supabase for our stack
```

The skill picks a mode (quick/standard/deep/ultradeep), runs the 8-phase pipeline, and saves output to `<git-root>/research/[Topic]_Research_[YYYYMMDD]/` — where `<git-root>` is the git root of the directory you invoke from (falling back to the cwd itself if it isn't a git repo). Set `$DEEP_RESEARCH_OUTPUT` to override the base path.

## How the search backend works

The skill's `reference/methodology.md` instructs Claude to invoke `~/.claude/skills/deep-research/scripts/bd_search.py` via the Bash tool, with the same CLI surface as the original `search-cli`:

```
bd_search.py "<query|url>" [--json] [-c N] [-m MODE] [--country XX] [--max-chars N]
```

**Search modes** (Bright Data SERP API, via `brightdata search`): `general, news, images` are mapped to the CLI's `--type` natively. Aliases `academic, scholar, patents, people` fall through to web search; the skill's downstream credibility re-ranker handles ordering.

**Content modes** (Bright Data Web Unlocker, via `brightdata scrape -f markdown`, positional arg must be a URL): `extract, scrape`

**Pipeline mode** (Bright Data structured datasets, via `brightdata pipelines reddit_posts`, positional arg must be a reddit.com URL): `reddit`. Required because the default Unlocker zone blocks reddit.com under robots.txt. Returns the dataset JSON as the `content` field for the skill to quote from. Billed per record (separate from Unlocker), slower (10-60s typical, up to 10 minutes for big threads). For Trustpilot there is no equivalent pipeline — rely on SERP snippets.

On any failure (CLI not installed, auth/quota error, empty results, zone-blocked URL) the wrapper emits a JSON error to stderr and exits non-zero, which triggers the skill's documented fallback to Claude's built-in `WebSearch`. Known auth/quota messages from the CLI are mapped to exit code `2` so the skill can prompt the user to re-authenticate instead of looping.

## Pipeline

`Scope → Plan → Retrieve (parallel) → Triangulate → Outline → Synthesize → Critique (loop-back) → Refine → Package`

Mode caps:

| Mode | Phases | Duration |
|------|--------|----------|
| Quick | 3 | 2–5 min |
| Standard | 6 | 5–10 min |
| Deep | 8 | 10–20 min |
| UltraDeep | 8+ | 20–45 min |

## Output

In `<output-base>/[Topic]_Research_[YYYYMMDD]/` (resolved as above):

- Markdown report (primary source of truth)
- `sources.jsonl`, `evidence.jsonl`, `claims.jsonl` (persisted evidence trail)
- `run_manifest.json` (records `provider_config.primary: "brightdata"`)
- HTML (McKinsey style, auto-opened)
- PDF (optional, requires `pip install weasyprint` in the skill's venv)

## Cost notes

Bright Data SERP and Web Unlocker bill per successful request. The retrieve phase fires 5–10 concurrent searches per batch; budget accordingly. Hard failures fall back to `WebSearch` (free) but cost is otherwise not capped by the skill.

## Known limitations

- **Publish dates often missing** from Google organic results, which flattens the recency signal in `source_evaluator.py` (defaults to 50/100). Optional enhancement: parse meta tags from scraped pages and backfill the date before calling `evaluate_source`.
- **Unknown-domain flattening**: open-web SERP surfaces many domains not in `source_evaluator.py`'s hardcoded tiers; they all score 55. For niche research areas, extend `HIGH_AUTHORITY_DOMAINS`/`MODERATE_AUTHORITY_DOMAINS`.
- **SERP schema drift**: Bright Data's parsed JSON field names vary by vertical (organic vs news). `_normalize_serp()` in `bd_search.py` is defensive but unverified against every CLI release. If results come back empty, run `brightdata search "<query>" --type news --json` by hand and check the field names against the live response.

## Files

```
deep-research/
├── SKILL.md                   # Skill entry point
├── README.md                  # (this file)
├── setup.sh                   # Creates .venv, verifies the Bright Data CLI is installed + authed
├── requirements.txt           # (empty — wrapper now shells out to the Bright Data CLI)
├── reference/                 # Methodology, report assembly, quality gates, etc.
├── templates/                 # Markdown + HTML report templates
├── schemas/                   # JSON schemas for sources/evidence/claims/manifest
├── scripts/
│   ├── bd_search.py           # Bright Data CLI wrapper (search + scrape)
│   ├── citation_manager.py    # Source registry, run manifest
│   ├── evidence_store.py      # Evidence persistence (JSONL)
│   ├── source_evaluator.py    # Deterministic credibility scorer (THE re-ranker)
│   ├── research_engine.py     # Phase orchestration prompts
│   ├── validate_report.py     # 9-check structural validator
│   ├── verify_citations.py    # DOI/URL/hallucination checker
│   └── ...
└── tests/                         # Tests (citation manager, evidence store, etc.)
```

## License

MIT licensed.
