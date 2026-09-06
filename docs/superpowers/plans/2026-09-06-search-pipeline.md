# Search pipeline implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a legwork run reach further (a search ladder and a page ladder, free rungs first) and record what it reached (opened versus seen, the query, the failures), with the gate enforcing the difference.

**Architecture:** Five layers, each a separate task with its own tests. The fetch log grows two fields and learns to verify itself; the gate learns that a search snippet is not an opened page; a new stdlib `fetch.py` opens pages for free and yields real page text; `bd_search.py` grows the rungs the Bright Data CLI already offers; the docs and evals catch up.

**Tech Stack:** Python 3.9+, standard library only. pytest for tests, hermetic (no network). Bright Data CLI 0.2.0 is an optional external binary, shelled out to and always mocked in tests.

**Spec:** `docs/superpowers/specs/2026-09-06-search-pipeline-design.md`

## Global Constraints

- **Standard library only.** No `requirements.txt`, no virtualenv. CI asserts it.
- **Python floor 3.9.** Every script carries `from __future__ import annotations`.
- **Tests are hermetic.** No socket is opened in any test. `urllib.request.urlopen` and `subprocess.run` are mocked.
- **House style:** British English, plain hyphens, no em or en dashes.
- **Scripts are referenced from SKILL.md via `${CLAUDE_SKILL_DIR}`.**
- **A change that makes any MUST-fail fixture pass has broken the gate.**
- Run from `skills/legwork/`: `python3 -m pytest tests/ -q`. Baseline is 225 passing.

---

### Task 1: The fetch log records more, and checks itself

**Files:**
- Modify: `skills/legwork/scripts/sources.py`
- Test: `skills/legwork/tests/test_sources.py`

**Interfaces:**
- Produces: `TSV_COLUMNS` gains `'query'` last. `VIA_VALUES` gains `'direct'`. `normalise_for_match(text) -> str`. `quote_appears_in(quote, text) -> bool`. `cmd_log` prints `numbers_from` (`'text'|'quote'|'flag'|'none'`) and `quote_verified` (`True|False|None`). `log` gains `--query`. New subcommand `receipt --tsv PATH [--format json]` printing `retrieval_receipt(rows) -> dict` with keys `sources, opened, snippet_only, brightdata, blocked, queries`.

- [ ] **Step 1: Write the failing tests** in `tests/test_sources.py`:
  - `test_query_column_round_trips`
  - `test_a_ten_column_log_still_reads` (no `query` header, fields fill empty)
  - `test_direct_is_a_valid_transport`
  - `test_numbers_come_from_the_quote_when_no_page_text`
  - `test_numbers_from_a_text_file_win_over_the_quote`
  - `test_a_quote_present_in_the_page_text_verifies`
  - `test_verification_survives_whitespace_and_curly_quotes`
  - `test_a_quote_absent_from_the_page_text_fails_verification`
  - `test_receipt_counts_opened_snippet_only_blocked_and_queries`
- [ ] **Step 2: Run them and watch them fail.** `python3 -m pytest tests/test_sources.py -q`
- [ ] **Step 3: Implement.** Append `'query'` to `TSV_COLUMNS` (last, so a ten-column log still parses positionally). Add `'direct'` to `VIA_VALUES`. Add:

```python
_MATCH_PUNCT = {0x2018: "'", 0x2019: "'", 0x201c: '"', 0x201d: '"',
                0x2013: '-', 0x2014: '-', 0x00a0: ' '}


def normalise_for_match(text):
    """Fold the differences that stop a true quote matching its page."""
    return re.sub(r'\s+', ' ', (text or '').translate(_MATCH_PUNCT)).strip().lower()


def quote_appears_in(quote, text):
    quote = normalise_for_match(quote)
    return bool(quote) and quote in normalise_for_match(text)
```

  In `cmd_log`: read the text file once into `page_text`; numbers from `--numbers`, else the text file, else `extract_numbers(quote)`; verify the quote against `page_text` when both exist. Add `retrieval_receipt(rows)` and `cmd_receipt`.
- [ ] **Step 4: Run the suite.** `python3 -m pytest tests/ -q` - all green.
- [ ] **Step 5: Commit.** `feat(sources): record the query, verify the quote, count what was opened`

---

### Task 2: The gate sees opened versus seen

**Files:**
- Modify: `skills/legwork/scripts/check.py`
- Create: `skills/legwork/tests/fixtures/snippet_only.md`, `skills/legwork/tests/fixtures/snippet_only.tsv`
- Modify: `skills/legwork/tests/fixtures/valid_brief.tsv`, `valid_report.tsv` (add a `query` column)
- Modify: `skills/legwork/templates/brief_template.md`, `report_template.md`, `AGENTS.md`, `.github/workflows/validate.yml`
- Test: `skills/legwork/tests/test_check.py`

**Interfaces:**
- Consumes: `sources.read_rows` rows carrying `via` and `query`.
- Produces: in `check_evidence`, `opened` excludes `via == 'websearch'`; graded problem text begins `cited from a search snippet, page never opened:`. New `check_receipt(content, rows, problems)` warning `receipt says N opened, the log has M`.

- [ ] **Step 1: Write the failing tests.** `test_a_citation_resting_only_on_a_snippet_fails_at_deep`, `..._warns_at_standard`, `..._is_ignored_at_quick`, `test_one_opened_row_clears_the_snippet_rule`, `test_a_receipt_opened_count_that_disagrees_with_the_log_warns`, `test_a_matching_receipt_count_is_silent`.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Build the fixture.** `snippet_only.md` is a valid brief - findings, confidence lines, limitations, bibliography, receipt - whose every cited row in `snippet_only.tsv` is `via=websearch` with a quote and a date, so the snippet rule is the only check that can fire.
- [ ] **Step 4: Implement** the two checks in `check.py`.
- [ ] **Step 5: Prove the fixture fails for that reason only.** `python3 scripts/check.py --report tests/fixtures/snippet_only.md --level deep --json` shows exactly one error, and `--level quick` passes.
- [ ] **Step 6: Update** both templates' receipt line to `([N] opened, [N] via Bright Data)`, the `AGENTS.md` MUST-fail table and conventions, and the CI MUST-fail list.
- [ ] **Step 7: Run the suite and every MUST-fail fixture.**
- [ ] **Step 8: Commit.** `feat(check): a search snippet is not an opened page`

---

### Task 3: `fetch.py`, a free direct fetch that yields page text

**Files:**
- Create: `skills/legwork/scripts/fetch.py`
- Create: `skills/legwork/tests/test_fetch.py`
- Modify: `skills/legwork/scripts/sources.py` (`log --from-fetch`)
- Test: `skills/legwork/tests/test_sources.py`

**Interfaces:**
- Produces: `html_to_text(html) -> str`; `extract_meta(html, headers=None) -> {'title', 'date', 'canonical'}`; `find_windows(text, terms, window=300, max_hits=5) -> [str]`; `classify(text, status, headers) -> ('ok'|'blocked'|'shell', reason)`; `link_density(html) -> float`; `fetch(url, timeout=30) -> (status, headers, body_bytes)`; `main()` exit codes 0 ok, 1 error, 3 blocked or shell, 4 unsupported type. Sidecar JSON keys: `url, final_url, http_status, content_type, title, date, chars, text_file, numbers, verdict, reason, find`.
- Consumes (Task 1): `sources.extract_numbers`.

- [ ] **Step 1: Write the failing tests**, all pure or mocked: `test_script_style_and_nav_are_dropped`, `test_block_elements_become_line_breaks`, `test_entities_decode`, `test_each_date_form_is_found_and_normalised` (meta `article:published_time`, JSON-LD `datePublished`, `<time datetime>`, `last-modified` header), `test_a_page_with_no_date_yields_empty`, `test_a_short_page_is_a_shell`, `test_high_link_density_is_a_shell`, `test_a_challenge_marker_is_blocked`, `test_403_exits_3_with_reason_blocked` (mock `urlopen`), `test_find_windows_marks_the_match_and_caps_hits`, `test_pdf_without_pdftotext_exits_4`.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement `fetch.py`** per the spec: browser-like headers, gzip, redirects, no cookies, no JavaScript, no `robots.txt` consultation (stated in SECURITY.md), `HTMLParser` subclass dropping `script style noscript svg nav header footer aside form template`, metadata extraction, shell and block classification, `--find` windows, text to `--out` (default `${TMPDIR:-/tmp}/legwork/<sha1[:12]>.txt`) plus the sidecar JSON, JSON to stdout.
- [ ] **Step 4: Run the tests.**
- [ ] **Step 5: Add `log --from-fetch PATH.json`** to `sources.py`, filling `--url`, `--title`, `--date`, `--text-file`, `--via direct`, with explicit flags winning. Tests: `test_from_fetch_fills_the_row`, `test_explicit_flags_beat_the_sidecar`.
- [ ] **Step 6: Run the suite.**
- [ ] **Step 7: Commit.** `feat(fetch): open a page for free and keep its text`

---

### Task 4: `bd_search.py` catches up with the CLI

**Files:**
- Modify: `skills/legwork/scripts/bd_search.py`
- Create: `skills/legwork/tests/test_bd_search.py`

**Interfaces:**
- Consumes: `fetch.html_to_text`, `fetch.find_windows`, `fetch.write_outputs`.
- Produces: modes `general news images shopping discover scrape render pipeline reddit`; flags `--engine --language --page --device --intent --since --until --must-contain --with-content --pipeline --find --window --out --max-chars --country --zone -c`. Exit 2 unchanged for auth and quota.

- [ ] **Step 1: Write the failing tests** with `subprocess.run` mocked: argument mapping per mode, `shopping` normalisation, `discover` flag mapping and per-result `content`, `render` command sequence (`browser open`, `browser get`, `browser close`), `pipeline` pass-through, `-m reddit` still maps to `reddit_posts`, dropped aliases (`scholar academic patents people`) fail naming the real modes, scrape output cleaned and windowed and written with a sidecar, auth message still exits 2.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the suite.**
- [ ] **Step 5: Commit.** `feat(bd): a second engine, intent search, a browser rung and every pipeline`

---

### Task 5: The playbook and the documents that describe the skill

**Files:**
- Modify: `skills/legwork/reference/methodology.md` (Phase 2 steps 1-3 become the playbook, capped at 30 lines), `skills/legwork/reference/subagent-brief.md`, `skills/legwork/SKILL.md` (retrieval policy becomes the two ladders, no longer than it is now), `skills/legwork/reference/quality-gates.md` (the snippet rule), `README.md`, `SECURITY.md`, `AGENTS.md`, `docs/design-notes.md`.

- [ ] **Step 1: Write the playbook** in `methodology.md`: three variants per angle, year-pin dated material only, explicit geo and language, open every page you cite, thin means fewer than two parties after three variants, log the failure before the fallback, record the query.
- [ ] **Step 2: Update `subagent-brief.md`:** the three variants in "How to work" step 1, the page ladder in step 2, `"query"` and `"opened"` in the return object, the lead-not-evidence rule.
- [ ] **Step 3: Update `SKILL.md`:** the two ladders as tables, `fetch.py` in the scripts table, the receipt format, the snippet rule in one line under Gates.
- [ ] **Step 4: Update `quality-gates.md`** Evidence layer with the snippet rule and the receipt warning.
- [ ] **Step 5: Update `README.md`** (backend table, gate paragraph, scripts table), `SECURITY.md` (three network paths, the `robots.txt` choice, temporary page text), `AGENTS.md` (conventions), `docs/design-notes.md` (a "Search was never measured" section carrying the 215-row table).
- [ ] **Step 6: Check every internal link resolves and the house style holds.** `grep -n -- '—\|–' skills/legwork/**/*.md docs/*.md *.md`
- [ ] **Step 7: Commit.** `docs: the query playbook and the retrieval ladders`

---

### Task 6: Evals

**Files:**
- Modify: `evals/evals.json`, `evals/README.md`
- Test: `skills/legwork/tests/test_evals.py`

- [ ] **Step 1: Add case 5** `open-the-page-rather-than-citing-the-snippet` with the observed failure (Evomotion, 2026-08-16, 18 of 29 cited sources snippet-only, gate passed, run filed), a prompt, and expectations covering opened rows, receipt agreement, traced figures and verified quotes.
- [ ] **Step 2: Add case 6** `get-through-a-blocked-primary-source` with the observed failure (eval case 1, 2026-08-13, three bank developer portals 403 to both arms), the case 1 prompt, and expectations covering `blocked` rows, the next rung being tried and logged, and `[unknown]` rather than a snippet-filled cell.
- [ ] **Step 3: Update `evals/README.md`** - the case table, and the note that cases 5 and 6 measure retrieval reach.
- [ ] **Step 4: Run `python3 -m pytest tests/test_evals.py -q`.**
- [ ] **Step 5: Commit.** `evals: two cases for retrieval reach`

---

### Task 7: Full verification

- [ ] **Step 1:** `python3 -m pytest tests/ -v` from `skills/legwork/`.
- [ ] **Step 2:** every MUST-fail fixture, including `snippet_only.md`, fails at deep and for its own reason only.
- [ ] **Step 3:** `python3 scripts/check.py --report tests/fixtures/valid_brief.md --format brief --level deep` passes.
- [ ] **Step 4:** `claude plugin validate .` and `bash -n install.sh`.
- [ ] **Step 5:** a live smoke test of `fetch.py` against one public page, reported with its actual output.
- [ ] **Step 6:** confirm no third-party import crept in: `grep -rn '^import \|^from ' skills/legwork/scripts/ | grep -v 'from __future__'` reviewed against the stdlib.
