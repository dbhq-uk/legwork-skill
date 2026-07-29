# Developer setup - Legwork

Set the skill up from source with a **live symlink install**, so your edits are active immediately in Claude Code (and Codex). End users don't need this - they install via the [DBHQ marketplace](../README.md#install).

## Prerequisites

- `git` (and the GitHub CLI `gh` if you'll push changes)
- `python3` 3.9 or newer - and nothing else. The skill is standard library only, so there is no virtualenv to create and no packages to install
- Optionally the [Bright Data CLI](https://github.com/brightdata/cli) if you want to exercise the fallback provider

## 1. Clone

```bash
git clone https://github.com/dbhq-uk/legwork-skill.git ~/dbhq-legwork
cd ~/dbhq-legwork
```

## 2. Install (symlink)

```bash
./install.sh          # Claude Code: symlinks into ~/.claude/skills (edits are live)
./install-codex.sh    # Codex: installs into ~/.codex/skills
```

The committed skill references its scripts via `${CLAUDE_SKILL_DIR}` (the skill's own directory), which Claude Code substitutes for personal, project and plugin installs alike. So `install.sh` symlinks the **whole skill directory** into `~/.claude/skills/` - `SKILL.md`, `scripts/`, `reference/` and `templates/` are all live, and every edit takes effect with no re-run. Codex does not substitute `${CLAUDE_SKILL_DIR}`, so `install-codex.sh` rewrites it to the install path - **re-run `./install-codex.sh` after editing a `SKILL.md`** for Codex.

## 3. Verify

```bash
cd skills/legwork
python3 -m pytest tests/ -v

# The gate must reject bad reports, not just accept good ones:
python3 scripts/check.py --report tests/fixtures/valid_brief.md --format brief --level deep
python3 scripts/check.py --report tests/fixtures/invalid_report.md --level deep      # expected to FAIL
python3 scripts/check.py --report tests/fixtures/one_origin.md --level deep          # expected to FAIL
```

The last one is the interesting failure: five genuinely distinct publishers back the
finding, but every one of them was surfaced by the same search angle, so corroboration
scores 1 rather than 5.

Then, in Claude Code, try *"legwork: compare managed Postgres options for a UK fintech"*.

## 4. Optional - the fallback provider

```bash
npm install -g @brightdata/cli
brightdata login
skills/legwork/setup.sh --reset
```

Everything works without this. You lose only fallback scraping of bot-blocked pages, Reddit threads and geo-specific SERP - and every Bright Data call costs money, so the skill is written to avoid it wherever a built-in would do.

## Where output goes

Runs write to `$LEGWORK_OUTPUT`, else `<git-root>/docs/research/`, else `$PWD/docs/research/`. That means a run started inside this repo lands in `docs/research/` - which is gitignored, so your own research output never ends up in a commit.
