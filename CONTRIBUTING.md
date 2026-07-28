# Contributing

Thanks for your interest - contributions are welcome.

## Ways to help

- Report a bug or request a feature via [issues](https://github.com/dbhq-uk/legwork-skill/issues)
- Improve the skill instructions, scripts or reference docs via a pull request

## Local development

```bash
git clone https://github.com/dbhq-uk/legwork-skill.git
cd legwork-skill
./install.sh          # symlinks into ~/.claude/skills (edits are live)
```

The whole skill directory is symlinked, so edits - including to `SKILL.md` - are live immediately. For Codex, re-run `./install-codex.sh` after editing a `SKILL.md`, since that path is rewritten at install time.

## Before opening a PR

- `python3 -m pytest skills/legwork/tests/ -v` - all tests pass, no network needed
- `claude plugin validate .` - the plugin validates
- **No third-party imports.** The scripts are standard library only and CI enforces it; that constraint is what keeps the install story simple across Claude, Codex and plugin installs
- Bright Data stays optional - nothing may assume the CLI is present
- British English, plain hyphens, no trailing full stops on headings

## Licence

By contributing you agree your work is licensed under the [MIT licence](LICENSE).
