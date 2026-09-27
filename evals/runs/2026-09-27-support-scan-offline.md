# 2026-09-27 - the support scan, offline: not built

**What:** component F of the scripted-gathering spec - Jev reads every passage
a run gathered and marks each as supporting, contradicting or not addressing a
finding - tested before it was built, as the spec required.

**How:** 28 findings from seven 24 Sep reports (banks, Postgres, accountancy).
For each, every passage from every page the run opened (pages re-opened with
`fetch.py` on 27 Sep; median 453 passages a pool) was scored for support of the
finding's heading, and the passage the report actually quoted was located in
the ranking. The free term match was the baseline.

| Scorer | Quoted passage in top 5 | Top 10 | Top 20 |
|---|---|---|---|
| Jev support score | 7% | 10% | 17% |
| Term match on the finding | 10% | 14% | 21% |

**Decision: not built.** Neither scorer puts the evidence a finding rests on
near the top, so a scan built on them would hand Claude the wrong passages.
Claude checks each finding against the digest instead, which is the spec's
stated fallback.

**Why it may understate, recorded so the question is not closed for the wrong
reason.** A finding such as "eight of nine banks need no authorisation for the
sandbox" is supported by dozens of passages, and the one the report happened to
quote need not be the most supportive. A test with labelled support and
contradiction, rather than "the passage the report quoted", would measure the
scan properly. That is the test to run before revisiting it.
