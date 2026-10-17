# Wide search: many wordings across Google and Exa in one call, subagents still read the pages

**Date:** 2026-10-17
**Status:** design, approved section by section by Dan on 17 Oct 2026. Not built.
**Scope:** a new `skills/legwork/scripts/search.py`; two fixes in `bd_search.py`;
an optional timeout on `fetch.py`'s Jev request;
the gather step in `SKILL.md`; the subagent brief and `brief.py`; entity sites in
`sources.py` and `ledger.py`; one gate check in `check.py`; `SECURITY.md`,
`README.md`, `AGENTS.md`, `setup.sh`; tests; one eval.
**Verified by:** gpt-6-astra, blind, in six passes (runs
`20261017T105734Z-17046b`, `20261017T111043Z-915654`,
`20261017T111655Z-481cad`, `20261017T112324Z-4420fb`,
`20261017T113100Z-bf0d16` and `20261017T113657Z-c9286f`); every finding is resolved in this version (see
[Review](#review)).
**Evidence:** the DBHQ research run `Wide_Search_Service_Research_20261016` in
`dbhq-uk/dbhq` (`docs/research/`), and this repo's `evals/runs/2026-09-2*`.

## Contents

- [Why, measured](#why-measured)
- [What the scripted-gathering trial taught](#what-the-scripted-gathering-trial-taught)
- [Decisions](#decisions)
- [Goal and pass test](#goal-and-pass-test)
- [The design](#the-design)
  - [A. How a subagent uses it](#a-how-a-subagent-uses-it)
  - [B. `search.py`](#b-searchpy)
  - [C. Providers](#c-providers)
  - [D. Failures](#d-failures)
  - [E. Output](#e-output)
  - [F. The search record](#f-the-search-record)
  - [G. What is logged](#g-what-is-logged)
  - [H. Wordings](#h-wordings)
  - [I. `bd_search.py` fixes](#i-bd_searchpy-fixes)
  - [J. Changes to the skill's text](#j-changes-to-the-skills-text)
  - [K. What leaves the machine](#k-what-leaves-the-machine)
  - [L. An entity's own site settles it](#l-an-entitys-own-site-settles-it)
- [Testing](#testing)
- [The eval](#the-eval)
- [Not yet known](#not-yet-known)
- [Out of scope](#out-of-scope)
- [Implementation order](#implementation-order)
- [Review](#review)

---

## Why, measured

All figures are from the 16 Oct 2026 research run unless marked.

- **Asking more ways is the biggest lever.** Over 8 questions, judged blind by
  two model families (Claude Sonnet and gpt-6-astra, agreeing on 80% of 202
  items), ten wordings on Google found 73 to 84 distinct useful sources against
  18 to 19 for today's single query.
- **Exa Answer finds what Google wordings miss.** One Exa Answer call per
  question returned 43 to 44 useful sources, 40 to 41 of them not found by any
  of the ten Google wordings. Adding it to the ten wordings took the total to
  113 to 125. It answered in a median of 2.0 seconds at about half a cent.
- **A second index in place of wordings loses.** Five Google wordings plus the
  same five on Ceramic found 51 to 58, against 73 to 84 for ten on Google.
- **Bright Data Google is slow.** A median of 13 to 17 seconds a call, up to
  90, with or without a dedicated SERP zone. Run one after another, ten
  wordings would take minutes; run in parallel, about the slowest call.
- **One wording at a time costs subagent steps.** Each search is a step that
  re-reads the subagent's whole conversation (`evals/runs/2026-09-27-scripted-gathering.md`).

**What these numbers do not show.** They count useful search results, not
whether a finished report was right. The trial below showed those differ.

## What the scripted-gathering trial taught

`docs/superpowers/specs/2026-09-27-scripted-gathering-design.md` built a script
that searched many phrasings, opened every result and handed Claude a reranked
digest, with no retrieval subagents. Graded blind against answer keys it was
**wider, not better**: across nine runs it stated 41 correct facts to `main`'s
27 and 15 wrong to `main`'s 7, with 7 scope errors to 1, and took 21 to 47
minutes against 8 to 16 (`evals/runs/2026-09-28-facts-against-answer-keys.md`).
The wrong facts came from aggregators and directories standing in for an
entity's own page, and from stale pages on the entity's own site.

Five lessons this design keeps:

1. **Subagents reading an entity's own pages is what keeps a report right.**
   This design widens what a subagent can see; it does not take the reading
   away.
2. **No filtering of search results.** Jev deciding what to open lost a tenth
   to a half of the evidence the runs relied on (`2026-09-25-jev-and-logging.md`);
   in the 16 Oct test 7 to 12 of 69 results Jev rejected were judged useful.
   Ranking only.
3. **One refused call must never stop the run.** The trial aborted on a single
   rate-limit refusal and lost 286 opened pages.
4. **Names come from sources, not memory.** Wordings name nothing that did not
   come from an earlier round.
5. **An entity's own page settles what it offers.** The trial's fix, a gate
   check that a matrix row about an entity cites that entity's own site
   (commit `b8a90a4`, on the closed branch), never reached `main`. It is
   rebuilt here for `main` ([L](#l-an-entitys-own-site-settles-it)).

## Decisions

| # | Decision | Dan |
|---|---|---|
| 1 | Pass test: wider, no less accurate. More core entities covered than `main`, no more wrong facts and no more scope errors; time and cost reported, not blocking | 17 Oct |
| 2 | Approach: a search tool for the existing subagents, which still choose and read primary pages (not scripted gathering, not Exa as a platform only) | 17 Oct |
| 3 | Providers in this build: Bright Data Google and Exa Answer. Bing behind a flag. Parallel, Brave and others later, each one function | 17 Oct |
| 4 | Every provider is optional: used when its key works, skipped with a stated reason when missing, out of credit or refusing | 16-17 Oct |
| 5 | Exa's written answer is shown, marked unverified and not a source | 17 Oct |
| 6 | Leads are not written to the run's `.tsv`; each call keeps its own search record | 17 Oct |
| 7 | WebSearch stays, for two or three of an angle's wordings | 17 Oct |
| 8 | The eval, cut for cost: banks and Postgres, two runs an arm (eight runs, about $45 of Claude usage at the 29 Sep rate). Campervan dropped: its key has three core entities and barely separates the arms | 17 Oct |
| 9 | The own-site rule is part of this build: subagents record each entity's own site, and the gate fails a matrix row about it that cites none of that site (option A of three) | 17 Oct |
| 10 | Subagents may make paid search calls through `search.py`; paid page retrieval (scrape, render, pipelines, Reddit) stays the orchestrator's | 17 Oct |

## Goal and pass test

A standard run in which each retrieval subagent sees far more candidate
sources for the same number of steps, and the report is at least as accurate.
Merged only on the eval below meeting decision 1.

## The design

### A. How a subagent uses it

1. Writes 6 to 10 wordings for its angle ([H](#h-wordings)).
2. Runs `search.py` once with all of them.
3. Reads the leads and Exa's unverified answer. If the top 40 do not answer the
   angle, reads the next 40 with `search.py --more` ([E](#e-output)).
4. Runs WebSearch on two or three of the wordings.
5. Opens the pages that would settle the question with `fetch.py`, exactly as
   today, and returns its JSON.

A later round repeats this with new wordings built from what the last round
found. Rounds, saturation and the entity rules are unchanged.

### B. `search.py`

```
search.py --angle "what does the incumbent charge" \
  --wording "..." --wording "..." [...]      # 1 to 12; 6 to 10 expected
  [--tsv RUN.tsv | --out-dir DIR]            # where the search record goes
  [--country gb] [--language en]             # passed to Bright Data
  [--engine google|bing|both]                # default google
  [--no-exa] [--show 40] [--time-limit 150]

search.py --more RECORD.json [--from 41] [--show 40]   # the next leads, no network
```

Standard library only, Python 3.9, `from __future__ import annotations`, like
every script here. In one call:

1. **Fan out, in parallel.** Each wording to Bright Data on the chosen engine,
   through `bd_search.py -m general` as a subprocess (so auth, zones and quota
   mapping stay in one place), 10 results each. The `--angle` text to Exa
   Answer once. A thread pool of up to 10.
2. **Merge.** Leads are keyed on `independence.canonicalize(url)`. A merged lead
   keeps every wording number and provider that found it, its best rank in each
   list, the longest snippet and the first title.
3. **Rank.** Reciprocal rank fusion, `sum(1 / (60 + rank))` over every list the
   lead appears in. There is one list per provider per wording - wording 3 on
   Google and wording 3 on Bing are two lists - and one for Exa's citations in
   the order Exa gave them. With a Jev key, each lead's `title + snippet` is scored
   against `--angle` on `fetch.py`'s four levels, in batches of 30, and the
   final score is the mean of RRF scaled to the top lead and the Jev expected
   score. The 27 Sep offline test found the mean of a lexical and a Jev score
   the best of the three (`evals/runs/2026-09-27-rerank-offline.md`). Without
   Jev, RRF alone. **Nothing is dropped.**
4. **Write the search record** ([F](#f-the-search-record)).
5. **Print** the compact output ([E](#e-output)).

It reuses `fetch.py`'s `typesafe_key`, `_jev_request`, `_expected_score` and
`JEV_LEVELS`, and `independence.canonicalize`. It writes nothing to the `.tsv`.

### C. Providers

Each provider is one function, `search_<name>(query, options) -> ProviderResult`,
where a result is `{'provider', 'query', 'ok', 'reason', 'seconds', 'results':
[{'url', 'title', 'snippet', 'rank', 'date'}]}`. Adding a provider later is a
new function and an entry in one table; nothing else changes, except that a
search engine asked once per wording also needs its name in `ENGINES`, because
`--engine` chooses among those engines.

| Provider | How | Key |
|---|---|---|
| `google` | `bd_search.py "<wording>" -m general --engine google --country C --language L -c 10`. Its stdout is JSON with `results`, each carrying `rank`, `title`, `url`, `snippet` and `date`; exit 2 means auth or quota, any other non-zero exit a failure | the Bright Data CLI's own login |
| `bing` | the same with `--engine bing`; only with `--engine bing` or `both` | the same |
| `exa` | `POST https://api.exa.ai/answer`, body `{"query": angle, "text": true}`, header `x-api-key`, a `User-Agent` set (Cloudflare refused Python's default with 403 on 16 Oct). Citations become results in order; `text` becomes the snippet, first 600 characters, whitespace collapsed; `answer` is kept separately | `EXA_API_KEY`, else `~/.dbhq/legwork/exa-api-key` |
| Jev | ranking only, as `fetch.py` | as `fetch.py` |

### D. Failures

No failure of one provider or one wording stops the call.

| Case | Behaviour |
|---|---|
| No Exa key | Exa skipped; status line says `exa: no key` |
| Exa HTTP error, timeout or bad JSON (out of credit, rate limit, refusal) | Exa skipped for this call; the reason (status code and first 120 characters of the body) printed and recorded |
| Bright Data CLI missing | Google skipped; `google: not installed` |
| `bd_search.py` exit 2 (auth or quota) on a wording | That wording recorded as refused; the others carry on |
| `bd_search.py` exits non-zero (not 2), or its stdout is not JSON | Retried once; then recorded as failed |
| `bd_search.py` exits 1 with `SERP returned zero organic results` in its stderr | A success with zero results: `bd_search.py` reports an empty SERP that way, and its exit stays as it is because subagents calling it directly rely on it to fall down the ladder. Not retried, not a failure; counts towards exit 0 |
| Exa returns no citations | A success with zero results, as above |
| A Google call over 60 seconds | Its subprocess is killed by the wrapper below; recorded as timed out, and retried once only if the deadline allows |
| The whole call reaches `--time-limit` (default 150 s) | See the deadline contract below |
| Every provider call failed, was refused or was unavailable | Prints `search: no search provider available - use WebSearch` and exits 4 |
| No Jev key, or Jev fails | RRF only; status line says `jev: off` or `jev: failed (<reason>)` |
| No `--tsv` and no `--out-dir` | Search record written under `/tmp/legwork/searches/` |

**The deadline contract.** `--time-limit` is wall-clock from start and bounds
every network call: searching, retries and Jev. After it the command does only
local work - ranking at most a few hundred leads, writing one JSON file and
printing - with no network and no waiting on another process. That work is not
time-bounded, because nothing can bound a write to a terminal that has stopped
reading; it is measured, and the status line reports the total seconds. Python cannot kill a thread, so
the guarantee rests on two things: every blocking call has a timeout no longer
than the time left, and nothing the main thread waits on can outlive the
deadline.

- **Workers are daemon threads** (`threading.Thread(daemon=True)`), at most 10
  at a time, pulling from a queue. The main thread waits on a result queue with
  a timeout and never joins a worker, so a stuck worker cannot hold the process
  open after output is printed.
- **Every `bd_search.py` call goes through one wrapper:** `subprocess.Popen(...,
  start_new_session=True)`, its handle kept in a shared set, then
  `communicate(timeout=min(60, time left))`. On timeout, and for every handle
  still in the set at the deadline, the wrapper kills the whole process group
  (`os.killpg(proc.pid, signal.SIGKILL)`), so the Bright Data CLI that
  `bd_search.py` starts dies with it. Where `os.killpg` does not exist
  (Windows), `start_new_session` is not passed and `proc.kill()` is used; the
  CLI child may then outlive it, which the status line does not hide. A retry starts only if at least 15 seconds
  remain.
- **Exa** uses `urlopen(..., timeout=min(30, time left))`.
- **Jev** runs only if at least 20 seconds remain. `fetch._jev_request` gains
  an optional `timeout=60` argument; existing callers are unchanged. All Jev
  batches start in parallel, each with `timeout=` the time left minus 5
  seconds. If any batch fails or times out, all Jev scores are discarded and
  ranking is RRF alone, so no lead is scored on a different basis from another;
  the status line says `jev: failed` or `jev: skipped (time)`.
- **Searching stops 3 seconds before the limit.** At `--time-limit` minus 3
  seconds the main thread stops waiting, records each unfinished wording,
  provider or Jev batch as `deadline`, kills the remaining process groups,
  ranks what it has, writes the record and prints. Jev's own budget is counted
  against the same point.

Tests patch `subprocess.Popen` and `os.killpg` for these calls. They drive a
`bd_search.py`, an Exa call and a Jev batch that never return, together and
apart, and assert that the network phase - the record's `network_seconds` -
ends within the limit (plus one 0.25-second polling interval), and that
`killpg` was called for the hanging process group. The whole command gets a
loose bound only: on 17 Oct 2026 a run with the CPU three times oversubscribed
took 2.6 seconds over the limit doing local work, which this section does not
promise to bound.

Exit codes: 0 when at least one provider call succeeded, even with no results
(the status line then says `0 leads`); 4 when every provider call failed, was
refused or was unavailable; 2 on bad arguments (argparse's own exit code).

### E. Output

Plain text, not JSON, so a subagent's context holds as little as possible:

```
search: 9 wordings · google 9/9 ok · exa ok · jev on · 87 leads (top 40 shown) · 31s
 1. Acme pricing - Team and Enterprise plans
    https://acme.example/pricing
    "Team plan: $30 per user per month, billed annually..."   [g1 g2 g5 exa]
 2. ...
+47 more: search.py --more RUN.searches/20261017T101500Z-what-does-the-incumbent-charge.json --from 41

Exa's written answer - UNVERIFIED, NOT A SOURCE. Open the cited pages before using anything in it:
    Acme charges $30 per user on its Team plan ...
```

- Snippets cut to 160 characters, titles to 100.
- `[g1 g2 g5 b2 exa]` lists the lists the lead came from: `g` for Google and
  `b` for Bing with the wording's number, and `exa` if Exa cited it.
- Exa's answer is cut to 1,500 characters, whitespace collapsed, and always
  printed last under that exact heading, so it cannot be mistaken for a lead.
- Failed or skipped providers and wordings appear in the status line, with
  details in the record.
- `--more RECORD --from N` prints leads N to N+`--show`-1 from a saved record,
  in the same format, with no network and no Exa answer. This is how the
  ranking stays an order rather than a cut: every lead is one command away.

### F. The search record

One JSON file per call: `<tsv without .tsv>.searches/<UTC stamp>-<angle slug>.json`
beside the run, or under `--out-dir`. It holds the date, the angle, every
wording, every provider result in full (including failures with their reason
and seconds), the merged leads with their scores, Exa's answer and its reported
cost, whether Jev ran, `network_seconds` (when every network call had ended or
been abandoned) and `seconds` (the whole call). It is the record of what was searched, for checking
a run and for the evals, and the source `--more` reads.

### G. What is logged

The run's `.tsv` receives only what subagents return, as today:

- a page the subagent opened, through `fetch.py` and `sources.py log-returns`,
  with page text and the quote checked against it;
- a lead it relied on without opening, returned with `"via": "serp"` and
  `"opened": false`, which the log and the gate already treat as a search
  result (`SNIPPET_VIA`).

So the receipt, concentration, independence and saturation keep measuring what
the run relied on, not how much it searched.

### H. Wordings

The rule lives once, in `SKILL.md`, between the lines
`<!-- wordings-rule -->` and `<!-- /wordings-rule -->`. `brief.py` copies that
block into the brief where the template has `{WORDINGS_RULE}`, the same way it
fills the template's other markers, and refuses to run if either marker is
missing. The orchestrator and the subagent read the same text, and there is
one copy to change. The rule: for each angle, 6 to 10 wordings of the same question as different people would put it.
At least: a plain one; one aimed at the primary party's own site (`site:`, an
exact phrase or `filetype:pdf`); a buyer's; a practitioner's; a critic's; and
one negative one built from the falsifier. Year-pin only what is dated. **Name
no organisation, product or site** unless it came from "Already found" or an
earlier round's sources. A `site:` wording therefore waits until a round has
named the party.

### I. `bd_search.py` fixes

- `--engine` drops `yandex`: the CLI cannot return JSON for it and every call
  failed on 16 Oct.
- A Bing search with no `--country` defaults to `gb`, and `--language` to `en`;
  without them Bright Data returned Bing results in a Spanish locale.

### J. Changes to the skill's text

Each rule changes in one place (`AGENTS.md`, "Each rule is stated once").

- **`SKILL.md`, step 3.** The "at least three query variants" paragraph is
  replaced by the marked wording rule ([H](#h-wordings)), which now also says
  how searching goes: `search.py` once with all the wordings whenever a
  provider is available, then WebSearch for two or three of them, WebSearch
  alone when `search.py` exits 4, and `--more` when the first 40 leads do not
  answer the angle. The ladder table's first row becomes `search.py` and its
  WebSearch row says "as the wording rule above says", with no number of its
  own. The paragraph "Subagents use the free rungs only" gains one exception
  (decision 10): they may run `search.py`, which makes paid search calls;
  paid page retrieval stays the orchestrator's. Every `brief.py` example uses
  `--wordings`. Logging, rounds, the refusal ladder and everything else are
  unchanged.
- **`reference/subagent-brief.md`.** Step 1 of "How to work" becomes the
  `{WORDINGS_RULE}` marker followed by the exact command,
  `python3 {SKILL_DIR}/scripts/search.py --angle "<your angle>" --wording "..." [...] --tsv "{TSV}"`,
  with no restatement of the rule. "What to return" adds `serp` to the `via`
  values and rewrites the transport sentence so the two cannot overlap: `serp`
  for a `search.py` lead you did not open, `websearch` for a WebSearch result
  you did not open. It also lets an entity be an object with its own site
  ([L](#l-an-entitys-own-site-settles-it)). The effort
  line reads `{n} to {m} wordings.` The return-only rule stays the last line.
- **`scripts/brief.py`.** `BUDGET` becomes `'{n} to {m} wordings.'`; the filled
  line reads `'{} to {} wordings.'`. `DEFAULT_SEARCHES` becomes
  `DEFAULT_WORDINGS`, `{'narrow': (6, 8), 'comparison': (8, 10)}`. The
  `--searches` flag becomes `--wordings`, with no alias, and `fill()`'s
  `searches` parameter becomes `wordings`. New markers `{WORDINGS_RULE}` (filled
  from `SKILL.md`) and `{TSV}` (filled from `--tsv` when given, otherwise
  `RUN.tsv` as a literal the subagent replaces). A missing `SKILL.md` marker is
  a `TemplateChanged` error, like a missing template marker.
- **`AGENTS.md`.** Layout lists `search.py`. The provider convention becomes:
  `search.py`'s providers (Bright Data, Exa) and Jev are each optional; with
  none available the run falls back to WebSearch, so a run still completes with
  no CLI and no keys.
- **`README.md`, `setup.sh`.** The optional Exa key, how to set it, and that
  without it `search.py` runs on Google alone. `setup.sh` reports whether a key
  is present and never prompts for it.

### K. What leaves the machine

`SECURITY.md` gains: each wording goes to Bright Data as search text (as with
`bd_search.py` today); the angle text goes to Exa; with a Jev key, lead titles
and snippets and the angle go to TypeSafe.

### L. An entity's own site settles it

**Returned.** In a subagent's `entities` object an entity may be a string, as
today, or `{"name": "Acme", "site": "acme.example"}`. The site is the entity's
own domain, recorded only when the subagent opened a page on it. Strings keep
working, so earlier replies and evals parse unchanged.

**Stored.** `sources.parse_entities` is unchanged: it still returns
`(angle, name)` pairs, so its caller in `log-returns` is untouched; for an
object entity it takes `name`. A new `sources.parse_entity_sites(text)` returns
`(angle, name, site)` for object entities that carry a site. `log-returns`
passes those to `ledger.record_round`, which gains an optional `sites=()`
argument of `(name, site)` pairs. The ledger keeps them under
`entry['sites'][full]`, where `full` is `ledger.full_name(name)`, a new
function: Markdown presentation removed first (`**`, `__`, single `*` and `_`
used as emphasis, backticks, `[text](url)` reduced to `text`, and citation
markers such as `[3]`), then
lowercased with whitespace collapsed. Words and parentheses are kept.
It is **not** the `distinctive()` key, which can merge different entities
("Acme Analytics", "Acme Hosting"), and it keeps parentheses, so "Acme (UK)"
and "Acme (US)" stay apart. Each value is a list of distinct
`ledger.site_key(site)` results, a new function and **not** `party_of`:
`party_of` reduces `analytics.example.com` and `hosting.example.com` to one
party, which is right for counting independent voices and wrong for "is this
the entity's own site". `site_key` prefixes `https://` when the site has no
scheme, then returns the host lowercased without `www.`. For a host that
`party_of` treats as a path tenant (`independence.PATH_TENANT_HOSTS`, such as
`github.com`, `pypi.org` or `npmjs.com`) it returns the host plus the site's
**whole** path, lowercased, without a trailing slash - not `party_of`'s value,
which keeps one segment and so reduces every PyPI project to
`pypi.org/project`. A site that gives an empty key is not stored. `party_of` itself is unchanged; a later round can add a site but never removes one. Ledger
files without `sites` load as before. Nothing about saturation changes: a site
never makes an entity new, and `entities` is still keyed by `distinctive()`.

**Checked.** A new `check.py` function, `check_rows_on_own_site(parsed,
entries, rows, tsv_path, problems)`, ported from `b8a90a4`. It is reached
through `check_matrix_section`, which gains a keyword argument
`tsv_path=None`; `run()`, its only caller, passes the `tsv_path` it already
holds, and the ledger is read from `ledger.path(tsv_path)` - the run's real
log, never a filename guessed from the report. Existing calls without
`tsv_path` skip the check. The call goes **inside the existing standard and
deep block**, after the opened-citation loop, so it follows that block's level
policy: not run at quick, and not run when there are no bibliography entries
or no log rows (a run with no log rows already fails the gate elsewhere). Rows
come from `matrix.parse_matrix`, whose `cells` maps each field to its text;
"every cell is `[unknown]`" means every value in `cells`, stripped, equals
`[unknown]` case-insensitively. A row is checked only when all of these hold:

- `ledger.full_name()` of its entity cell **equals** a key in some angle's
  `sites`. Exact match only: no containment, no first-word matching. A row
  named differently from the recorded entity is not checked, so the check can
  miss a row but never passes one on another entity's site. If the same key
  is in several angles, their site lists are combined;
- at least one of its cells is not `[unknown]` (`b8a90a4` skipped a row with
  any `[unknown]` cell; that exemption is dropped);
- it cites at least one bibliography entry.

A checked row fails as a structural error unless at least one of its cited
URLs both **belongs to** one of that entity's recorded sites **and** is in
`opened_urls(rows)`, the existing set of pages actually read. A URL belongs to
a host site when its host, lowercased without `www.`, equals the site or ends
with `.` plus the site (so `docs.acme.example` belongs to `acme.example`, and
`hosting.example.com` does not belong to `analytics.example.com`); it belongs
to a path-tenant site when its host matches and its path, split on `/`, starts
with every segment of the site's path (so `github.com/acme/repo` belongs to
`github.com/acme`, and `pypi.org/project/beta` does not belong to
`pypi.org/project/alpha`). An
own-site URL seen only in search results does not count. The message is worded
as in `b8a90a4`: cite a page you opened on its own site, or mark the cells
`[unknown]`. An entity with no recorded
site is not checked. With no ledger, the check does nothing. It changes no
band, no count and no other check.

## Testing

Hermetic, as `AGENTS.md` requires: `subprocess.run`, `subprocess.Popen`,
`os.killpg` and `urlopen` patched, no network. New `tests/test_search.py`, plus additions to `test_bd_search.py` and
`test_brief.py`.

- **Fan-out mapping:** each wording becomes one `bd_search.py` call with the
  right engine, country, language and count; the angle becomes one Exa request
  with the key header, a `User-Agent` and `text: true`; `--no-exa` sends none.
- **Merge:** two URLs that canonicalise alike become one lead carrying both
  wordings; the longest snippet wins.
- **Rank:** RRF orders a lead found by three lists above one found once; Jev
  scores average in when a key is present; Jev absent or raising leaves RRF.
- **Every row of the failure table**, including the zero-result message from
  `bd_search.py` (exit 0), Exa with no citations, exit 4, and the deadline
  contract with a `bd_search.py` and an Exa call that never return.
- **Bing:** with `--engine both`, each wording yields a `g` and a `b` list,
  fused separately and labelled separately.
- **`fetch._jev_request`:** the new `timeout` reaches `urlopen`; its default
  stays 60.
- **Output:** the status line; `--show` caps the list and the `+N more` line
  names the record; Exa's heading and 1,500-character cap; the answer printed
  last.
- **Search record:** its path beside the `.tsv`; its fields, failures included.
- **Nothing written to the `.tsv`** by `search.py`.
- **Logging:** a returned lead with `"via": "serp"` is logged as a lead and a
  citation resting on it is treated as unopened by the gate.
- **`bd_search.py`:** `yandex` refused by argparse; Bing gets `gb` and `en` by
  default.
- **Brief:** the filled brief contains the wording rule copied from `SKILL.md`,
  the `search.py` command with the real path and the `--tsv` path, the
  wordings budget from the new defaults, and still ends on the return-only
  line; a missing `SKILL.md` marker raises `TemplateChanged`; `--searches` is
  rejected.
- **`--more`:** reads a record and prints the requested slice; past the end it
  prints nothing and says so; it makes no network call.
- **Entity sites:** a string entity and an object entity both parse into the
  same `parse_entities` pairs; `parse_entity_sites` returns only object
  entities with a site; a site is stored once per party and survives a later
  round; a site never counts as a new entity; a ledger file with no `sites`
  loads; "Acme Analytics" and "Acme Hosting" keep separate sites.
- **The own-site check:** a row citing only an aggregator for an entity with a
  recorded site fails; the same row citing one page on the site passes; an
  all-`[unknown]` row passes; a partly-`[unknown]` row is still checked; a row
  for "Acme Analytics" citing only Acme Hosting's site fails; a row for "Acme
  Hosting" is not checked against a recorded "Acme"; "Acme (UK)" and "Acme
  (US)" keep separate sites; a row whose only own-site citation was never
  opened fails; an entity with no site is not checked; no ledger, or a call
  without `tsv_path`, means no check; a bare-domain site matches a cited page
  on it and on its subdomains; `analytics.example.com` and
  `hosting.example.com` stay separate sites and a row for one citing only the
  other fails; `github.com/acme` and `github.com/other` stay separate, and so do
`pypi.org/project/alpha` and `pypi.org/project/beta`, and two npm packages; a row
  labelled `**Acme**`, `[Acme](https://acme.example)` or `Acme [3]` is checked
  against a recorded "Acme"; and the check runs end to end through
  `check.run()` on a report, a log and a ledger, at standard, and not at quick. A new must-fail fixture, `own_site_missing.md`, fails for that
  reason only, and joins the `AGENTS.md` table.

**Live check before the eval:** one real call on a sample angle with both
providers, by hand, output saved to `evals/runs/`.

## The eval

Before merge, recorded in `evals/runs/` whichever way it falls. Cut for cost
(decision 8).

- **Cases:** banks and Postgres, from `evals/keys/`. Campervan is left out: its
  key has three core entities, so it barely separates the arms.
- **Arms:** `main` and the branch, two runs each, on the current Sonnet, run a
  few at a time.
- **Grading:** blind against the keys, per `evals/grading.md`, four anonymised
  reports per key.
- **Measures, per case, each the mean of two runs:** core entities covered
  (the grader's "covered", not "mentioned"); wrong facts, which are the
  grader's WRONG ratings plus its "other errors"; scope errors.
- **Merge if, judged per case and never pooled:** core coverage is higher than
  `main`'s in at least one of the two cases and lower in neither; wrong facts
  are no higher than `main`'s in either case; scope errors are no higher than
  `main`'s in either case.
- **Reported, not blocking:** time per question, Claude cost, Bright Data and
  Exa spend, searches run, and how often subagents used `--more`.
- **Expected cost:** about $45 of Claude usage for eight runs at the 29 Sep
  rate ($5.60 to $6.40 a run, `evals/runs/2026-09-29-saturation.md`), plus a
  few pounds of search. Two runs an arm is noisier than three; a result within
  one entity or one error either way is reported as inconclusive rather than
  as a pass or a fail.

## Not yet known

- **Whether more leads bring back the trial's failure.** More aggregator pages
  in view may tempt subagents to cite them. The existing gate rule that a
  matrix row must cite the subject's own site is the guard; the eval's wrong
  facts and scope errors are the measure.
- **Whether WebSearch for two or three wordings is enough** to keep the pages
  only it finds (20 cited against Bright Data's 14 on 24 Sep, 6 in common).
- **The right `--show`.** 40 is a starting value; the eval's step counts and
  costs will show whether subagents read that many.
- **Exa's quality on legwork's questions.** Measured on 8 questions and on
  snippets only.

## Out of scope

- Parallel Responses, Brave, Ceramic and any other provider (decision 3).
- Opening pages, extracting passages or digests in `search.py`: subagents open
  pages, as today.
- Jev filtering, Jev support checks, and any change to the gate, bands,
  receipt, rounds or independence counting beyond the own-site check
  ([L](#l-an-entitys-own-site-settles-it)).
- A separate repository or HTTP service. If a second caller appears, the module
  moves out; nothing in it imports legwork's log or gate.

## Implementation order

1. `bd_search.py` fixes (I), with tests.
2. Entity sites in `sources.py` and `ledger.py`, and the own-site check with its
   fixture (L), with tests.
3. `search.py` providers and failure handling (B 1, C, D), with tests.
4. Merge, rank, record, output and `--more` (B 2-5, E, F), with tests.
5. The marked wording rule in `SKILL.md`, `brief.py` and the brief (H, J), with
   tests.
6. The rest of `SKILL.md`, `AGENTS.md`, `README.md`, `setup.sh`, `SECURITY.md`
   (J, K).
7. Live check.
8. The eval; merge only on decision 1.

## Review

gpt-6-astra verified the first version blind against eight constraints (run
`20261017T105734Z-17046b`, read-only, with the repository open). It ruled three
held and five broken, and each is resolved here:

| Finding | Resolution |
|---|---|
| Leads past the top 40 were unreachable in a run, so the ranking acted as a filter | `search.py --more` ([E](#e-output)) |
| The search procedure was written in both `SKILL.md` and the brief | One marked block in `SKILL.md`, copied by `brief.py` ([H](#h-wordings)) |
| The spec relied on an own-site gate check that is not on `main` | Built here (decision 9, [L](#l-an-entitys-own-site-settles-it)) |
| `brief.py`'s defaults and output still said searches, 2 to 8 | Specified in full ([J](#j-changes-to-the-skills-text)) |
| The pass test did not say per case or pooled, nor what counts as wrong | Per case, never pooled; WRONG plus other errors ([The eval](#the-eval)) |

The second pass (run `20261017T111043Z-915654`, with the spec and every code
excerpt it depends on pasted in, after a first attempt could not read files)
confirmed the five resolutions and found three more, each resolved:

| Finding | Resolution |
|---|---|
| The brief tells subagents to make paid calls; `SKILL.md` restricts them to free rungs | An explicit exception for `search.py` only (decision 10, [J](#j-changes-to-the-skills-text)) |
| `parse_entities` returning triples would break three unpackings in `log-returns` | `parse_entities` unchanged; a separate `parse_entity_sites` and an optional `sites` argument ([L](#l-an-entitys-own-site-settles-it)) |
| Sites keyed by `distinctive()` let one entity's site pass another's row | Keyed and matched on the full normalised name, with a collision test ([L](#l-an-entitys-own-site-settles-it)) |
| The ladder repeated the "two or three wordings" number | The ladder points at the marked rule ([J](#j-changes-to-the-skills-text)) |

The third pass (run `20261017T111655Z-481cad`) confirmed the second pass's
fixes and found six more, each resolved:

| Finding | Resolution |
|---|---|
| `serp` and the existing `websearch` instruction overlapped | The transport sentence is rewritten so each tool has one value ([J](#j-changes-to-the-skills-text)) |
| The own-site check had no route to the run's ledger | `check_matrix_section(..., tsv_path=None)`, passed by `run()` ([L](#l-an-entitys-own-site-settles-it)) |
| An empty result was both a failure and a success | Zero results is a success; only a non-zero exit or bad JSON is a failure ([D](#d-failures)) |
| The time limit had no cancellation contract | The deadline contract, with a never-returning provider test ([D](#d-failures)) |
| Containment matching and dropped parentheses still let entities collide | Exact match on the full name, parentheses kept ([L](#l-an-entitys-own-site-settles-it)) |
| An unopened own-site URL could satisfy the check | The own-site citation must also be in `opened_urls(rows)` ([L](#l-an-entitys-own-site-settles-it)) |

The fourth pass (run `20261017T112324Z-4420fb`, with `check.py`'s `run()`,
`bd_search.py`'s SERP path and `fetch.py`'s Jev helpers added) confirmed the
transport, ledger-path, full-name and opened-citation fixes and found five
more, each resolved:

| Finding | Resolution |
|---|---|
| A thread pool cannot be cancelled, and killing `bd_search.py` leaves its CLI child running | Daemon workers, process groups killed with `killpg`, a timeout on every blocking call ([D](#d-failures)) |
| `bd_search.py` reports zero results as exit 1, so zero results could not be a success | `search.py` recognises that exact message as zero results; `bd_search.py` is unchanged because subagents rely on its exit ([D](#d-failures)) |
| `_jev_request` hard-codes a 60-second timeout | An optional `timeout` argument; all batches in parallel; any failure discards Jev scores ([D](#d-failures)) |
| Bing's place in the ranking and labels was unspecified | One list per provider per wording; `g` and `b` labels ([B](#b-searchpy), [E](#e-output)) |
| `party_of` returns nothing for a bare domain, and the check's place among the early returns was unstated | `https://` prefixed before `party_of`; the call sits inside the standard and deep block ([L](#l-an-entitys-own-site-settles-it)) |

The fifth pass (run `20261017T113100Z-bf0d16`, reporting only major and
blocker findings) confirmed the fourth pass's fixes, ruled C1 to C8 held at
design level, and found two more in C9, each resolved:

| Finding | Resolution |
|---|---|
| `party_of` merges distinct sites under one registrable domain, so one entity's site could pass another's row | A separate `site_key` keeps the host (or tenant); a cited URL belongs to a site by host or subdomain; `party_of` unchanged ([L](#l-an-entitys-own-site-settles-it)) |
| Markdown in a matrix entity cell (`**Acme**`, a link) stopped the name matching | `full_name` removes Markdown presentation first ([L](#l-an-entitys-own-site-settles-it)) |
| The deadline test allowed two seconds over the limit | Searching stops 3 seconds early; the test asserts the whole command finishes within the limit ([D](#d-failures)) |

The sixth pass (run `20261017T113657Z-c9286f`, C4 and C9 only, major and
blocker findings only) found two more, each resolved:

| Finding | Resolution |
|---|---|
| No timeout can bound ranking, writing and printing, so "the whole command within the limit" was a promise nothing could keep | The limit bounds every network call; the local work after it is measured and reported, not promised ([D](#d-failures)) |
| `party_of` keeps one path segment on `pypi.org` and `npmjs.com`, so two packages shared one tenant site | Path-tenant sites keep their whole path and match by segment prefix ([L](#l-an-entitys-own-site-settles-it)) |

After six passes the findings had narrowed from design to edge cases in one
check; the remaining risk is carried by that check's tests and by the eval.
