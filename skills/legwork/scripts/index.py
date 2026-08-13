#!/usr/bin/env python3
"""
index.py - the research index, so the next run can find the last one.

A report that never reaches the index is a report the next session cannot find,
and the next session re-runs it. Legwork writes one folder per run, date-stamped,
which sorts nicely and tells you nothing: after six months the output base is a
list of folder names nobody can match against a question without opening them.

The index is a dispatcher. One row per run, and the one-liner column is the whole
signal available before paying to open the report - so it says what the run
concluded, not what it was about:

    weak    Notes on the plugin gallery
    strong  No submission route exists; install is by URL or not at all

Identity is the FOLDER, not the topic. Topics get reworded between runs; the
folder is stamped once and never moves. Upserting on the folder is what makes a
refresh update its row in place instead of leaving two rows competing to describe
the same report.

CLI:
    index.py add  --base DIR --folder NAME --topic "..." --one-liner "..." \\
                  [--level standard] [--verified YYYY-MM-DD]
    index.py list --base DIR [--stale-days 90] [--format table|json]

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sources import parse_date  # noqa: E402

INDEX_FILENAME = 'index.md'

COLUMNS = ('topic', 'folder', 'level', 'verified', 'one_liner')
HEADINGS = ('Topic', 'Folder', 'Level', 'Last verified', 'One-liner')

HEADER = '# Research index\n\n'

# A run older than this on a moving topic should be refreshed rather than quoted.
DEFAULT_STALE_DAYS = 90


def _clean(value):
    """Single-line and pipe-free, so no field can break the table it sits in."""
    return re.sub(r'\s+', ' ', str(value or '')).replace('|', '/').strip()


# ---------------------------------------------------------------------------
# Parse and render
# ---------------------------------------------------------------------------


def parse_index(text):
    """Rows of the index table. Returns [] for an absent or empty index.

    The header is the FIRST table row, identified by position. Identifying it by
    content - "the row whose first cell says Topic" - silently drops a real run
    whose topic happens to be worded like the column heading.
    """
    rows = []
    for line in (text or '').splitlines():
        stripped = line.strip()
        if not stripped.startswith('|'):
            continue
        cells = [cell.strip() for cell in stripped.strip('|').split('|')]
        if all(set(cell) <= {'-', ':'} and cell for cell in cells):
            continue
        if len(cells) >= len(COLUMNS):
            rows.append(cells)
    return [dict(zip(COLUMNS, cells[:len(COLUMNS)])) for cells in rows[1:]]


def render_index(entries):
    lines = [HEADER.rstrip('\n'), '',
             '| ' + ' | '.join(HEADINGS) + ' |',
             '|' + '---|' * len(HEADINGS)]
    for entry in entries:
        lines.append('| ' + ' | '.join(_clean(entry.get(column, '')) for column in COLUMNS) + ' |')
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def upsert(entries, entry):
    """Add or refresh one row, keyed on the folder and keeping its position."""
    cleaned = {column: _clean(entry.get(column, '')) for column in COLUMNS}
    updated = list(entries)
    for position, existing in enumerate(updated):
        if existing.get('folder') == cleaned['folder']:
            updated[position] = cleaned
            return updated
    updated.append(cleaned)
    return updated


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def stale_entries(entries, days=DEFAULT_STALE_DAYS, now=None):
    """Entries last verified longer ago than the horizon.

    An unreadable date counts as stale. Unknown age is not the same as fresh, and
    defaulting to fresh is how a three-year-old entry gets quoted as current
    truth.
    """
    reference = now or datetime.now(timezone.utc)
    stale = []
    for entry in entries:
        parsed, _ = parse_date(entry.get('verified'))
        if parsed is None or (reference - parsed).total_seconds() / 86400.0 > days:
            stale.append(entry)
    return stale


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------


def index_path(base):
    return os.path.join(base, INDEX_FILENAME)


def read_index(base):
    path = index_path(base)
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as handle:
        return parse_index(handle.read())


def write_index(base, entries):
    os.makedirs(base, exist_ok=True)
    with open(index_path(base), 'w', encoding='utf-8') as handle:
        handle.write(render_index(entries))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_add(args):
    entry = {
        'topic': args.topic,
        'folder': args.folder,
        'level': args.level,
        'verified': args.verified or datetime.now(timezone.utc).date().isoformat(),
        'one_liner': args.one_liner,
    }
    entries = read_index(args.base)
    existed = any(e.get('folder') == _clean(args.folder) for e in entries)
    write_index(args.base, upsert(entries, entry))
    print(json.dumps({'status': 'refreshed' if existed else 'added',
                      'folder': entry['folder'], 'index': index_path(args.base)}))


def cmd_list(args):
    entries = read_index(args.base)
    stale = {id(entry) for entry in stale_entries(entries, days=args.stale_days)}
    if args.format == 'json':
        print(json.dumps([dict(entry, stale=id(entry) in stale) for entry in entries], indent=2))
        return
    if not entries:
        print('no index at {} yet'.format(index_path(args.base)))
        return
    print('{} run(s) indexed at {}'.format(len(entries), index_path(args.base)))
    for entry in entries:
        print('\n  {}{}'.format(entry.get('topic', ''), '   [STALE]' if id(entry) in stale else ''))
        print('    {}  ({}, last verified {})'.format(
            entry.get('folder', ''), entry.get('level', ''), entry.get('verified', '')))
        print('    {}'.format(entry.get('one_liner', '')))


def main():
    parser = argparse.ArgumentParser(prog='index', description=__doc__.split('\n')[1])
    sub = parser.add_subparsers(dest='command', required=True)

    p_add = sub.add_parser('add', help='Add or refresh one run in the index')
    p_add.add_argument('--base', required=True, help='The output base holding the run folders')
    p_add.add_argument('--folder', required=True)
    p_add.add_argument('--topic', required=True)
    p_add.add_argument('--one-liner', required=True,
                       help='What the run CONCLUDED, not what it was about')
    p_add.add_argument('--level', default='standard')
    p_add.add_argument('--verified', default='', help='ISO date; defaults to today')

    p_list = sub.add_parser('list', help='Show the index, flagging stale runs')
    p_list.add_argument('--base', required=True)
    p_list.add_argument('--stale-days', type=int, default=DEFAULT_STALE_DAYS)
    p_list.add_argument('--format', default='table', choices=['table', 'json'])

    args = parser.parse_args()
    {'add': cmd_add, 'list': cmd_list}[args.command](args)


if __name__ == '__main__':
    main()
