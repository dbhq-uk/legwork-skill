#!/usr/bin/env python3
"""
Close out a run: gate it, sweep it for stale evidence, and file it.

    finish.py --report PATH --level deep --topic "..." --one-liner "..."

The gate, the staleness sweep and the index entry are three separate commands
that all have to be remembered at the end of a long run, which is exactly when
a model has the least attention left for procedure. Runs on disk show the
predictable result: reports that assert their level while failing the gate, and
runs that never reach the index at all.

This is one call with one verdict. A run that fails the gate is not filed -
filing it would record a conclusion the evidence does not support, and the index
is what future sessions trust instead of re-searching.

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, __file__.rsplit('/', 1)[0])

import check  # noqa: E402
import index as index_module  # noqa: E402
from sources import CLAIM_KINDS, freshness_audit, read_rows  # noqa: E402


def infer_format(content):
    """A report carries an Executive Summary; a brief does not."""
    return 'report' if '## Executive Summary' in content else 'brief'


def default_tsv(report_path):
    candidate = os.path.splitext(report_path)[0] + '.tsv'
    return candidate if os.path.exists(candidate) else None


def default_base(report_path):
    """The output base is the folder holding the run folder."""
    return os.path.dirname(os.path.dirname(os.path.abspath(report_path)))


def staleness_sweep(rows, claim_kinds, now=None):
    """Per claim kind, what would be past its horizon if the run made that claim.

    Reported conditionally on purpose. The log does not record which claim a
    source was used for, so asserting a run is stale would be a guess; naming
    the kinds whose evidence has aged is not.
    """
    flagged = []
    for claim_kind in claim_kinds:
        audit = freshness_audit(rows, claim_kind, now=now)
        if audit['stale']:
            flagged.append({
                'claim_kind': claim_kind,
                'horizon_days': audit['horizon_days'],
                'stale': audit['stale'],
                'undated': audit['undated'],
            })
    return flagged


def main():
    parser = argparse.ArgumentParser(prog='finish', description=__doc__.split('\n')[1])
    parser.add_argument('--report', required=True)
    parser.add_argument('--level', default='standard', choices=list(check.LEVELS))
    parser.add_argument('--format', default='auto', choices=['auto'] + list(check.FORMATS))
    parser.add_argument('--tsv', default=None)
    parser.add_argument('--base', default=None, help='Output base holding index.md; inferred from the report path')
    parser.add_argument('--topic', default=None)
    parser.add_argument('--one-liner', default=None, dest='one_liner')
    parser.add_argument('--claim-kind', action='append', dest='claim_kinds',
                        choices=list(CLAIM_KINDS),
                        help='Repeatable. Defaults to every claim kind, reported conditionally.')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(args.report):
        print('error: report not found: {}'.format(args.report), file=sys.stderr)
        sys.exit(2)

    with open(args.report, encoding='utf-8') as handle:
        content = handle.read()

    fmt = infer_format(content) if args.format == 'auto' else args.format
    tsv = args.tsv or default_tsv(args.report)
    base = args.base or default_base(args.report)
    rows = read_rows(tsv) if tsv else []

    problems, summary = check.run(args.report, tsv, fmt, args.level)
    passed = not problems.errors

    stale = staleness_sweep(rows, args.claim_kinds or list(CLAIM_KINDS))

    filed = None
    if passed and args.topic:
        folder = os.path.basename(os.path.dirname(os.path.abspath(args.report)))
        entries = index_module.read_index(base)
        existed = any(e.get('folder') == folder for e in entries)
        index_module.write_index(base, index_module.upsert(entries, {
            'topic': args.topic,
            'folder': folder,
            'level': args.level,
            'verified': index_module.datetime.now(index_module.timezone.utc).date().isoformat(),
            'one_liner': args.one_liner or '',
        }))
        filed = {'status': 'refreshed' if existed else 'added', 'folder': folder}

    if args.json:
        print(json.dumps({'passed': passed, 'format': fmt, 'errors': problems.errors,
                          'warnings': problems.warnings, 'stale': stale, 'filed': filed,
                          **summary}, indent=2))
        sys.exit(0 if passed else 1)

    print('finishing {} ({} format, {} level)'.format(
        os.path.basename(args.report), fmt, args.level))
    if tsv:
        print('fetch log: {} ({} rows)'.format(os.path.basename(tsv), len(rows)))
    print()

    for message in problems.errors:
        print('  ERROR    {}'.format(message))
    for message in problems.warnings:
        print('  warning  {}'.format(message))
    if passed and not problems.warnings:
        print('  gate: all checks passed')
    print()

    if stale:
        print('  evidence that has aged, if this run makes these claims:')
        for entry in stale:
            print('    {:<11} {} of {} sources past a {}-day horizon'.format(
                entry['claim_kind'], entry['stale'], len(rows), entry['horizon_days']))
        print()

    if filed:
        print('  index: {} {}'.format(filed['status'], filed['folder']))
    elif not passed:
        print('  index: not filed - a run that fails its gate is not a run to trust later')
    elif not args.topic:
        print('  index: not filed - pass --topic and --one-liner to file it')
    print()
    print('PASS' if passed else 'FAIL')
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
