# Search pipeline: reach further, record what was reached

**Date:** 2026-09-06
**Status:** draft, awaiting review
**Scope:** `skills/legwork/scripts/`, the retrieval sections of `SKILL.md`,
`methodology.md`, `subagent-brief.md`, the templates, the evals, and the
three top-level docs that describe what the skill touches.

## Contents

- [The problem, measured](#the-problem-measured)
- [Goal and principles](#goal-and-principles)
- [The retrieval ladder](#the-retrieval-ladder)
- [Components](#components)
  - [A. The gate sees opened versus seen](#a-the-gate-sees-opened-versus-seen)
  - [B. The fetch log records more, and checks itself](#b-the-fetch-log-records-more-and-checks-itself)
  - [C. `fetch.py`, a free direct fetch that yields page text](#c-fetchpy-a-free-direct-fetch-that-yields-page-text)
  - [D. `bd_search.py` catches up with the CLI](#d-bd_searchpy-catches-up-with-the-cli)
  - [E. The query playbook](#e-the-query-playbook)
  - [F. Documents that describe the skill](#f-documents-that-describe-the-skill)
  - [G. Evals](#g-evals)
- [One angle, end to end](#one-angle-end-to-end)
- [Error handling](#error-handling)
- [Testing](#testing)
- [Compatibility](#compatibility)
- [Out of scope](#out-of-scope)
- [Implementation order](#implementation-order)

## The problem, measured

The fetch logs of one real run and six eval runs were read on 2026-09-06.
Seven logs, 215 rows.

| Log | Rows | `numbers` filled | Snippet-only rows (`via=websearch`) |
|---|---|---|---|
| Evomotion, real, standard, 2026-08-16 | 29 | 0 | 18 (62%) |
| Eval case 1, Sonnet | 34 | 0 | 0 |
| Eval case 2, Haiku | 9 | 0 | 5 |
| Eval case 2, Sonnet | 38 | 0 | 1 |
| Eval case 2, Opus | 96 | 0 | 20 |
| Eval case 3, Sonnet | 3 | 0 | 0 |
| Eval case 4, Sonnet | 6 | 1 | 1 |

Five things follow from those logs and the code that reads them.

1. **A search snippet passes as a fetched page.** `check_evidence` in
   `check.py` treats every row with status `ok` as opened, whatever its
   `via`. In the Evomotion run 18 of the 29 cited sources were never opened:
   the quote is a search snippet and the page was not read. The run passed
   the gate and was filed. The README's claim that the gate "fails a report
   that cites a page nobody opened" is not true for this case.
2. **Figure tracing never fires in practice.** The `numbers` column is
   filled on 1 row in 215. `WebFetch` returns a model summary rather than
   page text, so there is no file to hand to `--text-file`, and the check
   silently skips when it has nothing to compare against. It is proven by
   fixtures and dead in production, the exact failure the design notes warn
   about.
3. **There is no query strategy.** The whole search instruction is "search
   with `WebSearch`, year-pinned". No operators, no variants, no targeting of
   the primary domain, no definition of "thin coverage", no geo handling for
   a UK user on a US-centric engine. Year-pinning every query pulls "best X
   2026" round-ups, the aggregator content the skill distrusts. The
   Bright Data fallback fired on 0 of 29 retrievals in the real run, and
   the wrapper exposes none of the CLI's `--engine`, `--language`, `--page`,
   `--type shopping`, `discover`, `browser` or the forty-odd pipelines
   beyond Reddit.
4. **Nothing records what the search did.** Queries run, results returned,
   fetches that failed, fallbacks taken: none are logged. Every row in every
   log has status `ok`. The receipt line states angles and sources only, so
   "search is not performing" cannot be seen, let alone measured.
5. **The scrape cap truncates to a navigation shell.** Measured in eval
   case 4: two primary fetches returned navigation rather than body text,
   and the head-truncate at 8,000 characters made it worse.

## Goal and principles

Reach further and record what was reached, so that a run finds more, gets
through more of what blocks it, and every claim it makes traces to page text
somebody has on disk.

- **Reach.** More ways through a blocked or client-rendered page, a second
  search engine with geo and language control, and the platform pipelines
  for the source kinds the skill already names (reviews, job ads, company
  profiles, community).
- **Accuracy.** Quotes verified verbatim against page text, figures traced
  against page text, dates read from the page rather than guessed.
- **Free first.** The order stays: built-in search, then a free direct
  fetch, then the built-in fetch, then paid. A run against ordinary sources
  still makes zero paid calls.
- **Mechanism over prose.** Every rule here lands in a script or the gate
  where it can, per AGENTS.md. The playbook is the only prose addition and
  is capped at thirty lines.
- **Hermetic tests.** Nothing in `tests/` touches the network. Fetching is
  tested through mocked transport and pure functions.

## The retrieval ladder

For a search, in order:

1. `WebSearch`, three query variants per angle (see E).
2. Bright Data SERP (`bd_search.py -m general`) on a second engine, with
   `--country` and `--language`, when the angle is thin or geo-specific.
3. Bright Data `discover` (`bd_search.py -m discover`) when two engines are
   still thin: an intent-ranked search that can return page content in the
   same call.

For opening a page, in order:

1. `fetch.py` - free, direct, returns page text to a file, extracts title,
   date and numbers, prints keyword windows.
2. `WebFetch` - free, model-summarised. Used when `fetch.py` reports the page
   as blocked or a shell and the page is not worth paying for.
3. `bd_search.py -m scrape` - paid, Web Unlocker.
4. `bd_search.py -m render` - paid, headless browser, for client-rendered
   pages that scrape returns as a shell.
5. `bd_search.py -m pipeline` - paid per record, for platforms that block
   everything above (Reddit, LinkedIn, Google Maps reviews, app stores, X,
   YouTube comments, Amazon reviews, Crunchbase).

Quick level stays snippet-first by design. Standard and deep open every page
they cite; the gate enforces it (A).

## Components

### A. The gate sees opened versus seen

`check.py`, `check_evidence`:

- Build `opened` from rows with status `ok` and `via` other than
  `websearch`. Build `seen` from every `ok` row, as now.
- A cited URL in `seen` but not in `opened` is graded: "cited from a search
  snippet, page never opened: [N]". Warning at standard, error at deep,
  ignored at quick, through the existing `Problems.graded`.
- The "cited but never fetched" check keeps its meaning and its wording.
- The "rests on no recorded evidence" check is unchanged. A snippet quote is
  still a recorded quote; it is the snippet rule above that names the
  weakness.

`check.py`, receipt:

- The receipt line gains an opened count. New format in both templates:

  `*[level] · [N] angles · [N] sources ([N] opened, [N] via Bright Data) · [N] disconfirming searches · [what changed]*`

- `RECEIPT_RE` is unchanged; it is deliberately loose. A new warning at
  every level compares a stated `(\d+) opened` against the log's opened
  count and warns on a mismatch. This is the "reports compliance it did not
  achieve" failure applied to retrieval, and it is a warning because the
  receipt is hand-written and the log is the record.

### B. The fetch log records more, and checks itself

`sources.py`:

- **`query` column.** Appended last to `TSV_COLUMNS`, after `quote`, so a
  log written before it existed still parses positionally. `log --query`
  is optional. `read_rows` already fills missing trailing fields with
  empty strings.
- **`direct` transport.** Added to `VIA_VALUES`, for pages opened with
  `fetch.py`. `check.py` and `independence.py` treat it as they treat
  `webfetch`.
- **`--status blocked`.** Already accepted; the playbook now says to log a
  failed open with it before falling back. `resume` already separates
  `failed` rows and the receipt (below) counts them.
- **Numbers from the quote.** In `cmd_log`, when neither `--text-file` nor
  `--numbers` supplies tokens, `extract_numbers(quote)` fills the column.
  The quote is verbatim page text, so a figure inside it did appear on the
  page. Numbers from a text file remain the strong form; the JSON printed
  by `log` says which form was used (`"numbers_from": "text" | "quote"`).
- **Quote verification.** When both `--text-file` and `--quote` are given,
  normalise both (collapse whitespace, unify curly quotes and dashes,
  case-fold) and test containment. Print `"quote_verified": true|false` in
  the JSON and a one-line stderr warning when false. No new column; the
  transport already tells a reader which rows could have been verified.
- **`log --from-fetch PATH.json`.** Reads the JSON that `fetch.py` writes
  and fills `--url`, `--title`, `--date`, `--text-file` and `--via direct`
  from it. The agent supplies `--angle`, `--kind`, `--quote` and `--query`.
  Explicit flags override the file.
- **`receipt --tsv PATH`.** Prints one line for pasting into the receipt:
  `N sources · N opened · N snippet-only · N via Bright Data · N blocked ·
  N queries`. `--format json` for the hook and tests. `finish.py` prints
  it after the gate result so the two are seen together.
- **`resume`** lists distinct queries per angle alongside the counts it
  already prints, so a refresh sees what was asked and not only what came
  back.

### C. `fetch.py`, a free direct fetch that yields page text

New script, standard library only, Python 3.9.

```
fetch.py URL [--out PATH] [--find TERM ...] [--window 300] [--max-hits 5]
         [--timeout 30] [--json]
```

**Transport.** `urllib.request` with a browser-like `User-Agent`, `Accept`,
`Accept-Language` and `Accept-Encoding: gzip`; follows redirects; one
attempt, no retry; no cookies sent or stored; no credentials; never runs
JavaScript. Does not consult `robots.txt`: this is a single page opened on
explicit request, the same as a browser would, and the sites that object to
that already sit behind the paid path. That is a policy choice and is stated
in `SECURITY.md` so a reader can disagree with it.

**Text extraction.** An `html.parser.HTMLParser` subclass that drops
`script`, `style`, `noscript`, `svg`, `nav`, `header`, `footer`, `aside`,
`form` and `template`, emits a newline at block boundaries, decodes
entities and collapses whitespace. `text/plain` is taken as is.
`application/pdf` uses `pdftotext` if it is on `PATH`, otherwise exits with
code 4 and says so.

**Metadata.** Title from `og:title` then `<title>`. Date, first hit wins:
`article:published_time`, `og:updated_time`, `datePublished` or
`dateModified` in JSON-LD, `<time datetime>`, `<meta name="date">`,
`last-modified` header. Normalised to `YYYY-MM-DD`; absent stays absent
rather than guessed. Canonical URL from `<link rel="canonical">` when
present.

**Shell and block detection.** Exit 3 with a stated reason when any of:
HTTP 401, 403, 429 or 503; a Cloudflare or similar challenge marker in the
body ("Just a moment", "Enable JavaScript and cookies", "Checking your
browser"); extracted text under 400 characters; or link density above 0.6,
meaning most of the text sits inside anchors, which is what a client-rendered
page looks like to a plain fetch. The reason names the next rung: `WebFetch`
for a shell that is not worth paying for, `bd_search.py -m scrape` for a
block, `-m render` for a shell.

**Output.** Text to `--out`, default `${TMPDIR:-/tmp}/legwork/<sha1(url)
[:12]>.txt`. Scratch, never inside the run folder: the log stores the quote
and the numeric tokens, not the page, and that stays true. A sidecar JSON
with the same stem and a `.json` extension holding `url`, `final_url`, `http_status`,
`content_type`, `title`, `date`, `chars`, `text_file`, `numbers` (count),
`verdict` (`ok | blocked | shell | pdf`), `reason`, and `find`. The same
JSON goes to stdout.

**`--find`.** For each term, case-insensitive, up to `--max-hits` windows of
`--window` characters either side, with the match marked. This is how the
agent reaches the sentence it will quote without reading twenty thousand
characters into context, and it replaces the blind head-truncate as the way
a long page is made small.

### D. `bd_search.py` catches up with the CLI

CLI 0.2.0 was read on 2026-09-06.

**SERP (`-m general | news | images | shopping`).**

- Pass through `--engine google|bing|yandex`, `--language`, `--page`,
  `--device`. `-c` stays a client-side trim; `--page` is how you go deeper.
- `-m shopping` maps to `--type shopping`; normalise `name`, `price`,
  `link`, `source` into the existing result shape with `snippet` carrying
  the price and seller.
- Drop the `scholar`, `academic`, `patents` and `people` aliases. They
  silently degrade to web search and let an agent believe it searched a
  vertical it did not. An unknown mode fails with the list of real ones.

**Discover (`-m discover`).** `brightdata discover QUERY --intent TEXT
--country --language --num-results N [--start-date] [--end-date]
[--filter-keywords] [--include-content]`. Wrapper flags: `--intent`
(required for this mode), `--since YYYY-MM-DD`, `--must-contain a,b`,
`--with-content`. Uses the pipeline timeout. Results are normalised to the
SERP shape plus an optional `content` field per result, so a thin angle can
get pages in the same call it gets results.

**Scrape (`-m scrape`).** After the Unlocker returns markdown: strip
link-list and navigation blocks with the same cleaner `fetch.py` uses
(shared by importing `fetch.py`), then apply `--find` windows, then
`--max-chars`. Write the cleaned text to `--out` with the same default
scratch path and JSON sidecar as `fetch.py`, so `log --from-fetch` and
`--text-file` work on paid fetches too. The 8,000 character policy cap
stays, applied after cleaning and windowing rather than before.

**Render (`-m render`).** For client-rendered pages: `brightdata browser
open URL`, then `browser get`, then `browser close`, on a session named for
the run so parallel subagents do not share one. Same cleaner, `--find`,
`--out` and sidecar. Timeout 60 seconds.

**Pipelines (`-m pipeline --pipeline NAME PARAMS...`).** Generalises the
Reddit special case; `-m reddit` stays as an alias for `--pipeline
reddit_posts`. Any name from `brightdata pipelines list` is accepted and
passed through with its positional parameters. The docstring carries a
short table of which pipeline suits which source kind, for the agent
choosing one:

| Source kind the claim needs | Pipelines |
|---|---|
| `review_aggregate` | `google_maps_reviews`, `facebook_company_reviews`, `amazon_product_reviews`, `apple_app_store`, `google_play_store` |
| `job_ad` | `linkedin_job_listings` |
| `community` | `reddit_posts`, `x_posts`, `youtube_comments` |
| `registry`, company facts | `linkedin_company_profile`, `crunchbase_company`, `zoominfo_company_profile`, `yahoo_finance_business`, `github_repository_file` |
| `vendor_pricing`, market price | `google_shopping`, `amazon_product_search` |
| news | `reuter_news` |

Pipelines are billed per record. The wrapper cannot limit what the pipeline
collects, only what it prints (`-c`), so the docstring says to check
`brightdata budget` and to use a pipeline only when every free rung and
`scrape` have failed on that platform.

**Unchanged.** Exit code 2 on auth or quota with the login hint; JSON on
stdout, JSON error on stderr; the CLI holds the credentials.

### E. The query playbook

Prose, capped at thirty lines, replacing steps 1 to 3 of "Work
sub-question by sub-question" in `methodology.md` Phase 2. The rules:

- **Three variants per angle, minimum.** A plain query. A targeted query:
  `site:` the primary party's domain, an exact phrase in quotes, or
  `filetype:pdf` for filings and specifications. A negative query built
  from the angle's falsifier ("X limitations", "why we left X", "X price
  increase").
- **Year-pin dated material only.** Prices, releases, regulation and news
  get the year. Evergreen primary pages do not carry a year, so run the
  unpinned form for those; the pinned form alone pulls round-ups.
- **Geo and language are explicit.** `WebSearch` is US-centric. A question
  about a UK, EU or other market runs its SERP through `bd_search.py
  --country XX --language YY` on a second engine as one of the variants.
- **Open every page you cite** with `fetch.py`, then up the ladder. At
  standard and deep a snippet is a lead, not evidence; the gate says so.
- **Thin means fewer than two independent parties after three variants.**
  Thin routes to Bright Data SERP on a different engine, then `discover`
  with an intent line. Thin after that is a finding: say what was searched.
- **Log the failure before the fallback.** A blocked or shell open gets
  `--status blocked` in the log, then the next rung is tried. The receipt
  counts them.
- **Record the query on every row.** `--query` is what makes "search is not
  performing" answerable next time.

`subagent-brief.md` changes in step: "How to work" step 1 becomes the three
variants; step 2 names `fetch.py` and the ladder; the per-source return
object gains `"query"` and `"opened": true|false`; one rule line says a URL
returned without opening is a lead, not evidence, and the orchestrator logs
it `--via websearch`. `SKILL.md` "Retrieval policy" becomes the
two ladders above in the same table form it uses now, no longer.

### F. Documents that describe the skill

- `README.md`: the search backend table gains the direct-fetch rung, the
  render rung and the pipelines; the gate paragraph states the snippet rule.
- `SECURITY.md`: network paths become three, in order: built-ins,
  `fetch.py` from the user's machine with a browser user agent and no
  cookies, Bright Data. "Stores no cache of fetched pages between runs"
  stays true and gains "page text is written to a temporary directory
  during a run, not into the output".
- `AGENTS.md` conventions: "A search snippet is not a fetched page. A row
  with `via=websearch` is a lead; the gate treats a citation resting only on
  such rows as unopened at standard and deep." The MUST-fail table gains
  `snippet_only.md`.
- `docs/design-notes.md`: a section "Search was never measured", carrying
  the table at the top of this spec and the reasoning for the ladder.
- Both templates: the new receipt format.

### G. Evals

Two cases, each reproducing an observed failure per the evals README rule.

- **Case 5, `open-the-page-rather-than-citing-the-snippet`.** Observed:
  Evomotion run, 2026-08-16, 18 of 29 cited sources snippet-only, gate
  passed, run filed. Prompt: a standard-level product-fit question against
  a small UK vendor whose pages fetch cleanly. Expectations: every cited
  source has an opened row; receipt states the opened count and it matches
  the log; figures trace; quotes verified where the transport allows.
- **Case 6, `get-through-a-blocked-primary-source`.** Observed: eval case 1,
  2026-08-13, three bank developer portals returned 403 to both arms and
  the run noted this as the discriminator it did not measure. Prompt: the
  case 1 prompt. Expectations: blocked opens are logged with status
  `blocked`; the next rung is tried and logged; rows that remain unverified
  are `[unknown]` in the matrix rather than filled from a snippet.

After implementation, re-run cases 1, 2, 5 and 6 on the skill arm, Sonnet,
and record the run under `evals/runs/`.

## One angle, end to end

Angle: "what does the incumbent charge". Date anchored as 2026-09-06.

1. `WebSearch`: `acme pricing`; `site:acme.example pricing`;
   `acme price increase 2026`.
2. `fetch.py https://acme.example/pricing --find "per user"` prints a
   window containing "Team plan: 30 US dollars per user per month, billed
   annually", `date: 2026-07-01`, `verdict: ok`, and the text file path.
3. `sources.py log --tsv "$OUT/$BASE.tsv" --from-fetch
   /tmp/legwork/ab12cd34ef56.json --angle "what does the incumbent charge"
   --kind vendor_pricing --query "site:acme.example pricing" --quote "Team
   plan: 30 US dollars per user per month, billed annually."` prints
   `quote_verified: true`, `numbers_from: text`.
4. A competitor's pricing page returns 403. `fetch.py` exits 3, reason
   `blocked`. The agent logs it `--status blocked`, then
   `bd_search.py URL -m scrape --find "per user" --out ...` succeeds and is
   logged `--via brightdata --from-fetch`.
5. The receipt reads `2 sources (2 opened, 1 via Bright Data)`. `check.py`
   finds both citations opened, the figure 30 traced, dates present.

## Error handling

| Script | Exit | Meaning | Next rung |
|---|---|---|---|
| `fetch.py` | 0 | text on disk | log it |
| `fetch.py` | 1 | network or parse error | `WebFetch` |
| `fetch.py` | 3 | blocked or shell, reason given | `WebFetch` or `bd_search.py -m scrape`, then `-m render` |
| `fetch.py` | 4 | unsupported content type (PDF without `pdftotext`) | `WebFetch` |
| `bd_search.py` | 1 | CLI failure, JSON on stderr | next rung or record as unverified |
| `bd_search.py` | 2 | auth or quota | tell the user to run `brightdata login`; do not retry |
| `sources.py log` | 0 with `quote_verified: false` | quote not found in page text | re-take the quote from the window |
| `check.py` | graded | snippet-only citation | open the page or drop the citation |

Every failure is logged before the fallback, so the receipt's blocked count
is the record of what the run could not reach.

## Testing

**Fixtures.** `snippet_only.md` and `.tsv`: a valid brief whose cited rows
are all `via=websearch`, each carrying a quote and a date, so the snippet
rule is the only check that can fire. MUST fail at deep, warn at standard,
pass at quick. Added to the MUST-fail lists in `AGENTS.md` and
`.github/workflows/validate.yml`. `valid_brief.tsv` and `valid_report.tsv`
gain a `query` column so the round trip is exercised on the fixtures the CI
already runs.

**`test_check.py`.** Snippet rule at the three levels; a `webfetch` row for
the same URL clears it; receipt opened-count mismatch warns and a match does
not; existing fixtures unchanged in verdict.

**`test_sources.py`.** Eleven-column write and read; a ten-column log reads
with `query` empty; `direct` accepted as `via`; numbers from the quote when
no text file, and `numbers_from` reports which; quote verification true,
false, and unaffected by whitespace and curly quotes; `--from-fetch` fills
and explicit flags override; `receipt` counts opened, snippet-only,
blocked, Bright Data and queries; `resume` lists queries per angle.

**`test_fetch.py`.** All pure: HTML to text drops the listed elements and
keeps block breaks; entities decode; each date form is found and
normalised, and a page with none yields empty; link density and short-text
shell detection; challenge markers; `--find` windows and the hit cap; PDF
branch with `pdftotext` absent exits 4; `urlopen` mocked to return 403 and
the script exits 3 with reason `blocked`. No socket is opened in any test.

**`test_bd_search.py`.** `subprocess.run` mocked. Argument mapping for each
mode, including `--engine`, `--language`, `--page`, `shopping`, `discover`
flags, `render` command sequence, `pipeline` pass-through and the `reddit`
alias; dropped aliases fail with the mode list; shopping and discover
normalisation; scrape output cleaned, windowed, written to `--out` with a
sidecar.

**`test_evals.py`.** Already asserts case shape; the two new cases must
carry `observed_failure`, `prompt`, `expectations`.

**Hook.** `gate_on_stop.py` needs no change; it calls `check.py`, which
gains only graded problems and a warning.

## Compatibility

- Old logs (ten columns) read unchanged. A log started by old code and
  appended by new code has a ten-column header, so the eleventh field is
  dropped on read; acceptable, and `resume` says when a log has no
  `query` data.
- `RECEIPT_RE` unchanged; old receipts pass without the opened count and
  simply get no receipt-mismatch warning.
- `-m reddit` keeps working. `-m scholar|academic|patents|people` stop
  working, by design, with a message.
- Standard library only, Python 3.9 floor, `from __future__ import
  annotations` in the new script.

## Out of scope

- Replacing `WebSearch` as the primary search. Paid search on every query
  contradicts "free by default"; the second engine is for thin and
  geo-specific angles.
- A keyless tier that scrapes search-engine HTML. Rejected in the design
  notes for the maintenance cost; still rejected.
- Changes to the independence or corroboration maths.
- The model carve-out for subagents.
- Logging queries that returned nothing usable as rows. They are recorded
  in the subagent's `gaps` object and in Limitations, as now; a row needs a
  URL.

## Implementation order

Each step is a PR-sized unit with its own tests and leaves the suite green.

1. **Log and gate.** B (all but `--from-fetch`), A, templates, the
   `snippet_only` fixture, `AGENTS.md` and CI MUST-fail lists.
2. **`fetch.py`** and `log --from-fetch`.
3. **`bd_search.py`**, importing the cleaner from `fetch.py`.
4. **Playbook, brief, `SKILL.md` retrieval policy, README, SECURITY,
   design notes.**
5. **Evals**: cases 5 and 6, then the re-run of 1, 2, 5, 6 and its record.

Work starts on a fresh branch from `main` once the prose cut on
`refactor/cut-the-prose` has merged, so the playbook lands on the shorter
`methodology.md` and not the longer one.
