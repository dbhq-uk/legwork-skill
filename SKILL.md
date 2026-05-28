---
name: deep-research
description: Use when the user needs multi-source research with citation tracking, evidence persistence, and structured report generation. Triggers on "deep research", "comprehensive analysis", "research report", "compare X vs Y", "analyze trends", or "state of the art". Not for simple lookups, debugging, or questions answerable with 1-2 searches.
---

# Deep Research

## Core Purpose

Deliver citation-tracked research reports through a structured pipeline with evidence persistence, source identity management, claim-level verification, and progressive context management.

**Autonomy Principle:** Operate independently once a mode is chosen. Infer assumptions from context. Only stop for critical errors or incomprehensible queries. Surface high-materiality assumptions explicitly in the Introduction and Methodology rather than silently defaulting. **Exception:** mode selection is confirmed up front (see below) so the user knows whether they're committing to 5 minutes or 45.

---

## Decision Tree

```
Request Analysis
+-- Simple lookup? --> STOP: Use WebSearch
+-- Debugging? --> STOP: Use standard tools
+-- Complex analysis needed? --> CONTINUE

Mode Selection
+-- User named a mode? --> use it, start immediately
+-- User did NOT name a mode? --> ASK using AskUserQuestion (see below)
```

**Mode menu (always present these four when asking):**

| Mode | Phases | Duration | When |
|------|--------|----------|------|
| quick | 3 | 2–5 min | Initial exploration, scoping |
| standard | 6 | 5–10 min | Balanced research [recommend by default] |
| deep | 8 | 10–20 min | Critical decisions, multi-angle |
| ultradeep | 8+ | 20–45 min | Comprehensive review, high stakes |

**Counts as "user named a mode":** the request contains the literal word `quick`, `standard`, `deep`, `ultradeep`, or an equivalent like "quick scan", "ultradeep mode", "do a deep dive". `"deep research"` on its own is the skill name and does NOT count as choosing deep mode — still ask.

**Ask via `AskUserQuestion`** (or your platform's equivalent) before doing anything else — no searches, no scope, no folder creation. Use one question with four options matching the table above. Pre-select `standard` as the recommended option but let the user pick freely. Then, once chosen, the Autonomy Principle takes over and the run proceeds without further confirmation.

**Default assumptions** (apply within the chosen mode): Technical query = technical audience. Comparison = balanced perspective. Trend = recent 1-2 years.

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
3. **HTML/PDF output:** Load [html-generation.md](./reference/html-generation.md)
4. **Quality checks:** Load [quality-gates.md](./reference/quality-gates.md)
5. **Long reports (>18K words):** Load [continuation.md](./reference/continuation.md)

**Templates:**
- Report structure: [report_template.md](./templates/report_template.md)
- HTML styling: [mckinsey_report_template.html](./templates/mckinsey_report_template.html)

**Scripts:**
- `python scripts/validate_report.py --report [path]`
- `python scripts/verify_citations.py --report [path]`
- `python scripts/md_to_html.py [markdown_path]`

---

## Output Contract

**Required sections:**
- Executive Summary (200-400 words)
- Introduction (scope, methodology, assumptions)
- Main Analysis (4-8 findings, 600-2,000 words each, cited)
- Synthesis & Insights (patterns, implications)
- Limitations & Caveats
- Recommendations
- Bibliography (COMPLETE - every citation, no placeholders)
- Methodology Appendix

**Output files (all to `<output-base>/[Topic]_Research_[YYYYMMDD]/`):**

Resolve `<output-base>` at the start of the run using:

```bash
OUTPUT_BASE="${DEEP_RESEARCH_OUTPUT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)/research}"
```

- `$DEEP_RESEARCH_OUTPUT` if set, else `<git-root>/research/`, else `$PWD/research/` when not in a git repo.
- Surface the resolved path in the Methodology Appendix so reruns are reproducible.

Contents of the dated folder:
- Markdown (primary source of truth)
- `sources.jsonl` — stable source registry with canonical IDs
- `evidence.jsonl` — append-only evidence store with quotes and locators
- `claims.jsonl` — atomic claim ledger with support status
- `run_manifest.json` — query, mode, assumptions, provider config
- HTML (McKinsey style, auto-opened)
- PDF (professional print, auto-opened)

**Quality standards:**
- 10+ sources, 3+ per major claim (cluster-independent, not just count)
- All factual claims cited immediately [N] with evidence backing in `evidence.jsonl`
- Claim-support verification mandatory: no unsupported factual claims pass delivery
- No placeholders, no fabricated citations
- Prose-first (>=80%), bullets sparingly

---

## When to Use / NOT Use

**Use:** Comprehensive analysis, technology comparisons, state-of-the-art reviews, multi-perspective investigation, market analysis.

**Do NOT use:** Simple lookups, debugging, 1-2 search answers, quick time-sensitive queries.
