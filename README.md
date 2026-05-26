# Deep Research (Bright Data)

A Claude Code skill that runs multi-source web research and produces a citation-backed report.

The search backend is retargeted from `search-cli` (Brave/Serper/Exa/Jina/Firecrawl) to **Bright Data SERP API + Web Unlocker**. The skill's downstream relevance/rerank machinery (`source_evaluator.py`, Triangulate, Critique) is unchanged — Bright Data returns Google's SERP order, and the skill re-ranks on credibility on top.

## Installation

From the repo root:

```bash
./install.sh deep-research
```

That symlinks this directory into `~/.claude/skills/deep-research`, provisions a Python venv, and installs `requests`.

## Credentials

1. Sign up at [brightdata.com](https://brightdata.com/) and create:
   - one **SERP API** zone
   - one **Web Unlocker** zone
2. Run `~/.claude/skills/deep-research/setup.sh` — it prompts for the three values, writes `~/.deep-research/config.env` at `chmod 600`, and validates them against the SERP API with a single test request.

Re-enter or update credentials any time with:

```bash
~/.claude/skills/deep-research/setup.sh --reset
```

The wrapper reads environment variables first, then falls back to `~/.deep-research/config.env`. If you'd rather skip the prompts and edit the file by hand, run `setup.sh --no-prompt` to scaffold an empty template.

**When credentials go bad at runtime** (token revoked, zone deleted, plan exhausted), the wrapper exits with code `2` and an error message pointing back at `setup.sh --reset`. Claude will surface the message instead of silently falling through to `WebSearch` forever.

## Usage

Tell Claude what you want:

```
deep research on the current state of quantum computing
deep research in ultradeep mode: compare PostgreSQL vs Supabase for our stack
```

The skill picks a mode (quick/standard/deep/ultradeep), runs the 8-phase pipeline, and saves output to `~/Documents/[Topic]_Research_[YYYYMMDD]/`.

## How the search backend works

The skill's `reference/methodology.md` instructs Claude to invoke `~/.claude/skills/deep-research/scripts/bd_search.py` via the Bash tool, with the same CLI surface as the original `search-cli`:

```
bd_search.py "<query|url>" [--json] [-c N] [-m MODE] [--country XX] [--max-chars N]
```

**Search modes** (Bright Data SERP API): `general, news, academic, scholar, patents, people, images`

**Content modes** (Bright Data Web Unlocker, positional arg must be a URL): `extract, scrape`

On any failure (missing creds, non-200, empty results) the wrapper emits a JSON error to stderr and exits non-zero, which triggers the skill's documented fallback to Claude's built-in `WebSearch`.

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

In `~/Documents/[Topic]_Research_[YYYYMMDD]/`:

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
- **SERP schema drift**: Bright Data's parsed JSON field names vary by vertical. `_normalize_serp()` in `bd_search.py` is defensive but unverified against every zone. If results come back empty, check field names against the live response.

## Files

```
deep-research/
├── SKILL.md                   # Skill entry point
├── README.md                  # (this file)
├── setup.sh                   # Creates .venv, installs deps, scaffolds creds template
├── requirements.txt           # requests (Bright Data wrapper)
├── reference/                 # Methodology, report assembly, quality gates, etc.
├── templates/                 # Markdown + HTML report templates
├── schemas/                   # JSON schemas for sources/evidence/claims/manifest
├── scripts/
│   ├── bd_search.py           # Bright Data SERP + Web Unlocker wrapper
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
