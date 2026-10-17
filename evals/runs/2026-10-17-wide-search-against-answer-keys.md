# 2026-10-17 - wide search against the answer keys

**What:** the eval the wide-search spec makes a merge condition. Banks and
Postgres, two runs on `main` (`8e5f199`) and two on the branch (`8eb3213`),
on Sonnet 5.5, graded blind against the keys in `evals/keys/`. Run on 17 Oct
2026 from `~/legwork-evals/20261017/`, with the 27 Sep runner.

**Verdict: does not meet the bar for merging.** On banks the branch covered
fewer core banks than `main` and made more scope errors. On Postgres the
difference is within one entity and one error, so it is inconclusive.

## How it was graded

The eight reports were copied with the receipt line removed and given shuffled
labels; the map stayed outside the grading folder. One word that named the
branch's search service, in a list of leads in one Postgres report, was
removed. Each key was graded twice, blind and separately: by an Opus agent
with the prompts in `grading.md`, and by gpt-6-astra (runs
`20261017T190243Z-6295c3` and `20261017T190243Z-bc0829`) with the same rules.
The keys were not re-checked against live pages first; both arms were graded
against the same 27 Sep key.

"Wrong facts" is WRONG ratings plus other errors. Each figure is the mean of
two runs.

## Banks

| Banks, mean of 2 runs | `main` (Opus) | branch (Opus) | `main` (Astra) | branch (Astra) |
|---|---|---|---|---|
| Core covered (of 16) | 10 | 8 | 10.5 | 9 |
| Extras covered | 0 | 4 | 0 | 5.5 |
| Wrong facts | 1.5 | 0.5 | 1.5 | 2.5 |
| Scope errors | 0.5 | 1.5 | 1 | 2.5 |

Per run (Opus): `main` 8 and 12 core, the branch 8 and 8. `main`'s two runs
differ by four core banks, so two runs an arm is a small sample.

What the branch did differently: one run named 32 of the key's entities in some
form, against 20 and 22 for `main`'s runs, but researched only 8 core banks to a
stated requirement. NatWest, Santander, Nationwide, Monzo and Starling are in
that report as rows of `[unknown]` or as unread: Santander's page returned 503
on two routes, and Starling's and TSB's rendered empty. The other branch run
named 19.

## Postgres

| Postgres, mean of 2 runs | `main` (Opus) | branch (Opus) | `main` (Astra) | branch (Astra) |
|---|---|---|---|---|
| Core covered (of 9) | 7 | 7.5 | 7 | 7.5 |
| Extras covered | 1.5 | 0.5 | 2 | 0.5 |
| Wrong facts | 1 | 1 | 4 | 1.5 |
| Scope errors | 0 | 0 | 0 | 0 |
| Sound recommendations (Opus) | 2 of 2 | 1 of 2 | - | - |

Astra rated all eight recommendations WEAK. No report claimed UK GDPR requires
UK hosting.

## Against the merge rule

- **Core coverage higher in at least one case and lower in neither:** not met.
  Banks is lower by 2 core banks a run (Opus) and 1.5 (Astra). Postgres is
  higher by 0.5, within one entity, so inconclusive.
- **Wrong facts no higher in either case:** the graders disagree on banks
  (lower for Opus, higher for Astra); Postgres is no higher for either.
- **Scope errors no higher in either case:** not met on banks (higher by 1
  for Opus, 1.5 for Astra). Postgres has none in any report.

## Reported, not blocking

| Mean of 2 runs | `main` banks | branch banks | `main` Postgres | branch Postgres |
|---|---|---|---|---|
| Minutes | 14.0 | 24.4 | 10.9 | 10.6 |
| Claude cost | $3.37 | $3.75 | $4.69 | $1.99 |
| `search.py` calls (wordings) | - | 10 (84) | - | 9.5 (68) |
| `--more` used | - | 5.5 | - | 0 |
| WebSearch calls | 30 | 8 | 17 | 5.5 |
| Exa spend | - | $0.05 | - | $0.05 |

Bright Data spend was not metered per run; the branch's four runs sent 304
wordings to Google through it.

Claude cost for all eight runs: $27.60, against the $45 estimated.

## Seen on the way

- **Five of eight runs stopped after two failed gate cycles**, as `SKILL.md`
  says. Four stopped on saturation, two in each arm, because an angle was
  still finding new names or had had one round; one `main` Postgres run traced
  it to plan names of one vendor counting as new entities. The fifth, a branch
  banks run, stopped on three rows that cited no opened page. Three passed and
  were filed: both of `main`'s second runs and one branch banks run. Stopping
  at two cycles caps how many rounds a run gets, on `main` as much as on the
  branch.
- **The new own-site rule was visible in the reports.** Where a bank's own page
  could not be opened, the branch's reports marked the row `[unknown]` rather
  than citing an aggregator. Whether that, rather than search width, explains
  the lower core count was not tested.

Grades: `~/legwork-evals/20261017/grading/` (Opus scores as JSON beside the
reports; Astra's in `astra-*.txt`). The label map is
`~/legwork-evals/20261017/grading-key.json`.
