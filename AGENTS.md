# AGENTS.md

Guidance for AI agents (and people) working in this repository.

## What this is

**Legwork** - a decision-research skill for AI coding agents. It produces cited findings where every claim states how well it is supported, judges a source by whether it suits the claim it backs, and refuses to ship a finding it cannot support. It follows the [Agent Skills](https://agentskills.io) layout (`skills/<name>/SKILL.md`) and ships as a [Claude Code plugin](https://code.claude.com/docs/en/plugins).

## Layout

```
.claude-plugin/plugin.json     # plugin manifest
skills/legwork/SKILL.md        # the skill (agent-facing instructions)
skills/legwork/scripts/        # python, standard library only
skills/legwork/reference/      # methodology (four phases), quality gates
skills/legwork/templates/      # brief + report
skills/legwork/tests/          # offline, no network
install.sh / install-codex.sh  # local symlink installers (Claude / Codex)
docs/design-notes.md           # why the skill is shaped the way it is
```

## Conventions

- **Standard library only.** No `requirements.txt`, no virtualenv. This is load-bearing: it is what lets the same paths work across Claude, Codex and plugin installs. CI asserts it, so an added third-party import fails the build rather than quietly breaking the install story.
- Python floor is **3.9**. Every script carries `from __future__ import annotations` so PEP 604 syntax parses there.
- SKILL.md references scripts via `${CLAUDE_SKILL_DIR}` (the skill's own directory), which Claude Code substitutes for personal, project and plugin installs alike. `install.sh` therefore symlinks the whole skill directory into `~/.claude/skills/` with no rewrite. `install-codex.sh` rewrites the variable, since Codex does not substitute it.
- Bright Data is a **fallback**, never a requirement. Anything that assumes it is installed is a bug: the built-in `WebSearch`/`WebFetch` are the primary providers and a run must complete without a CLI present.
- Tests are hermetic - no network, ever. The gate makes no network calls at all.
- **Corroboration must be counted on the layer the pipeline does not amplify.** Gather deliberately fans out to find more sources per finding, so a source count measures our own effort. Independence groups reached from *different search angles* is the real signal. A change that makes corroboration rise with breadth has broken the check, whatever the tests say.
- House style: British English, plain hyphens (no em or en dashes).

## Validating a change

```bash
cd skills/legwork
python3 -m pytest tests/ -v                  # no network
python3 scripts/check.py --report tests/fixtures/valid_brief.md --format brief --level deep
python3 scripts/check.py --report tests/fixtures/invalid_report.md --level deep      # MUST fail
python3 scripts/check.py --report tests/fixtures/unfetched_citation.md --level deep  # MUST fail
python3 scripts/check.py --report tests/fixtures/one_origin.md --level deep          # MUST fail
cd ../.. && claude plugin validate .         # manifest + structure
```

The three fixtures that MUST fail are the important ones - they exist so the gate is proved to bite. Each covers a different failure mode: `invalid_report.md` a truncated document, `unfetched_citation.md` a citation to a page nobody opened, `one_origin.md` a strong claim resting on a single line of enquiry. A change that makes any of them pass has broken the gate, even if every other test is green.
