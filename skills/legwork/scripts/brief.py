#!/usr/bin/env python3
"""
brief.py - write the brief for one retrieval subagent.

    brief.py --angle "SUB-QUESTION" --effort narrow|comparison
             [--searches N-M] [--date YYYY-MM-DD]

Prints the filled brief and nothing else. Pass that output to the subagent
unchanged, as its whole prompt.

The template lives in reference/subagent-brief.md, beside the reason for every
line in it; this script only fills it. It exists because a written instruction
to paste the template verbatim was not enough. Measured on 2026-09-24: an
orchestrator retyped the brief and turned its fetch.py command into "a fetch
tool or WebFetch", so its nine subagents made 103 WebFetch calls and 4 fetch.py
calls, and nearly every source reached the log without its page text - no
figure to trace and no quote to check. Output from a script leaves nothing to
paraphrase: the date, the angle and the real path to the skill's own scripts
are filled in here.

If the template in subagent-brief.md changes shape - a placeholder renamed or
removed - this exits 2 rather than print a brief with a hole in it.

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_FILE = os.path.join(SKILL_DIR, 'reference', 'subagent-brief.md')

DATE = '{YYYY-MM-DD}'
ANGLE = '{the single sub-question this agent is answering, verbatim from Frame}'
RETURN_ANGLE = '{the angle above, unchanged}'
BUDGET = '{n} to {m} searches.'
SKILL = '{SKILL_DIR}'
EFFORT = ('{"This is one narrow fact - stop once you have it, from two\n'
          'independent sources." | "This is a multi-option comparison - spread the effort\n'
          'across the options rather than going deep on the first one."}')

KNOWN = '{what earlier rounds on this angle found}'

PLACEHOLDERS = (DATE, ANGLE, RETURN_ANGLE, BUDGET, SKILL, EFFORT, KNOWN)

FIRST_ROUND = 'Nothing yet - this is the first round on this angle.'
LATER_ROUND = ('Earlier rounds on this angle found these. Look for the ones they missed - other\n'
               'phrasings, registers and directories, smaller and newer players - and do not\n'
               'spend your budget finding these again:\n')

EFFORT_TEXT = {
    'narrow': 'This is one narrow fact - stop once you have it, from two\nindependent sources.',
    'comparison': ('This is a multi-option comparison - spread the effort\n'
                   'across the options rather than going deep on the first one.'),
}
DEFAULT_SEARCHES = {'narrow': (2, 4), 'comparison': (4, 8)}


class TemplateChanged(Exception):
    """The template no longer has a placeholder this script fills."""


def read_template(path=TEMPLATE_FILE):
    """The fenced block under '## The brief' in subagent-brief.md."""
    with open(path, encoding='utf-8') as handle:
        text = handle.read()
    # The template has headings of its own, so the section cannot be cut at the
    # next '## '. Take the first fenced block after the heading instead.
    heading = re.search(r'^## The brief\s*$', text, re.M)
    if not heading:
        raise TemplateChanged('no "## The brief" section in {}'.format(path))
    block = re.search(r'^```[^\n]*\n(.*?)^```\s*$', text[heading.end():], re.M | re.S)
    if not block:
        raise TemplateChanged('no fenced template under "## The brief" in {}'.format(path))
    return block.group(1)


def known_text(known):
    if not known:
        return FIRST_ROUND
    return LATER_ROUND + '\n'.join('- ' + name for name in known)


def fill(template, angle, effort, date, searches, known=()):
    missing = [marker for marker in PLACEHOLDERS if marker not in template]
    if missing:
        raise TemplateChanged(
            'the template in subagent-brief.md no longer has {} - update brief.py to match '
            'rather than hand-writing the brief'.format(', '.join(repr(m) for m in missing)))
    low, high = searches or DEFAULT_SEARCHES[effort]
    out = template.replace(EFFORT, EFFORT_TEXT[effort])
    out = out.replace(BUDGET, '{} to {} searches.'.format(low, high))
    out = out.replace(DATE, date)
    out = out.replace(ANGLE, angle).replace(RETURN_ANGLE, angle)
    out = out.replace(SKILL, SKILL_DIR)
    out = out.replace(KNOWN, known_text(known))
    left = [marker for marker in PLACEHOLDERS if marker in out]
    if left:
        raise TemplateChanged('placeholders left unfilled: {}'.format(left))
    return out


def _date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:
        raise argparse.ArgumentTypeError('expected YYYY-MM-DD, got {!r}'.format(value))


def _searches(value):
    match = re.fullmatch(r'\s*(\d+)\s*-\s*(\d+)\s*', value)
    if not match or int(match.group(1)) > int(match.group(2)):
        raise argparse.ArgumentTypeError('expected N-M, got {!r}'.format(value))
    return int(match.group(1)), int(match.group(2))


def main():
    parser = argparse.ArgumentParser(prog='brief.py', description=__doc__.split('\n')[1].strip())
    parser.add_argument('--angle', required=True,
                        help='The one sub-question this subagent answers, as written in Frame')
    parser.add_argument('--effort', required=True, choices=sorted(EFFORT_TEXT),
                        help='narrow: one fact from one party. comparison: several options')
    parser.add_argument('--searches', type=_searches, default=None,
                        help='Search budget as N-M. Default 2-4 for narrow, 4-8 for comparison')
    parser.add_argument('--date', type=_date, default=None,
                        help='Defaults to today in UTC. Pass the run date so every brief agrees')
    parser.add_argument('--tsv', default=None,
                        help='The run fetch log: the brief lists what earlier rounds on this angle found')
    args = parser.parse_args()

    angle = ' '.join(args.angle.split())
    if not angle:
        parser.error('--angle is empty')
    date = args.date or datetime.now(timezone.utc).strftime('%Y-%m-%d')

    try:
        known = ()
        if args.tsv:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import ledger
            known = sorted(((ledger.load(args.tsv).get(angle) or {}).get('entities') or {}).values())
        text = fill(read_template(), angle, args.effort, date, args.searches, known)
    except (OSError, TemplateChanged) as exc:
        print('brief.py: {}'.format(exc), file=sys.stderr)
        sys.exit(2)
    sys.stdout.write(text)


if __name__ == '__main__':
    main()
