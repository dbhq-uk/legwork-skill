# 2026-09-29 - saturation: wide enough, measured

**What:** three findings on 29 Sep 2026, each graded blind against the answer
keys in `evals/keys/`, three runs an arm.

## 1. The newer model is cheap because it is shallow

`--model sonnet` now resolves to Sonnet 5.5. `main` on it cost $0.66 to $2.38
a run and took 3 to 7 minutes, against $2 to $9 and 8 to 16 on Sonnet 5, and
eight of nine runs used no retrieval subagents. Graded: as accurate on
Postgres and campervan, but 5 core banks a run of 16, against 12 on Sonnet 5.
It dropped half the list and nothing told it the list was unfinished.

Haiku retrieval subagents saved nothing: $51.06 against $48.63 on Sonnet 5,
and $23.76 against $9.88 on Sonnet 5.5, with no accuracy gain.

## 2. Wide enough, defined (Dan, 29 Sep 2026)

- Each angle runs round by round until a round finds nothing new: a new
  entity on a list angle, a new independent party on any other.
- Cap: 3 rounds at standard, none at deep, 1 at quick. An angle capped while
  still finding things is reported as not saturated.
- Every entity found is researched, or listed under Found, not researched
  with a reason. Subagents set aside what is plainly out of scope themselves,
  with a reason, and those never count as new.
- The gate fails a standard or deep run with no recorded rounds, an open
  angle, a capped angle not reported, or an entity dropped.

## 3. The result

| Banks, 3 runs each | `main` on Sonnet 5 | saturation, first | saturation, with scope fix |
|---|---|---|---|
| Core covered per run (of 16) | 10, 14, 14 | 12, 10, 8 | 11, 11, 11 |
| Extras covered | 0 | 2 | 10 |
| Correct / partly / wrong | 17 / 16 / 3 | 15 / 15 / 2 | 23 / 12 / 1 |
| Scope errors | 1 | 7 | 4 |
| Claude cost | $22.79 | $17.14 | $16.90 |

| Postgres, 3 runs each | `main` on Sonnet 5 | `main` on Sonnet 5.5 | saturation, first |
|---|---|---|---|
| Core covered (of 27) | 18 | 17 | 24 |
| Extras covered | 3 | 0 | 9 |
| Correct / partly / wrong | 11 / 7 / 3 | 13 / 3 / 1 | 18 / 13 / 2 |
| Sound recommendations | 1 of 3 | 3 of 3 | 3 of 3 |
| Claude cost | $16.81 | $2.51 | $19.20 |

**Verdict: merged.** Saturation is the only version that is both wide and
accurate on the newer model, at 74% (banks) and 114% (Postgres) of Sonnet 5
`main`'s cost. It is not cheap: the newer model's saving is spent on the
rounds. Quick stays the cheap, narrow level.

**Still open:** scope errors are 4 against `main`'s 1 - e-money firms listed
among challenger banks - and Griffin and Virgin Money were missed by most runs
of every arm.

Grades: `~/legwork-evals/20260929/grading/`, `grading2/`, `grading3/`.
