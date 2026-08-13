#!/usr/bin/env python3
"""
Stop hook: refuse to end a turn on a legwork report that fails its own gate.

Legwork's gate is the one part of the skill that cannot be talked out of a
verdict, and until now it fired only when the agent remembered to run it - at
the end of a long run, which is when there is least attention left for
procedure. Reports on disk show the predictable result: documents asserting
their level while failing the gate, and one flagship deep run with no fetch log
at all.

An instruction that has to be remembered scales badly with the length of the
thing doing the remembering. A hook does not.

Wire it into settings.json (install.sh --with-hook does this for you):

    {"hooks": {"Stop": [{"hooks": [
      {"type": "command", "command": "python3 ~/.claude/hooks/legwork-gate.py"}
    ]}]}}

Reads the hook payload on stdin, writes a JSON decision on stdout. Exits 0
always: a hook that crashes the session is worse than a gate that missed one
report, so every failure path here degrades to silence.

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

# How recently a report must have changed to be considered this session's work.
# Generous, because a deep run legitimately takes 20-40 minutes, and the cost of
# being wrong is one extra gate run rather than a missed one.
RECENT_SECONDS = 6 * 60 * 60

# A file only looks like a legwork run if it carries one of these. Without this
# the hook would gate every markdown file under the output base, including notes
# and supporting documents that were never meant to be reports.
MARKERS = ('## Findings', '## Could not answer', '### Finding 1')


def skill_dir():
    """Where the skill lives, so the hook works from a symlinked install."""
    override = os.environ.get('LEGWORK_SKILL_DIR')
    if override and os.path.isdir(override):
        return override
    return os.path.expanduser('~/.claude/skills/legwork')


def output_bases(cwd):
    """Every plausible place a run could have been written."""
    bases = []
    override = os.environ.get('LEGWORK_OUTPUT')
    if override:
        bases.append(override)
    try:
        root = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=cwd,
                              capture_output=True, text=True, timeout=5)
        if root.returncode == 0 and root.stdout.strip():
            bases.append(os.path.join(root.stdout.strip(), 'docs', 'research'))
    except (OSError, subprocess.SubprocessError):
        pass
    bases.append(os.path.join(cwd, 'docs', 'research'))
    return [b for b in dict.fromkeys(bases) if os.path.isdir(b)]


def recent_reports(base, now):
    """Reports under this base touched recently enough to be this run's work."""
    found = []
    for folder in sorted(os.listdir(base)):
        run_dir = os.path.join(base, folder)
        if not os.path.isdir(run_dir):
            continue
        for name in sorted(os.listdir(run_dir)):
            if not name.endswith('.md'):
                continue
            path = os.path.join(run_dir, name)
            try:
                if now - os.path.getmtime(path) > RECENT_SECONDS:
                    continue
                with open(path, encoding='utf-8') as handle:
                    head = handle.read(20000)
            except OSError:
                continue
            if any(marker in head for marker in MARKERS):
                found.append((path, infer_format(head)))
    return found


def infer_format(head):
    """A report carries an Executive Summary; a brief does not.

    Gating a brief as a report would fail it for missing sections a brief is
    never supposed to have, which would make the hook fire on every quick run
    and teach the agent to ignore it.
    """
    return 'report' if '## Executive Summary' in head else 'brief'


def gate(path, fmt):
    """(passed, errors). A gate that cannot run never blocks."""
    checker = os.path.join(skill_dir(), 'scripts', 'check.py')
    if not os.path.exists(checker):
        return True, []
    level = os.environ.get('LEGWORK_DEFAULT_MODE', 'standard')
    if level not in ('quick', 'standard', 'deep'):
        level = 'standard'
    try:
        result = subprocess.run(
            [sys.executable, checker, '--report', path,
             '--format', fmt, '--level', level, '--json'],
            capture_output=True, text=True, timeout=60)
        payload = json.loads(result.stdout or '{}')
    except (OSError, subprocess.SubprocessError, ValueError):
        return True, []
    return bool(payload.get('passed', True)), payload.get('errors', [])


def main():
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        sys.exit(0)

    # Already blocked once this turn. Blocking again would loop the agent
    # against a gate it may not be able to satisfy.
    if event.get('stop_hook_active'):
        sys.exit(0)

    cwd = event.get('cwd') or os.getcwd()
    now = time.time()

    failures = []
    for base in output_bases(cwd):
        for report, fmt in recent_reports(base, now):
            passed, errors = gate(report, fmt)
            if not passed:
                failures.append((report, errors))

    if not failures:
        sys.exit(0)

    lines = ['A legwork report written in this session does not pass its own gate.', '']
    for report, errors in failures:
        lines.append('{}:'.format(os.path.relpath(report, cwd)))
        for message in errors[:8]:
            lines.append('  - {}'.format(message))
        if len(errors) > 8:
            lines.append('  - ... and {} more'.format(len(errors) - 8))
        lines.append('')
    lines.append('Fix these and re-run:')
    lines.append('  python3 {}/scripts/finish.py --report <path> --level <level>'.format(skill_dir()))
    lines.append('')
    lines.append('After two failed cycles, stop and report what is still failing '
                 'rather than continuing to patch.')

    print(json.dumps({'decision': 'block', 'reason': '\n'.join(lines)}))
    sys.exit(0)


if __name__ == '__main__':
    main()
