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
import re
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


def _git(args, cwd, timeout=5):
    """Run git, returning stdout, or None if git could not answer."""
    try:
        result = subprocess.run(['git'] + args, cwd=cwd, capture_output=True,
                                text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def is_session_work(path, now):
    """Was this run written in this session, rather than merely checked out?

    mtime cannot answer this inside a repository, and it fails in the common
    direction: `git worktree add`, `git clone` and `git checkout` all stamp
    every file they write with the current time. In a worktree created an hour
    ago, every report ever committed looks an hour old.

    Measured 2026-08-18 - a worktree made at 13:48 gave all six of a repo's
    research reports an mtime of 13:48, and a run from 11 July 2026 blocked the
    end of a turn that had nothing to do with it. The agent then spent that turn
    retrofitting confidence bands onto month-old research instead of the work it
    had been asked for, which is the real cost: a hook that cries wolf does not
    just get ignored, it actively misdirects.

    So git is asked instead, and it is asked two things, because neither alone
    is enough:

    - **Uncommitted?** Untracked or modified means someone is working on it now,
      whatever its age. This is what keeps a brand new run blocking, and without
      it "ignore what git already knows about" would quietly become "ignore
      everything".
    - **Created recently?** The *oldest* commit touching the file, not the
      newest. A run created this session and committed is still this session's
      work; an old report given a formatting fix today is not a new run, and
      holding the turn hostage to it is the loop this function exists to break.

    Outside a repository there is nothing to ask, so mtime stands.
    """
    folder = os.path.dirname(path)
    if _git(['rev-parse', '--show-toplevel'], folder) is None:
        return True  # not a repo; the mtime pre-filter already vouched for it

    status = _git(['status', '--porcelain', '--', os.path.basename(path)], folder)
    if status is None:
        return True  # git present but unhappy; fall back to blocking rather than missing
    if status.strip():
        return True

    log = _git(['log', '--format=%ct', '--', os.path.basename(path)], folder)
    if log is None or not log.strip():
        return True  # tracked-clean with no history should not happen; do not silently skip
    try:
        created = int(log.strip().splitlines()[-1])
    except ValueError:
        return True
    return now - created <= RECENT_SECONDS


def recent_reports(base, now):
    """Reports under this base written recently enough to be this run's work."""
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
                # A stale mtime is trustworthy in a way a fresh one is not:
                # any edit bumps it, so old means untouched. Kept as the cheap
                # negative filter, so only report-shaped candidates reach git.
                if now - os.path.getmtime(path) > RECENT_SECONDS:
                    continue
                with open(path, encoding='utf-8') as handle:
                    head = handle.read(20000)
            except OSError:
                continue
            if not any(marker in head for marker in MARKERS):
                continue
            if not is_session_work(path, now):
                continue
            found.append((path, infer_format(head), infer_level(head)))
    return found


# The receipt line opens with the level the run claims: *deep - 6 angles, ...*
_RECEIPT_LEVEL = re.compile(r'^\*\s*(quick|standard|deep)\b', re.M | re.I)


def infer_level(head):
    """Gate a run at the level it claims for itself.

    Reading the level from an environment default meant the hook checked
    everything at standard, where the whole evidence and independence layer is
    warnings - so it enforced structure and let unevidenced work through.
    Measured 2026-08-13: a report whose matrix had five uncited rows was not
    blocked. A run that announces deep in its receipt is now held to deep.
    """
    match = _RECEIPT_LEVEL.search(head)
    if match:
        return match.group(1).lower()
    level = os.environ.get('LEGWORK_DEFAULT_MODE', 'standard')
    return level if level in ('quick', 'standard', 'deep') else 'standard'


def infer_format(head):
    """A report carries an Executive Summary; a brief does not.

    Gating a brief as a report would fail it for missing sections a brief is
    never supposed to have, which would make the hook fire on every quick run
    and teach the agent to ignore it.
    """
    return 'report' if '## Executive Summary' in head else 'brief'


def gate(path, fmt, level):
    """(passed, errors). A gate that cannot run never blocks."""
    checker = os.path.join(skill_dir(), 'scripts', 'check.py')
    if not os.path.exists(checker):
        return True, []
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
        for report, fmt, level in recent_reports(base, now):
            passed, errors = gate(report, fmt, level)
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
