# AGENTS.md

Guidance for AI agents (and people) working in this repository.

## What this is

**Legwork** - a multi-source research skill for AI coding agents, producing citation-tracked findings with evidence persistence and claim-level verification. It follows the [Agent Skills](https://agentskills.io) layout (`skills/<name>/SKILL.md`) and ships as a [Claude Code plugin](https://code.claude.com/docs/en/plugins).

## Layout

```
.claude-plugin/plugin.json     # plugin manifest
skills/legwork/SKILL.md        # the skill (agent-facing instructions)
skills/legwork/scripts/        # python, standard library only
skills/legwork/reference/      # phase methodology, gates, assembly, continuation
skills/legwork/templates/      # brief + report + HTML templates
skills/legwork/schemas/        # source / evidence / claim / run_manifest
skills/legwork/tests/          # 105 tests, offline
install.sh / install-codex.sh  # local symlink installers (Claude / Codex)
docs/design-notes.md           # why the skill is shaped the way it is
```

## Conventions

- **Standard library only.** No `requirements.txt`, no virtualenv. This is load-bearing: it is what lets the same paths work across Claude, Codex and plugin installs. CI asserts it, so an added third-party import fails the build rather than quietly breaking the install story.
- Python floor is **3.9**. Every script carries `from __future__ import annotations` so PEP 604 syntax parses there.
- SKILL.md references scripts via `${CLAUDE_SKILL_DIR}` (the skill's own directory), which Claude Code substitutes for personal, project and plugin installs alike. `install.sh` therefore symlinks the whole skill directory into `~/.claude/skills/` with no rewrite. `install-codex.sh` rewrites the variable, since Codex does not substitute it.
- Bright Data is a **fallback**, never a requirement. Anything that assumes it is installed is a bug: the built-in `WebSearch`/`WebFetch` are the primary providers and a run must complete without a CLI present.
- Tests are hermetic - no network, ever. The offline citation path is asserted explicitly.
- House style: British English, plain hyphens (no em or en dashes).

## Validating a change

```bash
cd skills/legwork
python3 -m pytest tests/ -v                  # 105 tests, no network
python3 scripts/validate_report.py --report tests/fixtures/valid_brief.md --format brief
python3 scripts/validate_report.py --report tests/fixtures/invalid_report.md  # MUST fail
cd ../.. && claude plugin validate .         # manifest + structure
```

The invalid fixture is the important one: it exists so the quality gate is proved to bite. A change that makes `invalid_report.md` pass has broken the gate, even if every other test is green.
