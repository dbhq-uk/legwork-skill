> **Superseded.** This records the design of Legwork *before* the July 2026
> redesign, when it was still shaped for academic research. The scripts it
> discusses (`validate_report.py`, `verify_citations.py`, `citation_manager.py`,
> `evidence_store.py`, `extract_claims.py`, `verify_claim_support.py`,
> `source_evaluator.py`) no longer exist. Kept for the reasoning, not as a
> description of the current tool. See [`../design-notes.md`](../design-notes.md).

# Deep Research: Day-to-Day Fix List (Design Document)

**Status:** ✅ Implemented · **Branch:** `deep-research-optimize` · **Date:** 2026-07-14

> All 11 fixes below are implemented. Test suite: 45 → 105 tests, all passing across
> Python 3.9–3.13 in CI. This document is retained as the rationale record — it explains
> *why* the skill is shaped the way it is, which the code alone can't say.
>
> **Implementation summary:**
>
> | Fix | What shipped |
> |-----|--------------|
> | F1 | Mode is picked and announced, never asked. `$DEEP_RESEARCH_DEFAULT_MODE` honoured |
> | F2 | `verify_citations.py --offline` (0.12s, zero network) for quick/standard; network pass is 8-way concurrent + per-run cached, `time.sleep` removed |
> | F3 | `setup.sh` succeeds without the Bright Data CLI (exit 0, venv provisioned) |
> | F4 | Claims pipeline wired into Phase 6 for deep/ultradeep; "mandatory" wording dropped for lighter modes |
> | F5 | `register-sources` / `add-batch` batch subcommands; artifact set scales with mode |
> | F6 | `source_evaluator.py score` CLI; `~/.deep-research/domains.json` user tiers; subdomain matching |
> | F7 | `research_engine.py` deleted (603 dead lines) |
> | F8 | `brief` format + `brief_template.md` + `validate_report.py --format` |
> | F9 | Claim schema accepts its scripts' own fields; manifest records websearch-primary/brightdata-fallback; template uses the real `support_status` enum |
> | F10 | Tests for every wired-in script; GitHub Actions CI (matrix + smoke job) |
> | F11 | `from __future__ import annotations` across all scripts and tests (Python 3.9 floor) |
>
> **Bug found while testing:** `validate_report.py` counted citation markers across the
> *whole* document, bibliography included — so a report with zero inline citations passed
> as long as it had a bibliography, and the "unused bibliography entries" warning could
> never fire. Both now cross-check against the body only.

## 1. Target usage profile

This skill began as a consulting-grade report factory. The actual usage profile it
needs to serve is **frequent, personal, internet research**:

- Several runs per day/week, mostly quick/standard depth; deep/ultradeep occasionally.
- Markdown findings are the deliverable. HTML/PDF is a rare special request.
- Zero recurring cost by default: built-in WebSearch/WebFetch first, Bright Data only
  when a page is blocked, the target is Reddit, or coverage is thin. *(Already done on
  this branch.)*
- Low ceremony: no interactive prompts, no multi-minute validation passes, no artifact
  bloat for a 5-minute question.
- The evidence/citation machinery is the skill's differentiator — keep it, but make its
  cost proportional to run depth.

**Design principle for every fix below: cost (tokens, time, prompts, network) must scale
with the chosen mode. Quick mode should feel like a fast answer with receipts; ultradeep
keeps the full rigor.**

## 2. What's already fixed on this branch

- Search inverted: WebSearch/WebFetch primary, `bd_search.py` fallback (blocked pages,
  Reddit pipeline, geo/vertical SERP, thin coverage).
- Token Efficiency Policy added to SKILL.md (snippets before scrapes, `--max-chars 8000`,
  structured-JSON-only subagents, word targets are ceilings).
- HTML/PDF made opt-in; markdown is the default deliverable; duplicate copy to
  `~/.claude/research_output/` removed.

## 3. What the second-pass audit found

A full script/schema/test audit (2026-07-14) confirmed:

- **All 45 unit tests pass** (Python 3.12, stdlib-only scripts). The persistence layer
  (`citation_manager.py`, `evidence_store.py`) matches its JSON schemas field-for-field.
- `verify_citations.py` is the only validator that touches the network — and it is
  mandated after **every** report.
- Two scripts with full test coverage (`extract_claims.py`, `verify_claim_support.py`)
  are never invoked by any documented workflow, while SKILL.md claims their function
  ("claim-support verification mandatory") is enforced.
- `research_engine.py` (603 lines) is dead code by its own docstring's admission.
- `source_evaluator.py` is named throughout the methodology but has no CLI — the
  documented "score each source" step has no runnable form.

## 4. Fix list

### P0 — friction that hits every run

**F1. Kill the mandatory mode prompt.**
`SKILL.md` currently requires an `AskUserQuestion` mode menu on every run where the user
didn't name a mode. For daily use this is the single most annoying step.
*Design:* default to **standard** silently; state the chosen mode in the first status
line ("Running standard mode — say 'deep' to escalate"). Ask only when the request is
genuinely ambiguous about stakes (e.g. contains "important decision", "thorough",
"comprehensive" but no mode word). Honour `DEEP_RESEARCH_DEFAULT_MODE` env var.
*Files:* `SKILL.md` (Decision Tree section).

**F2. Make citation verification cost scale with mode.**
`verify_citations.py` fires one DOI GET per DOI'd entry plus one HEAD per unverified
entry, serially, `time.sleep(0.5)` per entry, no cache, no concurrency
(`verify_citations.py:129,161,331`) — up to ~60 blocking calls on a deep report, and
`quality-gates.md:41-51` mandates it after every report with up to 3 retry cycles.
*Design:*
- quick/standard: run in `--offline` mode (new flag): format checks, citation↔bibliography
  cross-check, suspicious-pattern flags — zero network.
- deep/ultradeep: full network verification, but with a thread pool (8 workers), the
  sleep removed, and a per-run URL result cache so retry cycles don't re-fetch.
*Files:* `scripts/verify_citations.py`, `reference/quality-gates.md`.

**F3. `setup.sh --no-prompt` must succeed without the Bright Data CLI.**
`setup.sh:64-73` hard-exits if `brightdata`/`bdata` is missing — before the
`--no-prompt` branch is reached. Now that Bright Data is a fallback, the skill is fully
functional without it.
*Design:* demote the CLI check to a warning ("Bright Data CLI not found — fallback
scraping disabled; install with `npm i -g @brightdata/cli` when needed"); only `--reset`
requires it.
*Files:* `setup.sh`, README install section.

**F4. Resolve the claims-pipeline contradiction.**
SKILL.md promises "claim-support verification mandatory", but `extract_claims.py` and
`verify_claim_support.py` are orphans — no reference doc ever calls them; the documented
validation loop runs only `validate_report.py` + `verify_citations.py`.
*Design:* make the claims ledger a **deep/ultradeep-only** stage, and wire it in
explicitly: after synthesis run `extract_claims.py` → `verify_claim_support.py`, gate
delivery on no `unsupported` claims. For quick/standard, drop the "mandatory" wording
from SKILL.md and skip `claims.jsonl` entirely (evidence.jsonl + inline citations are
enough at that depth).
*Files:* `SKILL.md` (Output Contract, quality standards), `reference/methodology.md`
(Phase 6), `reference/quality-gates.md` (validation loop).

### P1 — cost and capability

**F5. Right-size artifact persistence per mode.**
`citation_manager.py register-source` and `evidence_store.py add` are one Python
subprocess per source/span with an O(n) rescan per call — dozens-to-hundreds of spawns
on a deep run, and heavy ceremony for a quick one.
*Design:*
- Add batch subcommands: `register-sources --jsonl-file` and `add-batch --jsonl-file`
  (read many records in one process; dedup index built once).
- Mode policy: quick = no jsonl ledger (report + inline citations only);
  standard = `sources.jsonl` + `evidence.jsonl`; deep/ultra = full set incl. claims.
*Files:* `scripts/citation_manager.py`, `scripts/evidence_store.py`,
`reference/methodology.md`, `reference/report-assembly.md`, tests.

**F6. Give `source_evaluator.py` a CLI and a user config.**
It has no argparse interface (`source_evaluator.py:264-292` runs hardcoded examples),
domain tiers are hardcoded set literals, unknown domains flatten to 55, and null dates
flatten recency to 50.
*Design:*
- `score --jsonl-file sources.jsonl` batch CLI emitting scored JSONL.
- Optional user tier overrides from `~/.deep-research/domains.json`
  (`{"high": [...], "moderate": [...], "low": [...]}`) merged over the built-ins — this
  is where recurring personal research topics get their trusted domains registered
  without editing source.
- Date backfill: when a page is scraped anyway, parse `article:published_time` /
  `<time datetime>` meta and pass it to the evaluator, un-flattening the recency signal.
*Files:* `scripts/source_evaluator.py`, `reference/methodology.md`, new test file.

**F7. Delete `research_engine.py`.**
603 lines, zero references, self-described as "not a runtime orchestrator". Dead weight
that misleads readers of the scripts directory.
*Files:* delete script; drop the README directory-listing line.

**F8. Add a `brief` output format (orthogonal to mode).**
Modes control research effort; nothing controls deliverable weight. Day-to-day, a
1–2k-word findings memo (question → 3-6 findings → so-what → sources) beats the 8-section
formal report.
*Design:* `format: brief | report`. Default **brief** for quick/standard, **report** for
deep/ultradeep; either can be requested explicitly ("brief" / "full report" in the
request). Brief still cites every claim and writes `sources.jsonl` (standard mode) —
it drops the Executive Summary/Intro/Methodology-appendix scaffolding, not the rigor.
*Files:* `SKILL.md`, `reference/report-assembly.md`, `templates/` (new
`brief_template.md`), `scripts/validate_report.py` (relax required-sections check for
brief format).

### P2 — consistency and hygiene

**F9. Schema drift fixes.**
- `claims.jsonl` rows violate their own schema: `claim.schema.json` sets
  `additionalProperties: false` but `extract_claims.py:207` writes `_citation_numbers`
  and `verify_claim_support.py:234-235` writes `_support_score`/`_support_notes`.
  Fix: add these as optional schema properties (they're useful) rather than stripping.
- `run_manifest.schema.json:65` default `"primary": "search-cli"` is stale →
  `"websearch"`; `citation_manager.py cmd_init_run` hardcodes `'brightdata'` → record
  `"websearch"` primary with `"brightdata"` fallback.
- `methodology.md`'s subagent evidence format (`claim/evidence_quote/source_url/...`)
  shares no field names with the `register-source`/`add` payloads it feeds. Document the
  mapping in one short table in methodology.md.
- `report_template.md`'s Claims-Evidence table uses a `Confidence: High/Medium/Low`
  column that matches nothing in the schema — replace with `support_status` enum values.

**F10. Test the wired-in scripts.**
Coverage is inverted: the orphan claim scripts have 22 tests; `validate_report.py`,
`verify_citations.py` (offline paths), `md_to_html.py`, `verify_html.py`,
`source_evaluator.py` have zero. Add offline unit tests for each (the existing
`tests/fixtures/valid_report.md`/`invalid_report.md` are ready-made inputs).

**F11. Portability.**
- Python ≥3.10 is silently required (`evidence_store.py:38` uses PEP 604 unions).
  Add `from __future__ import annotations` across scripts *or* a version check in
  `setup.sh` — the future-import is cheaper.
- `~/.claude/skills/deep-research/...` is hardcoded in `reference/methodology.md` and
  `reference/html-generation.md`; `install-codex.sh` only rewrites SKILL.md, and
  deep-research isn't in its `AVAILABLE_SKILLS` anyway. If Codex install is wanted,
  add the skill to `install-codex.sh` and extend path rewriting to `reference/*.md`;
  otherwise document Claude-only support in README.

## 5. Explicitly not changing

- The 8-phase pipeline, mode tiers, and evidence-first philosophy — they're the value.
- Stable source IDs / display-number derivation — survives compaction, keep as is.
- `bd_search.py` — recently reworked, fails clean, well-tested against the fallback
  contract. Only touch it if the CLI schema drifts.
- The McKinsey HTML/PDF path — already opt-in; not worth deleting while it costs nothing
  unless invoked.

## 6. Suggested implementation order

1. **F1 + F3 + F7** — pure friction removal, no design risk (~30 min).
2. **F2 + F4** — validation-loop redesign; do together since both edit quality-gates.md.
3. **F5 + F6** — persistence batching + evaluator CLI/config; the biggest code changes.
4. **F8** — brief format; do after F5 so the mode/artifact policy is settled.
5. **F9–F11** — hygiene sweep; safe to batch into one commit.

Each step: run `python3 -m pytest tests/` (all 45 must stay green, new tests added in
F5/F6/F10), then one live smoke run per changed mode (`quick` and `standard` at minimum)
checking: no mode prompt, no Bright Data call on an unblocked topic, artifact set matches
the mode policy, validation completes offline in quick/standard.
