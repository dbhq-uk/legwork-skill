# Scripted Gathering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace subagent retrieval with `gather.py`, which searches every
source, opens every result, reranks every passage per angle and hands Claude a
digest, so a standard run costs at most half today's Claude usage with at least
today's reach and confidence.

**Architecture:** Claude frames and judges; scripts gather. `gather.py` calls
the existing CLIs (`bd_search.py`, `platforms.py`, `fetch.py`) as subprocesses
through one patchable helper, logs through `sources.log_row`, and reranks with
a new `rerank.py`. Spec: `docs/superpowers/specs/2026-09-27-scripted-gathering-design.md`.

**Tech Stack:** Python 3.9+, standard library only; pytest, hermetic.

## Global Constraints

- Standard library only; CI rejects third-party imports in `scripts/` and `hooks/`.
- `from __future__ import annotations` in every script.
- Tests never touch the network; subprocess and urlopen are patched.
- House style: British English, plain hyphens, no em or en dashes.
- Every change to this repo goes by pull request; merge only after the eval
  meets the spec's goal.
- No spending cap on Bright Data (spec decision 1); a per-call time limit only.
- Claude's WebSearch is not used by the run (spec decision 6).

---

### Task 1: Reddit through `platforms.py`

**Files:** Modify `skills/legwork/scripts/platforms.py`; Test `skills/legwork/tests/test_platforms.py`

**Interfaces:** Produces `search_reddit(args) -> (endpoint, results)`, registered
as `SEARCHERS['reddit']` and `PLATFORMS['reddit']`. Results are `community`
rows. A 403 or 429 exits non-zero through `_fail`, which `gather.py` treats as
"use `bd_search.py -m reddit`".

- [ ] Test: a canned Atom `search.rss` body parses to rows with url, title,
  date, snippet and kind `community`; the endpoint is
  `https://www.reddit.com/search.rss?q=...&sort=relevance&t=year`.
- [ ] Test: an HTTP 403 from `_get` makes `cmd_search` exit non-zero.
- [ ] Implement `search_reddit` with `_get(..., accept='application/atom+xml')`
  and the existing `_parse_feed(body, args, kind='community')`.
- [ ] Run `pytest tests/test_platforms.py -q`; expect pass. Commit.

### Task 2: Passages that keep sentences and headings whole

**Files:** Modify `skills/legwork/scripts/fetch.py`; Test `skills/legwork/tests/test_fetch.py`

**Interfaces:** Produces `extract_headings(markup) -> list[tuple[int, str]]`
(level, text); the sidecar gains `headings`. Produces
`passages_with_trail(text, headings) -> list[dict]` with keys `text`, `trail`.
`split_passages(text)` keeps its signature and now splits long paragraphs at
sentence ends. `rank_passages` uses the new splitter.

- [ ] Test: a 3,000-character paragraph splits only at `. `, `? ` or `! `
  boundaries - no passage starts or ends mid-sentence.
- [ ] Test: a heading line is never the last line of a passage when text
  follows it.
- [ ] Test: with headings `[(1,'Pricing'),(2,'Team plan')]`, a passage under
  "Team plan" has trail `Pricing > Team plan`.
- [ ] Implement, keeping every existing `test_fetch.py` test green. Commit.

### Task 3: `sources.py quote`

**Files:** Modify `skills/legwork/scripts/sources.py`; Test `skills/legwork/tests/test_sources.py`

**Interfaces:** Produces `set_quote(tsv, url, quote, page_text) -> str`
('true' | 'false') and the verb `quote --tsv --url --quote [--text-file]`.
Updates the first `ok` row for the canonical URL in place; never appends.

- [ ] Test: quoting a logged row sets its quote and `verified=true` when the
  words are on the saved page, `false` when not, and the row count is unchanged.
- [ ] Test: quoting a URL with no `ok` row exits 2.
- [ ] Implement with `read_rows` and a rewrite of the TSV under its header. Commit.

### Task 4: `rerank.py`

**Files:** Create `skills/legwork/scripts/rerank.py`; Test `skills/legwork/tests/test_rerank.py`

**Interfaces:** Produces:
- `term_scores(passages: list[str], terms: list[str]) -> list[float]` - IDF-weighted
  term overlap over the pool, 0-1.
- `jev_scores(passages, question) -> list[float] | None` - via
  `fetch._jev_request` and `fetch.typesafe_key()`, batches of 30; None when no key
  or on any failure.
- `select_digest(items, subject_party, cap=3, top=40) -> (chosen, overflow)` where
  each item is a dict with `score`, `party`, `id`; `overflow` maps party to the
  ids left out.

- [ ] Test: term scores rank a passage containing the rare terms above one with
  only common words.
- [ ] Test: `select_digest` caps a party at 3, never caps `subject_party`, keeps
  one passage from every party with score > 0, and lists every left-out id in
  overflow.
- [ ] Test: `jev_scores` returns None without a key and on an exception.
- [ ] Implement. Commit.

### Task 5: Offline test of cross-source reranking

**Files:** Create `evals/runs/2026-09-27-rerank-offline.md`; script under
`/home/devops/legwork-evals/20260927/`.

- [ ] Pool every passage from pages opened per angle in the 24 Sep banks,
  postgres and accountancy runs; score with `term_scores` and with `jev_scores`.
- [ ] Measure how many quoted passages land in the top 20 and top 40, and set
  the digest size (`top`) from the result.
- [ ] Record the result. Commit.

### Task 6: `gather.py` - plan, search, open, log

**Files:** Create `skills/legwork/scripts/gather.py`; Test `skills/legwork/tests/test_gather.py`

**Interfaces:**
- `run_script(argv: list[str], timeout: int) -> (code, stdout, stderr)` - the one
  subprocess seam tests patch.
- `load_plan(path) -> dict`, raising `PlanError` for a round-2 angle with a
  `subject` and neither `from` nor `expected`.
- `search_angle(angle, plan) -> list[dict]` - Bright Data on `google` and `bing`
  for every phrasing and disconfirming phrasing, platforms for `people` angles
  (`hn`, `stackexchange`, `githubissues`, `reddit`), Reddit falling back to
  `bd_search.py -m reddit`. Raises `SearchAborted` when `bd_search.py` exits 2.
- `open_url(url) -> dict` - `fetch.py`, then `bd_search.py -m scrape`, then
  `-m render`; returns the sidecar dict with `text_file` and `verdict`.
- One log row per (angle, url): opened, blocked, or `serp`/`api` lead.

- [ ] Tests with `run_script` patched: plan provenance refusal; both engines
  queried for every phrasing; `people` adds the platforms; Reddit falls back on
  a non-zero exit; duplicate links opened once; the ladder climbs on exit 3 and
  logs `blocked`; exit 2 from Bright Data aborts with a message naming
  `brightdata login`; the time limit returns partial results and lists what
  was not reached.
- [ ] Implement with a `ThreadPoolExecutor` across angles and pages. Commit.

### Task 7: `gather.py` - passages, rerank, names, saturation, digest

**Files:** Modify `skills/legwork/scripts/gather.py`; Test `skills/legwork/tests/test_gather.py`

**Interfaces:** Produces the digest Markdown and `<tsv stem>.ids.json` mapping
digest ids to url and text file.

- [ ] Tests: passages from every opened page pooled per angle and reranked;
  the digest honours the cap and subject exemption and prints overflow lines;
  round 1 lists names with the count of independent parties naming each (names
  from one party only are dropped); saturation is `saturated` when the last
  three searches added no new party; the ids file resolves every digest id.
- [ ] Implement. Commit.

### Task 8: Support scan offline test

- [ ] On the 24 Sep reports, ask Jev whether each gathered passage supports,
  contradicts or is unrelated to each finding; check it finds the passages the
  findings cite. Record the result.
- [ ] Build `gather.py --scan` only if it does; otherwise record why not.

### Task 9: Documents

**Files:** `SKILL.md`, `reference/methodology.md`, both templates, `SECURITY.md`,
`README.md`, `AGENTS.md`.

- [ ] The run as the spec's six steps; framing that names nothing; memory as a
  check; the receipt line with parties, searches, saturation and Bright Data
  spend; WebSearch and subagents out of the run; what leaves the machine.
- [ ] Full suite green. Commit.

### Task 10: Eval and merge

- [ ] All six cases, `main` against the branch, Sonnet 5, a few arms at a time.
- [ ] Pass only if Claude cost is at most half, reach and confidence are at
  least today's, and no report names anything without a source.
- [ ] Record `evals/runs/2026-09-27-scripted-gathering.md`, open the PR, merge
  on green only if the eval passed.
