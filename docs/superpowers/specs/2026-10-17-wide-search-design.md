# Wide search: many wordings across Google and Exa in one call, subagents still read the pages

**Date:** 2026-10-17
**Status:** design, approved section by section by Dan on 17 Oct 2026. Not built.
**Scope:** a new `skills/legwork/scripts/search.py`; two fixes in `bd_search.py`;
the gather step in `SKILL.md`; the subagent brief and `brief.py`; `SECURITY.md`,
`README.md`, `AGENTS.md`, `setup.sh`; tests; one eval.
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
- [Testing](#testing)
- [The eval](#the-eval)
- [Not yet known](#not-yet-known)
- [Out of scope](#out-of-scope)
- [Implementation order](#implementation-order)

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

Four lessons this design keeps:

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
| 8 | The full eval: three answer-keyed cases, three runs an arm | 17 Oct |

## Goal and pass test

A standard run in which each retrieval subagent sees far more candidate
sources for the same number of steps, and the report is at least as accurate.
Merged only on the eval below meeting decision 1.

## The design

### A. How a subagent uses it

1. Writes 6 to 10 wordings for its angle ([H](#h-wordings)).
2. Runs `search.py` once with all of them.
3. Reads the leads and Exa's unverified answer.
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
   lead appears in, each wording's Google list and Exa's citation order counted
   as separate lists. With a Jev key, each lead's `title + snippet` is scored
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
new function and an entry in one table; nothing else changes.

| Provider | How | Key |
|---|---|---|
| `google` | `bd_search.py "<wording>" -m general --engine google --country C --language L -c 10` | the Bright Data CLI's own login |
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
| Any other `bd_search.py` failure or empty result | Retried once; then recorded as failed |
| A Google call over 60 seconds | Stopped and recorded as timed out |
| The call over `--time-limit` (default 150 s) | Returns what has finished; lists the wordings and providers that did not |
| Every provider call failed, was refused or was unavailable | Prints `search: no search provider available - use WebSearch` and exits 4 |
| No Jev key, or Jev fails | RRF only; status line says `jev: off` or `jev: failed (<reason>)` |
| No `--tsv` and no `--out-dir` | Search record written under `/tmp/legwork/searches/` |

Exit codes: 0 when at least one provider call succeeded, even with no results
(the status line then says `0 leads`); 4 when every provider call failed, was
refused or was unavailable; 1 on bad arguments.

### E. Output

Plain text, not JSON, so a subagent's context holds as little as possible:

```
search: 9 wordings · google 9/9 ok · exa ok · jev on · 87 leads (top 40 shown) · 31s
 1. Acme pricing - Team and Enterprise plans
    https://acme.example/pricing
    "Team plan: $30 per user per month, billed annually..."   [g1 g2 g5 exa]
 2. ...
+47 more in RUN.searches/20261017T101500Z-what-does-the-incumbent-charge.json

Exa's written answer - UNVERIFIED, NOT A SOURCE. Open the cited pages before using anything in it:
    Acme charges $30 per user on its Team plan ...
```

- Snippets cut to 160 characters, titles to 100.
- `[g1 g2 g5 exa]` lists the Google wordings by number and Exa if it cited it.
- Exa's answer is cut to 1,500 characters, whitespace collapsed, and always
  printed last under that exact heading, so it cannot be mistaken for a lead.
- Failed or skipped providers and wordings appear in the status line, with
  details in the record.

### F. The search record

One JSON file per call: `<tsv without .tsv>.searches/<UTC stamp>-<angle slug>.json`
beside the run, or under `--out-dir`. It holds the date, the angle, every
wording, every provider result in full (including failures with their reason
and seconds), the merged leads with their scores, Exa's answer and its reported
cost, and whether Jev ran. It is the record of what was searched, for checking
a run and for the evals. Nothing reads it in the run itself.

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

The rule, stated once in `SKILL.md` and pointed at from the brief: for each
angle, 6 to 10 wordings of the same question as different people would put it.
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

- **`SKILL.md`, step 3.** The ladder's first rung becomes `search.py` with the
  angle's wordings, always when a provider is available; WebSearch becomes the
  same rung's second line, for two or three of the wordings, and the only route
  when `search.py` exits 4. The "at least three query variants" paragraph is
  replaced by the wording rule ([H](#h-wordings)). Logging, rounds, the refusal
  ladder and everything after are unchanged.
- **`reference/subagent-brief.md`.** Step 1 of "How to work" becomes: write the
  wordings, run `python3 {SKILL_DIR}/scripts/search.py ...` once, read the
  leads and treat Exa's answer as unverified, then WebSearch two or three of
  the wordings. "What to return" adds `serp` to the `via` values: a lead from
  `search.py` you did not open. The effort line reads `{n} to {m} wordings.`
  The return-only rule stays the last line.
- **`scripts/brief.py`.** The `BUDGET` marker becomes `'{n} to {m} wordings.'`
  and its argument is renamed `wordings`. Nothing else.
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

## Testing

Hermetic, as `AGENTS.md` requires: `subprocess.run` and `urlopen` patched, no
network. New `tests/test_search.py`, plus additions to `test_bd_search.py` and
`test_brief.py`.

- **Fan-out mapping:** each wording becomes one `bd_search.py` call with the
  right engine, country, language and count; the angle becomes one Exa request
  with the key header, a `User-Agent` and `text: true`; `--no-exa` sends none.
- **Merge:** two URLs that canonicalise alike become one lead carrying both
  wordings; the longest snippet wins.
- **Rank:** RRF orders a lead found by three lists above one found once; Jev
  scores average in when a key is present; Jev absent or raising leaves RRF.
- **Every row of the failure table**, including exit 4 and the time limit.
- **Output:** the status line; `--show` caps the list and the `+N more` line
  names the record; Exa's heading and 1,500-character cap; the answer printed
  last.
- **Search record:** its path beside the `.tsv`; its fields, failures included.
- **Nothing written to the `.tsv`** by `search.py`.
- **Logging:** a returned lead with `"via": "serp"` is logged as a lead and a
  citation resting on it is treated as unopened by the gate.
- **`bd_search.py`:** `yandex` refused by argparse; Bing gets `gb` and `en` by
  default.
- **Brief:** the filled brief contains the `search.py` command with the real
  path, the wordings budget, and still ends on the return-only line.

**Live check before the eval:** one real call on a sample angle with both
providers, by hand, output saved to `evals/runs/`.

## The eval

Before merge, recorded in `evals/runs/` whichever way it falls.

- **Cases:** banks, Postgres and campervan, the three with answer keys in
  `evals/keys/`.
- **Arms:** `main` and the branch, three runs each, on the current Sonnet,
  run a few at a time.
- **Grading:** blind against the keys, per `evals/grading.md`.
- **Merge if** the branch covers more core entities than `main` on average,
  states no more wrong facts, and makes no more scope errors. Time per question,
  Claude cost, Bright Data and Exa spend and searches run are reported.
- **Expected cost:** roughly $50 to $100 of Claude usage for 18 runs, plus a few
  pounds of search.

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
  receipt, rounds or independence counting.
- A separate repository or HTTP service. If a second caller appears, the module
  moves out; nothing in it imports legwork's log or gate.

## Implementation order

1. `bd_search.py` fixes (I), with tests.
2. `search.py` providers and failure handling (B 1, C, D), with tests.
3. Merge, rank, record and output (B 2-5, E, F), with tests.
4. `brief.py` and the brief (J), with tests.
5. `SKILL.md`, `AGENTS.md`, `README.md`, `setup.sh`, `SECURITY.md` (J, K).
6. Live check.
7. The eval; merge only on decision 1.
