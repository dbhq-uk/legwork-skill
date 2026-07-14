---
name: deep-research
description: Use when the user needs multi-source research with citation tracking, evidence persistence, and structured report generation. Triggers on "deep research", "comprehensive analysis", "research report", "compare X vs Y", "analyze trends", or "state of the art". Not for simple lookups, debugging, or questions answerable with 1-2 searches.
---

# Deep Research

## Core Purpose

Deliver citation-tracked research reports through a structured pipeline with evidence persistence, source identity management, claim-level verification, and progressive context management.

**Autonomy Principle:** Operate independently. Infer assumptions from context, pick a mode, and start. Only stop for critical errors or incomprehensible queries. Surface high-materiality assumptions explicitly in the Introduction and Methodology rather than silently defaulting. **Do not ask the user to pick a mode** — announce the one you picked and let them redirect.

---

## Decision Tree

```
Request Analysis
+-- Simple lookup? --> STOP: Use WebSearch
+-- Debugging? --> STOP: Use standard tools
+-- Complex analysis needed? --> CONTINUE

Mode Selection (never blocks — pick and announce)
+-- User named a mode? ------------> use it
+-- $DEEP_RESEARCH_DEFAULT_MODE set? --> use it
+-- Otherwise -------------------------> standard
```

| Mode | Phases | Duration | Format | Artifacts | When |
|------|--------|----------|--------|-----------|------|
| quick | 3 | 2–5 min | brief | report only | Initial exploration, scoping |
| standard | 6 | 5–10 min | brief | + sources, evidence | Balanced research **[default]** |
| deep | 8 | 10–20 min | report | + claims ledger | Critical decisions, multi-angle |
| ultradeep | 8+ | 20–45 min | report | + claims ledger | Comprehensive review, high stakes |

**Counts as "user named a mode":** the request contains the literal word `quick`, `standard`, `deep`, `ultradeep`, or an equivalent like "quick scan", "ultradeep mode", "do a deep dive". `"deep research"` on its own is the skill name and does NOT count as choosing deep mode — fall through to the default.

**Announce, don't ask.** Open the run with a single line — `Running **standard** mode (~5-10 min, brief format). Say "deep" for a fuller report.` — then proceed straight into Phase 1 without waiting. The user can redirect mid-run; that costs far less than a blocking prompt on every research question.

**Escalate silently when warranted:** if Phase 1 scoping reveals the question is materially higher-stakes than the default implies (regulatory, safety, irreversible financial decision), step up one mode and say so in the same status line.

**Default assumptions** (apply within the chosen mode): Technical query = technical audience. Comparison = balanced perspective. Trend = recent 1-2 years.

---

## Search Provider Policy

**Primary: built-in `WebSearch` + `WebFetch`.** Free, zero setup, no per-request billing. Use them for all initial retrieval.

**Fallback: Bright Data (`bd_search.py`)** — reach for it only when the built-ins can't do the job:

- `WebFetch` fails on a page you genuinely need (bot-blocked, paywalled, JS-heavy) → `bd_search.py "<url>" -m scrape --json`
- Reddit threads (WebFetch is blocked; the Unlocker zone is too) → `bd_search.py "<reddit-url>" -m reddit --json` (billed per record — top threads only)
- Geo-specific or vertical SERP (news/images, `--country XX`) that WebSearch can't express
- WebSearch results are thin/repetitive after 2-3 query variants and you need raw Google SERP coverage

Wrapper path: `~/.claude/skills/deep-research/.venv/bin/python ~/.claude/skills/deep-research/scripts/bd_search.py`. On exit code 2 (auth/quota), tell the user to run `brightdata login` — don't retry. Every Bright Data call costs money; never use it where a built-in would have worked.

---

## Token Efficiency Policy

Deep research burns tokens in three places: scraped page content, subagent transcripts, and report prose. Control all three:

1. **Snippets before scraping.** SERP/WebSearch snippets are often enough to establish a claim + source. Only fetch full pages for the sources that will anchor major findings (roughly the top ⅓ of your source list).
2. **Cap scraped content.** Use `--max-chars 8000` on scrape calls unless you have a specific reason to need more (default is 20000).
3. **Subagents return evidence, not essays.** Retrieval subagents run on `haiku` and must return the structured JSON evidence format only — no narrative summaries. Never paste a subagent's full transcript into your synthesis.
4. **Persist, don't re-read.** Evidence goes to `evidence.jsonl` once; query it with the scripts (`evidence_store.py`, `citation_manager.py`) rather than re-reading whole `.jsonl` files into context.
5. **Right-size the report.** Word targets are ceilings, not quotas. A standard-mode run that answers the question in 3,000 words should stop at 3,000 words. Never pad findings to hit a length band.
6. **Markdown only by default.** HTML and PDF generation (plus their reference docs, templates, and verification loops) run only when the user asks for them.

---

## Workflow Overview

| Phase | Name | Quick | Std | Deep | Ultra |
|-------|------|-------|-----|------|-------|
| 1 | SCOPE | Y | Y | Y | Y |
| 2 | PLAN | - | Y | Y | Y |
| 3 | RETRIEVE | Y | Y | Y | Y |
| 4 | TRIANGULATE | - | Y | Y | Y |
| 4.5 | OUTLINE REFINEMENT | - | Y | Y | Y |
| 5 | SYNTHESIZE | - | Y | Y | Y |
| 6 | CRITIQUE | - | - | Y | Y |
| 7 | REFINE | - | - | Y | Y |
| 8 | PACKAGE | Y | Y | Y | Y |

**Note:** Phases 3-5 operate as an evidence loop per section (retrieve → evidence store → refine outline → draft → verify claims → delta-retrieve if needed), not as strict sequential gates.

---

## Execution

**On invocation, load relevant reference files:**

1. **Phase 1-7:** Load [methodology.md](./reference/methodology.md) for detailed phase instructions
2. **Phase 8 (Report):** Load [report-assembly.md](./reference/report-assembly.md) for progressive generation
3. **HTML/PDF output (only if the user requested it):** Load [html-generation.md](./reference/html-generation.md)
4. **Quality checks:** Load [quality-gates.md](./reference/quality-gates.md)
5. **Long reports (>18K words):** Load [continuation.md](./reference/continuation.md)

**Templates:**
- Report structure: [report_template.md](./templates/report_template.md)
- HTML styling: [mckinsey_report_template.html](./templates/mckinsey_report_template.html)

**Scripts** (all stdlib-only; run with the skill's `.venv/bin/python` or any `python3` >= 3.9):

| Script | Purpose |
|--------|---------|
| `validate_report.py --report [path] --format brief\|report` | Structure/quality gate (local, no network) |
| `verify_citations.py --report [path] [--offline]` | Citation checks; `--offline` skips all network (use for quick/standard) |
| `citation_manager.py init-run \| register-source \| register-sources \| assign-display-numbers \| export-bibliography` | Source identity + run manifest |
| `evidence_store.py init \| add \| add-batch \| list \| export` | Evidence persistence |
| `source_evaluator.py score --jsonl-file [path]` | Credibility scoring (batch); user tiers from `~/.deep-research/domains.json` |
| `extract_claims.py` → `verify_claim_support.py` | Claim ledger + support verification (**deep/ultradeep only**) |
| `md_to_html.py [markdown_path]` | HTML rendering (only on explicit request) |

**Use the batch forms.** `register-sources --jsonl-file` and `add-batch --jsonl-file` take many records in one process — never loop a subprocess per source.

---

## Subagent Model Policy

Subagents must run on **cheaper models than the orchestrator** — never let them inherit the premium main-session model. Pass an explicit model override every time you spawn one:

| Subagent role | Phase | Model | Why |
|---------------|-------|-------|-----|
| Retrieval / deep-dive agents | 3 (RETRIEVE) | `haiku` | Fetch pages + extract structured evidence — mechanical, high-volume |
| PDF generation agent | 8 (PACKAGE) | `haiku` | Mechanical HTML→PDF conversion |
| Continuation agents | Long reports (>18K words) | `sonnet` | Writes report prose — quality-sensitive |

Spawn with the model override, e.g. `Task(subagent_type="general-purpose", model="haiku", ...)`. If your platform's subagent tool names the parameter differently, use that name — the requirement is that these subagents never run on the orchestrator's premium model. Only the orchestrator (scoping, synthesis, critique) stays on the main model.

---

## Output Contract

### Format: brief vs report

Format is **orthogonal to mode**. Mode controls research effort; format controls deliverable weight.

- **brief** (default for quick/standard) — a findings memo, 800–2,500 words:
  Question & Scope → Findings (3–6, each 150–400 words, every claim cited) → So What (implications, recommendations) → Limitations (2-4 sentences) → Bibliography (complete).
  Template: [brief_template.md](./templates/brief_template.md)
- **report** (default for deep/ultradeep) — the full structure:
  Executive Summary (200-400 words) → Introduction (scope, methodology, assumptions) → Main Analysis (4-8 findings, 600–2,000 words each) → Synthesis & Insights → Limitations & Caveats → Recommendations → Bibliography → Methodology Appendix.
  Template: [report_template.md](./templates/report_template.md)

The user can override either way ("brief", "just a summary" → brief; "full report", "write it up properly" → report). **Brief drops scaffolding, never rigor** — every factual claim is still cited [N] and the bibliography is still complete.

Validate with the matching format: `python scripts/validate_report.py --report [path] --format brief|report`.

**Output files (all to `<output-base>/[Topic]_Research_[YYYYMMDD]/`):**

Resolve `<output-base>` at the start of the run using:

```bash
OUTPUT_BASE="${DEEP_RESEARCH_OUTPUT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)/docs/research}"
```

- `$DEEP_RESEARCH_OUTPUT` if set, else `<git-root>/docs/research/`, else `$PWD/docs/research/` when not in a git repo.
- Surface the resolved path in the Methodology Appendix so reruns are reproducible.

**Artifacts scale with mode** — a 5-minute question does not earn a full evidence ledger:

| Artifact | quick | standard | deep | ultradeep |
|----------|-------|----------|------|-----------|
| Markdown deliverable (primary) | Y | Y | Y | Y |
| `run_manifest.json` | Y | Y | Y | Y |
| `sources.jsonl` (stable source registry) | - | Y | Y | Y |
| `evidence.jsonl` (quotes + locators) | - | Y | Y | Y |
| `claims.jsonl` (claim ledger + support status) | - | - | Y | Y |
| HTML / PDF | only on explicit request | | | |

In quick mode, inline citations `[N]` plus a complete bibliography *are* the evidence trail — skip `init-run`'s JSONL files entirely and just write the markdown.

**Quality standards:**
- 10+ sources, 3+ per major claim (cluster-independent, not just count)
- All factual claims cited immediately [N]; in standard+ every one has a backing row in `evidence.jsonl`
- **Claim-support verification (deep/ultradeep only):** run `extract_claims.py` → `verify_claim_support.py` after synthesis; no `unsupported` claim ships (see quality-gates.md)
- No placeholders, no fabricated citations
- Prose-first (>=80%), bullets sparingly

---

## When to Use / NOT Use

**Use:** Comprehensive analysis, technology comparisons, state-of-the-art reviews, multi-perspective investigation, market analysis.

**Do NOT use:** Simple lookups, debugging, 1-2 search answers, quick time-sensitive queries.
