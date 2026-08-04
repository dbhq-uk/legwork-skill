#!/usr/bin/env python3
"""
matrix.py - completeness checking for a comparison matrix.

"Compare X, Y and Z" is a grid question, and rendering it as prose findings loses
the grid. But a grid is also where a comparison quietly goes wrong: the shape says
"complete" while half the cells are blank, and a reader takes an empty cell to
mean "no" rather than "we never found out".

So the rule is that every cell says something. Either it carries a claim, or it
carries `[unknown]`, which is a result: it records that the question was asked of
that entity and came back empty. A blank cell records nothing and reads as
settled.

The other rule is that a row with any established content cites something. A row
of confident-looking values with no citation anywhere is the matrix version of a
finding resting on nothing, and the report gate would never see it because table
cells are not sentences.

A row that is entirely `[unknown]` needs no citation, and still belongs in the
table: it is how the report says "we looked at this one and found nothing", which
is exactly the entity a reader would otherwise assume was overlooked.

CLI:
    matrix.py check --report PATH [--format text|json]

Stdlib only, no network. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

MATRIX_HEADING_RE = re.compile(r'^##\s+Comparison matrix\s*$', re.M | re.I)

UNKNOWN_MARKERS = ('[unknown]', '[not established]')


def _is_separator(cells):
    return all(set(cell) <= {'-', ':'} and cell for cell in cells)


def parse_matrix(content):
    """The first markdown table under '## Comparison matrix'.

    Returns {'entity_label', 'fields', 'rows': [{'entity', 'cells', 'width'}]} or
    None when the report has no matrix section at all.
    """
    heading = MATRIX_HEADING_RE.search(content or '')
    if not heading:
        return None
    section = content[heading.end():]
    next_heading = re.search(r'^##\s+', section, re.M)
    if next_heading:
        section = section[:next_heading.start()]

    table = [line.strip() for line in section.splitlines() if line.strip().startswith('|')]
    if not table:
        return None

    header = [cell.strip() for cell in table[0].strip('|').split('|')]
    rows = []
    for line in table[1:]:
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if _is_separator(cells):
            continue
        if not cells or not cells[0]:
            continue
        rows.append({
            'entity': cells[0],
            'width': len(cells),
            'cells': {field: (cells[i + 1] if i + 1 < len(cells) else '')
                      for i, field in enumerate(header[1:])},
        })
    return {'entity_label': header[0] if header else '', 'fields': header[1:], 'rows': rows}


def check_matrix(parsed):
    """Completeness of a parsed matrix. Returns problems plus coverage."""
    result = {'entities': 0, 'fields': 0, 'cells': 0, 'unknown_cells': 0,
              'coverage': 0.0, 'problems': []}
    if not parsed:
        return result

    fields = parsed['fields']
    expected_width = len(fields) + 1
    problems = []
    cells = unknown = 0

    for row in parsed['rows']:
        if row['width'] != expected_width:
            problems.append(
                '{}: row has {} columns, the table has {}'.format(
                    row['entity'], row['width'], expected_width))

        established = 0
        for field in fields:
            value = (row['cells'].get(field) or '').strip()
            cells += 1
            if not value:
                problems.append(
                    '{}: the {!r} cell is blank - a cell nobody filled reads as settled; '
                    'write [unknown] if it could not be established'.format(row['entity'], field))
            elif value.lower() in UNKNOWN_MARKERS:
                unknown += 1
            else:
                established += 1

        if established and not re.search(r'\[\d+\]', ' '.join(row['cells'].values())):
            problems.append(
                '{}: the row states values but carries no citation anywhere'.format(row['entity']))

    result.update({
        'entities': len(parsed['rows']),
        'fields': len(fields),
        'cells': cells,
        'unknown_cells': unknown,
        'coverage': round((cells - unknown) / cells, 4) if cells else 0.0,
        'problems': problems,
    })
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_check(args):
    with open(args.report, encoding='utf-8') as handle:
        parsed = parse_matrix(handle.read())

    if parsed is None:
        message = 'no "## Comparison matrix" section in {}'.format(os.path.basename(args.report))
        print(json.dumps({'matrix': False, 'message': message}) if args.format == 'json' else message)
        return

    result = check_matrix(parsed)
    if args.format == 'json':
        print(json.dumps(dict(result, matrix=True), indent=2))
    else:
        print('{} entities x {} fields = {} cells, {} unknown ({:.0%} established)'.format(
            result['entities'], result['fields'], result['cells'],
            result['unknown_cells'], result['coverage']))
        for problem in result['problems']:
            print('  ERROR  {}'.format(problem))
        if not result['problems']:
            print('  the matrix is complete')
    sys.exit(0 if not result['problems'] else 1)


def main():
    parser = argparse.ArgumentParser(prog='matrix', description=__doc__.split('\n')[1])
    sub = parser.add_subparsers(dest='command', required=True)
    p_check = sub.add_parser('check', help="Check a report's comparison matrix for completeness")
    p_check.add_argument('--report', required=True)
    p_check.add_argument('--format', default='text', choices=['text', 'json'])
    args = parser.parse_args()
    {'check': cmd_check}[args.command](args)


if __name__ == '__main__':
    main()
