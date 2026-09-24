# 2026-09-24 - the subagent brief comes from a script

**Arms:** two runs of the banks prompt (cases 1 and 6) on `feat/brief-script`,
Claude Sonnet 5, with `LEGWORK_SKILL_DIR` on the branch. Compared with the
banks run in [`2026-09-24-matrix-snippet-rows.md`](2026-09-24-matrix-snippet-rows.md),
which is where the defect was found.

## Why

`subagent-brief.md` said to paste its template verbatim, and the template's
step 2 is a command: `python3 {SKILL_DIR}/scripts/fetch.py "<url>" --find`. In
the matrix run the orchestrator retyped the brief and turned that command into
"using a fetch tool or WebFetch". Its nine subagents made 103 WebFetch calls
and 4 `fetch.py` calls, and nearly every source reached the log without its page
text. A written instruction to paste something verbatim is exactly the kind of
rule a model negotiates with.

`scripts/brief.py` now fills the template - date, angle, effort line, and the
real path to the skill's scripts - and prints the brief. It reads the template
from `subagent-brief.md`, so the brief is still written down once, and it
refuses to run if a placeholder there is renamed or lost. `SKILL.md` step 3 says
to run it and put the printed text in the subagent's prompt.

## Result

| | matrix run: brief retyped | run 1 | run 2 |
|---|---|---|---|
| Subagent prompts carrying the `fetch.py` command | 0 of 9 | 0 of 4 as text - see below | **3 of 3** |
| Subagent `fetch.py` / `WebFetch` calls | 4 / 103 | 59 / 14 | 16 / 6 |
| Log rows / carrying figures / quotes checked true | 36 / 1 / 0 | 38 / 17 / 19 | 19 / 13 / 12 |
| Brief files left in the research folder | 0 | 4 | 0 |
| Time / cost | 14 min / $7.55 | 11 min / $5.69 | 13 min / $4.09 |

**Run 1 used the script and then passed its output the wrong way.** It wrote
each brief to a file in the run folder and gave each subagent the prompt
`$(cat <file>)`. A prompt is text, not a shell, so that is what arrived; all
four subagents read the file the path named and followed it, which is why the
page text came through. The outcome was right and the mechanism was luck, and it
left four brief files beside the report. `SKILL.md` now says the printed text
goes in the prompt, and that `$(cat file)` or a path reaches the subagent as
those characters. Run 2, with that sentence, put the full brief - about 700
words, the `fetch.py` command with a real path in it - in all three prompts,
and left nothing in the folder.

Run 2 is smaller than the others - three subagents, 19 log rows, 17 `[unknown]`
cells - and its gate warnings include one quote checked and not found on the
page. That is the verification catching a misquote, not the brief failing.

## What this does not settle

Two runs. The script removes the chance to paraphrase the brief; it cannot stop
an orchestrator skipping the script, and neither run did.
