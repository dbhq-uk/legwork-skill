# 2026-09-27 - quality against answer keys

**What:** the first test of whether a report is right, not only whether it
passes the gate. For banks, Postgres and campervan an answer key was built
from primary sources by an agent that saw no report: which entities belong in
the answer, core or extra, and the facts that matter for each, every row
quoted from the entity's own page. Three runs of `main` and three of the
branch (after the no-drop change, 74d0625) per case, eighteen reports,
anonymised with the receipt line removed and graded against the key by one
grader per case. Keys and scores: `~/legwork-evals/20260927/keys/`,
`~/legwork-evals/20260927/grading/`.

| Case | Key | Core covered, `main` → branch | Facts wrong, `main` → branch | Scope errors, `main` → branch |
|---|---|---|---|---|
| banks | 51 in scope, 16 core | 12.7 → 12.3 of 16 (extra 0 → 5) | 3 → 6 | 0 → 10 |
| Postgres | 18, 9 core | 6.0 → **8.7** of 9 | 4 → 7 (other errors 10 → 19) | - |
| campervan | 5, 3 core | 1.3 → 1.7 of 3 | 0 → 0 | 3 → 6 |

**Claude cost** over the same eighteen runs: the branch was 65% of `main`
($31.85 against $48.63), and took 18 to 49 minutes against 8 to 16.

**Verdict: wider, not better.** The branch covered more of what belongs -
every Postgres core provider in two runs of three, five extra banks a run
against none - and got more of it wrong. The wrong claims share a source:
aggregators, directories and reviews, which is where a wide search finds an
entity, standing in for the entity's own page, which is what settles it.
Examples: a supplier of pre-built units sold as flat-pack, Nationwide's
sandbox as free sign-up when it needs an Open Banking Directory statement,
AWS's retired twelve-month free tier. `main`, whose subagents read each
vendor's pages in depth, was narrower and more careful.

**Changes made from it** (14ab54a and after):

1. A matrix row about a researched subject must cite the subject's own site,
   or mark its cells `[unknown]`; the gate fails it otherwise. Replayed over
   the nine branch reports it fails five rows.
2. Each subject's round-2 digest gives half its passages to the subject's own
   site.
3. Four faults that cost steps: later rounds re-asked to account for round 1's
   parties, pages opened in plan order starving the last subjects, bare site
   names not recognised, quotes missing rows on path case or a home-page
   canonical link.

**Not caught by any rule:** a report that cites the supplier's own page and
still misreads it (one called that same pre-built supplier flat-pack with its
own page cited), and entities the report lists with every cell `[unknown]`,
which graders counted as claiming a sandbox that was never confirmed.
