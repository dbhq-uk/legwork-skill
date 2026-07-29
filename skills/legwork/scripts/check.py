#!/usr/bin/env python3
"""
check.py - the shippability gate. One question, three layers of answer.

Replaces three scripts that each answered part of "is this report fit to send".

  Structural (every level)
      Sections, placeholders, truncation markers, bibliography completeness,
      inline citations, internal links.

  Evidence (standard and deep)
      Every cited URL was actually fetched. Every figure quoted next to a
      citation actually appeared on a page that was fetched. Every finding
      states its confidence.

  Independence (standard and deep)
      A finding claiming strong support has corroboration from genuinely
      independent sources reached by different angles.

The anti-fabrication check is the important one and it needs no heuristics: a
citation to a URL that never appears in the run's fetch log is fabricated. Its
predecessor tried to catch invented citations by pattern-matching titles that
sounded like fake academic papers, which never once fired on real research and
could only ever produce false positives on a legitimately titled vendor page.

Problems are warnings at standard and errors at deep, except structural ones,
which are always errors. Exit status is 0 when there are no errors.

CLI:
    check.py --report PATH [--tsv PATH] [--format report|brief] [--level quick|standard|deep]

Stdlib only, no network. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from independence import canonicalize, corroboration  # noqa: E402
from sources import read_rows  # noqa: E402

LEVELS = ('quick', 'standard', 'deep')
FORMATS = ('report', 'brief')

REQUIRED_SECTIONS = {
    'report': ('Executive Summary', 'Introduction', 'Findings', 'Synthesis',
               'Limitations', 'Recommendations', 'Bibliography'),
    'brief': ('Findings', 'Limitations', 'Bibliography'),
}

# The honest-empty outcome is a different document shape, not a failed report.
COULD_NOT_ANSWER_RE = re.compile(r'^##\s+Could not answer\b', re.M | re.I)
CLOSEST_RE = re.compile(r'^\s*\*{0,2}Closest\b', re.M | re.I)

RECEIPT_RE = re.compile(r'^\s*\*(quick|standard|deep)\b[^*]*\*\s*$', re.M | re.I)
FINDING_RE = re.compile(r'^#{2,3}\s+Finding\s+(\d+)\s*[:.]\s*(.+)$', re.M)
# House style is a plain hyphen, but the separator class accepts an en dash too:
# parsing should be forgiving of a report someone wrote by hand. Do not "tidy"
# this to a bare hyphen - it would silently stop recognising those findings.
CONFIDENCE_RE = re.compile(r'^\*\*Confidence:\s*(Strong|Moderate|Weak)\*\*\s*[-–]\s*(\S.*)$', re.M | re.I)

PLACEHOLDERS = ('TBD', 'TODO', 'FIXME', '[citation needed]', '[needs citation]', '[placeholder]')

TRUNCATION_PATTERNS = (
    (r'\[\d+\s*-\s*\d+\]', 'a citation range such as [8-75] instead of individual entries'),
    (r'Additional\s+citations', '"Additional citations"'),
    (r'would be included', '"would be included"'),
    (r'\[\s*\.\.\.\s*continue', '"[...continue"'),
    (r'\[Continue with', '"[Continue with"'),
    (r'Content continues', '"Content continues"'),
    (r'Due to length', '"Due to length"'),
    (r'\[Sections?\s+\d+\s*-\s*\d+', '"[Sections X-Y"'),
    (r'Additional sections', '"Additional sections"'),
)

# Figures below this are almost always prose counts ("three of the five"), not
# claims worth tracing. Decimals and percentages are always traced.
MIN_TRACED_NUMBER = 10

CONFIDENCE_CORROBORATION = {'strong': 2, 'moderate': 1, 'weak': 0}


class Problems:
    def __init__(self, level):
        self.level = level
        self.errors = []
        self.warnings = []

    def structural(self, message):
        self.errors.append(message)

    def graded(self, message):
        """An error at deep, a warning at standard, ignored at quick."""
        if self.level == 'deep':
            self.errors.append(message)
        elif self.level == 'standard':
            self.warnings.append(message)

    def warn(self, message):
        self.warnings.append(message)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def split_bibliography(content):
    """(body, bibliography). Citation checks must never count the bibliography's
    own [N] markers, or a report with no inline citations passes on the strength
    of having a bibliography."""
    parts = re.split(r'^##\s*Bibliography\s*$', content, maxsplit=1, flags=re.M | re.I)
    return (parts[0], parts[1]) if len(parts) == 2 else (content, '')


def parse_bibliography(bibliography):
    """{number: {'raw': str, 'url': str}} from '[N] ... https://...' lines."""
    entries = {}
    current = None
    for line in bibliography.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r'^\[(\d+)\]\s+(.*)$', stripped)
        if match:
            current = int(match.group(1))
            entries[current] = {'raw': match.group(2), 'url': ''}
        elif current is not None:
            entries[current]['raw'] += ' ' + stripped
    for entry in entries.values():
        url = re.search(r'https?://[^\s)\]>]+', entry['raw'])
        entry['url'] = url.group(0).rstrip('.,;') if url else ''
    return entries


def finding_sections(content):
    """[{'number', 'title', 'text'}] for each '## Finding N: ...' section."""
    matches = list(FINDING_RE.finditer(content))
    sections = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        next_heading = re.search(r'^#{1,3}\s+(?!Finding\b)', content[start:end], re.M)
        if next_heading:
            end = start + next_heading.start()
        sections.append({'number': int(match.group(1)), 'title': match.group(2).strip(),
                         'text': content[start:end]})
    return sections


def citations_in(text):
    return {int(n) for n in re.findall(r'\[(\d+)\]', text)}


_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')
_NUMBER_TOKEN = re.compile(r'(?<![\w.[])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.[])\d+(?:\.\d+)?')


def traced_figures(text):
    """Figures stated in a sentence that also carries a citation.

    Bracketed citation markers are excluded, and bare integers below
    MIN_TRACED_NUMBER are skipped as prose counts. Percentages and decimals are
    always traced however small, because those are the figures that get
    transposed.
    """
    figures = set()
    for sentence in _SENTENCE_SPLIT.split(text):
        if '[' not in sentence or not re.search(r'\[\d+\]', sentence):
            continue
        stripped = re.sub(r'\[\d+\]', ' ', sentence)
        for raw in _NUMBER_TOKEN.findall(stripped):
            token = raw.replace(',', '')
            try:
                value = float(token)
            except ValueError:
                continue
            is_decimal = value != int(value)
            followed_by_percent = re.search(re.escape(raw) + r'\s*%', stripped) is not None
            if not is_decimal and not followed_by_percent and value < MIN_TRACED_NUMBER:
                continue
            figures.add(str(int(value)) if value == int(value) else repr(value))
    return figures


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


def check_structure(content, fmt, problems, report_path):
    body, bibliography = split_bibliography(content)

    for section in REQUIRED_SECTIONS[fmt]:
        if not re.search(r'^##\s+.*' + re.escape(section), content, re.M | re.I):
            problems.structural('missing section: {}'.format(section))

    found = [p for p in PLACEHOLDERS if p.lower() in content.lower()]
    if found:
        problems.structural('placeholder text present: {}'.format(', '.join(found)))

    for pattern, description in TRUNCATION_PATTERNS:
        if re.search(pattern, content, re.I):
            problems.structural(
                'truncation marker present ({}) - the report looks finished but is not'.format(description))

    if not re.search(r'\[\d+\]', body):
        problems.structural('no inline [N] citations in the body; a bibliography alone is not an evidence trail')

    if not bibliography.strip():
        problems.structural('no Bibliography section')
        return {}

    entries = parse_bibliography(bibliography)
    if not entries:
        problems.structural('Bibliography section has no [N] entries')
        return {}

    numbers = sorted(entries)
    gaps = [n for n in range(1, numbers[-1] + 1) if n not in entries]
    if gaps:
        problems.structural('Bibliography numbering has gaps: {}'.format(gaps))

    cited = citations_in(body)
    dangling = sorted(cited - set(entries))
    if dangling:
        problems.structural('cited in the body but absent from the bibliography: {}'.format(dangling))
    orphaned = sorted(set(entries) - cited)
    if orphaned:
        problems.warn('in the bibliography but never cited: {}'.format(orphaned))

    missing_url = sorted(n for n, entry in entries.items() if not entry['url'])
    if missing_url:
        problems.graded('bibliography entries with no URL: {}'.format(missing_url))

    for link in re.findall(r'\[[^\]]*\]\((\.{1,2}/[^)]+)\)', content):
        target = os.path.join(os.path.dirname(os.path.abspath(report_path)), link.split('#')[0])
        if not os.path.exists(target):
            problems.structural('broken internal link: {}'.format(link))

    return entries


def check_evidence(content, entries, rows, problems):
    """Fetched-URL and figure tracing. Requires a fetch log."""
    by_url = {}
    quotes_by_url = {}
    for row in rows:
        if (row.get('status') or 'ok').lower() == 'ok':
            key = canonicalize(row.get('url', ''))
            by_url.setdefault(key, []).extend(row.get('numbers') or [])
            if (row.get('quote') or '').strip():
                quotes_by_url[key] = row['quote'].strip()

    unfetched = sorted(
        number for number, entry in entries.items()
        if entry['url'] and canonicalize(entry['url']) not in by_url
    )
    if unfetched:
        problems.graded(
            'cited but never fetched in this run - a citation to a page nobody opened: {}'.format(unfetched))

    for finding in finding_sections(content):
        cited = citations_in(finding['text'])
        figures = traced_figures(finding['text'])

        available = set()
        quoted = False
        for number in cited:
            entry = entries.get(number)
            if entry and entry['url']:
                key = canonicalize(entry['url'])
                available.update(by_url.get(key, []))
                quoted = quoted or key in quotes_by_url

        # Roughly half of real findings carry no figure at all, so figure tracing
        # alone leaves them checked only by "somebody opened the page". A recorded
        # quote is what a qualitative claim rests on, and it is also the only part
        # of the evidence that survives the page changing or going dead.
        if cited and not figures and not quoted:
            problems.graded(
                'Finding {} rests on no recorded evidence: it quotes no figure, and none of '
                'its cited sources carries a quote in the fetch log'.format(finding['number']))

        if not figures or not available:
            continue
        untraceable = sorted(figures - available)
        if untraceable:
            problems.graded(
                'Finding {}: figures not found on any cited page that was fetched: {}'.format(
                    finding['number'], ', '.join(untraceable)))


def check_confidence(content, entries, rows, problems, run_independence):
    findings = finding_sections(content)
    if not findings:
        problems.structural('no "## Finding N: ..." sections found')
        return

    by_url = {canonicalize(row.get('url', '')): row for row in rows}

    for finding in findings:
        match = CONFIDENCE_RE.search(finding['text'])
        if not match:
            problems.graded(
                'Finding {} has no "**Confidence: Strong|Moderate|Weak** - ..." line'.format(finding['number']))
            continue
        band = match.group(1).lower()

        if not run_independence:
            continue

        cited_rows = []
        for number in citations_in(finding['text']):
            entry = entries.get(number)
            if entry and entry['url']:
                row = by_url.get(canonicalize(entry['url']))
                if row:
                    cited_rows.append(row)
        if not cited_rows:
            continue

        required = CONFIDENCE_CORROBORATION[band]
        if required == 0:
            continue
        result = corroboration(cited_rows)
        if result['corroboration'] < required:
            problems.graded(
                'Finding {} claims {} confidence but has corroboration {} (needs {}): '
                '{} sources collapse to {} independent group(s) across {} angle(s)'.format(
                    finding['number'], band, result['corroboration'], required,
                    result['sources'], result['groups'], result['angles']))


def check_could_not_answer(content, problems):
    if not CLOSEST_RE.search(content):
        problems.structural(
            'a "could not answer" report must name the closest thing found, on a line starting "Closest"')
    if FINDING_RE.search(content):
        problems.structural('a "could not answer" report must not also ship findings')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(report_path, tsv_path, fmt, level):
    with open(report_path, encoding='utf-8') as handle:
        content = handle.read()

    problems = Problems(level)

    if COULD_NOT_ANSWER_RE.search(content):
        check_could_not_answer(content, problems)
        return problems, {'outcome': 'could-not-answer'}

    if not RECEIPT_RE.search(content):
        problems.graded('no receipt line under the title, e.g. *standard - 4 angles, 9 sources, 3 fetched directly*')

    entries = check_structure(content, fmt, problems, report_path)

    rows = read_rows(tsv_path) if tsv_path else []
    evidence_layers = level in ('standard', 'deep')

    if evidence_layers and entries:
        if not rows:
            problems.graded('no fetch log supplied, so cited URLs cannot be checked against what was retrieved')
        else:
            check_evidence(content, entries, rows, problems)

    if evidence_layers:
        check_confidence(content, entries, rows, problems, run_independence=bool(rows))

    return problems, {'outcome': 'report', 'sources': len(entries), 'fetched': len(rows)}


def main():
    parser = argparse.ArgumentParser(prog='check', description=__doc__.split('\n')[1])
    parser.add_argument('--report', required=True)
    parser.add_argument('--tsv', default=None, help='The run fetch log; defaults to the report path with .tsv')
    parser.add_argument('--format', default='report', choices=list(FORMATS))
    parser.add_argument('--level', default='standard', choices=list(LEVELS))
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(args.report):
        print('error: report not found: {}'.format(args.report), file=sys.stderr)
        sys.exit(2)

    tsv = args.tsv
    if tsv is None:
        candidate = os.path.splitext(args.report)[0] + '.tsv'
        tsv = candidate if os.path.exists(candidate) else None

    problems, summary = run(args.report, tsv, args.format, args.level)
    passed = not problems.errors

    if args.json:
        print(json.dumps({'passed': passed, 'errors': problems.errors,
                          'warnings': problems.warnings, **summary}, indent=2))
    else:
        print('checking {} ({} format, {} level)'.format(
            os.path.basename(args.report), args.format, args.level))
        if tsv:
            print('fetch log: {} ({} rows)'.format(os.path.basename(tsv), summary.get('fetched', 0)))
        print()
        for message in problems.errors:
            print('  ERROR    {}'.format(message))
        for message in problems.warnings:
            print('  warning  {}'.format(message))
        if not problems.errors and not problems.warnings:
            print('  all checks passed')
        print()
        print('PASS' if passed else 'FAIL')

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
