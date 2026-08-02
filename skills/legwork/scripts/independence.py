#!/usr/bin/env python3
"""
independence.py - collapse sources into independent voices, then count
corroboration on the layer Legwork does not amplify.

Three sources agreeing is only evidence if they could have disagreed. Counting
URLs does not establish that. Three tests, cheapest first:

  1. Same canonical URL      - the same page reached twice.
  2. Same party              - every page on a vendor's own domains is one voice
                               about that vendor. In one real run, 26 of 78
                               bibliography entries were learn.microsoft.com.
  3. Same origin             - near-duplicate title and lede, i.e. syndication.
                               Five outlets carrying one wire story is one story.

What survives is a set of INDEPENDENCE GROUPS. "Three independent sources" means
three groups.

Corroboration then goes one step further. Legwork's Gather phase fans out across
sub-questions specifically in order to find more sources per finding, so any
count downstream of that fan-out partly measures our own effort. The layer we do
not amplify is which ANGLE surfaced a source. So corroboration is the largest
set of groups that can each be attributed to a DIFFERENT angle - a maximum
matching between groups and angles. Five sources from one line of enquiry score
1, however many distinct domains they span.

CLI:
    independence.py groups --tsv PATH [--format table|json]
    independence.py check  --tsv PATH [--urls URL,URL,...] [--min 2] [--format text|json]

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from urllib.parse import urlparse, urlunparse

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from sources import read_rows  # noqa: E402

# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------

# Query parameters that identify the referrer or campaign, not the content.
TRACKING_PARAMS = frozenset([
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'ref', 'ref_src', 'source', 'fbclid', 'gclid', 'msclkid', 'mc_cid', 'mc_eid',
    'igshid', 'cmpid', 'ncid', 's_cid', 'sc_channel',
])


def canonicalize(raw_url):
    """Normalise a URL so the same page reached two ways compares equal.

    Lowercases scheme and host, drops 'www.', strips the fragment and any
    tracking parameters, removes a trailing slash, and sorts what remains.
    """
    parsed = urlparse((raw_url or '').strip())
    scheme = (parsed.scheme or 'https').lower()
    host = (parsed.hostname or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    path = (parsed.path or '').rstrip('/')
    if parsed.query:
        kept = [part for part in parsed.query.split('&')
                if part.split('=', 1)[0].lower() not in TRACKING_PARAMS]
        query = '&'.join(sorted(kept))
    else:
        query = ''
    return urlunparse((scheme, host, path, '', query, ''))


# Public suffixes with two labels. Not the full Public Suffix List - that is a
# 200KB download and this is a stdlib-only skill - but it covers the suffixes
# that actually appear in research bibliographies. A miss degrades safely: two
# sources that ARE the same party get treated as independent, which understates
# corroboration rather than overstating it.
TWO_LABEL_SUFFIXES = frozenset([
    'co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'net.uk', 'sch.uk', 'nhs.uk', 'police.uk',
    'com.au', 'net.au', 'org.au', 'edu.au', 'gov.au',
    'co.nz', 'org.nz', 'govt.nz',
    'co.za', 'org.za',
    'co.jp', 'or.jp', 'ne.jp', 'ac.jp', 'go.jp',
    'com.br', 'com.cn', 'com.hk', 'com.sg', 'com.tr', 'com.mx', 'com.ar',
    'co.in', 'co.il', 'co.kr', 'co.id',
])


def registrable_domain(host):
    """The domain a party actually registered: 'learn.microsoft.com' -> 'microsoft.com'."""
    host = (host or '').lower().strip('.')
    if not host:
        return ''
    labels = host.split('.')
    if len(labels) < 3:
        return host
    if '.'.join(labels[-2:]) in TWO_LABEL_SUFFIXES:
        return '.'.join(labels[-3:])
    return '.'.join(labels[-2:])


def party_of(url):
    return registrable_domain(urlparse((url or '').strip()).hostname or '')


# ---------------------------------------------------------------------------
# Near-duplicate detection
# ---------------------------------------------------------------------------

STOPWORDS = frozenset([
    'the', 'a', 'an', 'to', 'for', 'how', 'is', 'in', 'of', 'on', 'and', 'with',
    'from', 'by', 'at', 'this', 'that', 'it', 'what', 'are', 'do', 'can', 'as',
    'its', 'be', 'or', 'not', 'no', 'so', 'if', 'but', 'about', 'has', 'have',
    'will', 'new', 'says', 'said',
])

SIMILARITY_THRESHOLD = 0.70


def normalise(text):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', (text or '').lower())).strip()


def trigrams(normalised):
    if len(normalised) < 3:
        return {normalised} if normalised else set()
    return {normalised[i:i + 3] for i in range(len(normalised) - 2)}


def content_tokens(normalised):
    return {token for token in normalised.split() if len(token) > 1 and token not in STOPWORDS}


def jaccard(left, right):
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def hybrid_similarity(text_a, text_b):
    """max(character-trigram Jaccard, content-token Jaccard).

    Trigrams catch reworded-but-derived headlines; tokens catch reordering. Taking
    the max means either signal alone is enough to call syndication.
    """
    norm_a, norm_b = normalise(text_a), normalise(text_b)
    return max(jaccard(trigrams(norm_a), trigrams(norm_b)),
               jaccard(content_tokens(norm_a), content_tokens(norm_b)))


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


class _Union:
    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, index):
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def join(self, left, right):
        root_l, root_r = self.find(left), self.find(right)
        if root_l != root_r:
            self.parent[root_r] = root_l


def group_sources(rows, threshold=SIMILARITY_THRESHOLD):
    """Collapse rows into independence groups.

    Each row needs 'url' and, for the syndication test, 'title'. Returns a list
    of groups, each {'members': [row, ...], 'angles': [...], 'reason': str}.
    """
    if not rows:
        return []
    canonical = [canonicalize(row.get('url', '')) for row in rows]
    parties = [party_of(row.get('url', '')) for row in rows]
    titles = [row.get('title', '') for row in rows]

    union = _Union(len(rows))
    reasons = {}

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if canonical[i] and canonical[i] == canonical[j]:
                union.join(i, j)
                reasons.setdefault(union.find(i), 'same page')
            elif parties[i] and parties[i] == parties[j]:
                union.join(i, j)
                reasons.setdefault(union.find(i), 'same party ({})'.format(parties[i]))
            elif titles[i] and titles[j] and hybrid_similarity(titles[i], titles[j]) >= threshold:
                union.join(i, j)
                reasons.setdefault(union.find(i), 'same origin (near-duplicate title)')

    buckets = {}
    for index, row in enumerate(rows):
        buckets.setdefault(union.find(index), []).append(row)

    groups = []
    for root, members in buckets.items():
        angles = []
        for member in members:
            angle = (member.get('angle') or '').strip()
            if angle and angle not in angles:
                angles.append(angle)
        groups.append({
            'members': members,
            'angles': angles,
            'reason': reasons.get(root, 'independent'),
            'party': party_of(members[0].get('url', '')),
        })
    groups.sort(key=lambda g: (-len(g['members']), g['party']))
    return groups


# ---------------------------------------------------------------------------
# Corroboration
# ---------------------------------------------------------------------------


def _max_matching(adjacency, right_size):
    """Maximum bipartite matching, left index -> set of right indices."""
    match_right = [-1] * right_size

    def augment(left, seen):
        for right in adjacency[left]:
            if right in seen:
                continue
            seen.add(right)
            if match_right[right] == -1 or augment(match_right[right], seen):
                match_right[right] = left
                return True
        return False

    return sum(1 for left in range(len(adjacency)) if augment(left, set()))


def corroboration(rows, threshold=SIMILARITY_THRESHOLD):
    """How many independent confirmations these rows actually represent.

    The count is a maximum matching between independence groups and the angles
    that surfaced them, so two groups that were both only reached by one angle
    score 1, not 2. Rows carrying no angle fall back to a per-group placeholder
    so an unlabelled log degrades to plain group counting.
    """
    groups = group_sources(rows, threshold=threshold)
    angle_index = {}
    adjacency = []
    for position, group in enumerate(groups):
        angles = group['angles'] or ['__unlabelled_{}__'.format(position)]
        indices = []
        for angle in angles:
            if angle not in angle_index:
                angle_index[angle] = len(angle_index)
            indices.append(angle_index[angle])
        adjacency.append(indices)
    score = _max_matching(adjacency, len(angle_index)) if adjacency else 0
    return {
        'sources': len(rows),
        'groups': len(groups),
        'angles': len(angle_index),
        'corroboration': score,
        'detail': [
            {'party': g['party'], 'members': len(g['members']), 'angles': g['angles'], 'reason': g['reason']}
            for g in groups
        ],
    }


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

# Corroboration is asked per finding. Nothing was ever asked of the run as a
# whole, so a report could pass on every finding while most of the document rested
# on one party. These are deliberately loose: the check exists to catch a lopsided
# run, not to impose a source quota.
DEFAULT_MAX_PARTY_SHARE = 0.5
DEFAULT_MIN_PARTIES = 3
# Party share and group share catch different failures and neither implies the
# other. Six outlets syndicating one wire story are six parties and one voice:
# party share calls that perfectly balanced, and only group share sees it.
DEFAULT_MAX_GROUP_SHARE = 0.6


def portfolio(rows, max_party_share=DEFAULT_MAX_PARTY_SHARE, min_parties=DEFAULT_MIN_PARTIES,
              max_group_share=DEFAULT_MAX_GROUP_SHARE):
    """Concentration across a whole run, rather than within one finding.

    Share is counted on retrievals, not on groups. Eight pages from one vendor
    collapse to a single group, so measuring at group level would report a run
    dominated by that vendor as perfectly balanced.
    """
    if not rows:
        return {'sources': 0, 'groups': 0, 'parties': 0, 'angles': 0,
                'top_party': '', 'top_party_share': 0.0, 'top_group_share': 0.0,
                'passed': True, 'failures': []}

    groups = group_sources(rows)

    party_counts = {}
    for row in rows:
        party = party_of(row.get('url', '')) or '(unknown)'
        party_counts[party] = party_counts.get(party, 0) + 1
    top_party, top_count = max(party_counts.items(), key=lambda kv: (kv[1], kv[0]))

    angles = {(row.get('angle') or '').strip() for row in rows}
    angles.discard('')

    top_group = max(len(g['members']) for g in groups)

    result = {
        'sources': len(rows),
        'groups': len(groups),
        'parties': len(party_counts),
        'angles': len(angles),
        'top_party': top_party,
        'top_party_share': top_count / len(rows),
        'top_group_share': top_group / len(rows),
    }

    failures = []
    if result['top_party_share'] > max_party_share:
        failures.append(
            'source concentration: {:.0f}% of retrievals come from one party ({}), '
            'above the {:.0f}% limit'.format(
                result['top_party_share'] * 100, top_party, max_party_share * 100))
    if result['parties'] < min_parties:
        failures.append(
            'source concentration: only {} distinct parties across the whole run '
            '(need at least {})'.format(result['parties'], min_parties))
    if result['top_group_share'] > max_group_share:
        failures.append(
            'source concentration: {:.0f}% of retrievals collapse into one independence '
            'group - a single voice however many domains it spans - above the {:.0f}% '
            'limit'.format(result['top_group_share'] * 100, max_group_share * 100))
    result['failures'] = failures
    result['passed'] = not failures
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _select(rows, urls):
    if not urls:
        return rows
    wanted = {canonicalize(url) for url in urls}
    return [row for row in rows if canonicalize(row.get('url', '')) in wanted]


def cmd_groups(args):
    rows = _select(read_rows(args.tsv), args.urls.split(',') if args.urls else None)
    groups = group_sources(rows)
    if args.format == 'json':
        print(json.dumps([
            {'party': g['party'], 'reason': g['reason'], 'angles': g['angles'],
             'urls': [m.get('url', '') for m in g['members']]}
            for g in groups
        ], indent=2))
        return
    print('{} sources -> {} independent groups'.format(len(rows), len(groups)))
    for group in groups:
        print('\n  {} ({} source{}, {})'.format(
            group['party'] or '(unknown)', len(group['members']),
            '' if len(group['members']) == 1 else 's', group['reason']))
        print('    angles: {}'.format(', '.join(group['angles']) or '(none recorded)'))
        for member in group['members']:
            print('      {}'.format(member.get('url', '')[:88]))


def cmd_check(args):
    rows = _select(read_rows(args.tsv), args.urls.split(',') if args.urls else None)
    result = corroboration(rows)
    result['min_required'] = args.min
    result['passed'] = result['corroboration'] >= args.min
    if args.format == 'json':
        print(json.dumps(result, indent=2))
    else:
        print('{} sources, {} independent groups, {} angles -> corroboration {} (need {}) : {}'.format(
            result['sources'], result['groups'], result['angles'],
            result['corroboration'], args.min, 'PASS' if result['passed'] else 'FAIL'))
        for entry in result['detail']:
            print('  {:<28} {:>2} source(s)  {}'.format(
                entry['party'] or '(unknown)', entry['members'], entry['reason']))
    sys.exit(0 if result['passed'] else 1)


def cmd_portfolio(args):
    rows = read_rows(args.tsv)
    result = portfolio(rows, max_party_share=args.max_party_share, min_parties=args.min_parties,
                       max_group_share=args.max_group_share)
    if args.format == 'json':
        print(json.dumps(result, indent=2))
    else:
        print('{} sources -> {} groups, {} parties, {} angles'.format(
            result['sources'], result['groups'], result['parties'], result['angles']))
        print('largest party: {} ({:.0f}% of retrievals)'.format(
            result['top_party'] or '(none)', result['top_party_share'] * 100))
        print('largest group: {:.0f}% of retrievals'.format(result['top_group_share'] * 100))
        for failure in result['failures']:
            print('  FAIL  {}'.format(failure))
        if result['passed']:
            print('  PASS')
    sys.exit(0 if result['passed'] else 1)


def main():
    parser = argparse.ArgumentParser(prog='independence', description=__doc__.split('\n')[1])
    sub = parser.add_subparsers(dest='command', required=True)

    p_groups = sub.add_parser('groups', help='Show the independence groups in a fetch log')
    p_groups.add_argument('--tsv', required=True)
    p_groups.add_argument('--urls', default='', help='Comma-separated subset of URLs to consider')
    p_groups.add_argument('--format', default='table', choices=['table', 'json'])

    p_check = sub.add_parser('check', help='Assert a minimum corroboration level')
    p_check.add_argument('--tsv', required=True)
    p_check.add_argument('--urls', default='', help='Comma-separated subset of URLs to consider')
    p_check.add_argument('--min', type=int, default=2)
    p_check.add_argument('--format', default='text', choices=['text', 'json'])

    p_portfolio = sub.add_parser('portfolio', help='Source concentration across the whole run')
    p_portfolio.add_argument('--tsv', required=True)
    p_portfolio.add_argument('--max-party-share', type=float, default=DEFAULT_MAX_PARTY_SHARE)
    p_portfolio.add_argument('--min-parties', type=int, default=DEFAULT_MIN_PARTIES)
    p_portfolio.add_argument('--max-group-share', type=float, default=DEFAULT_MAX_GROUP_SHARE)
    p_portfolio.add_argument('--format', default='table', choices=['table', 'json'])

    args = parser.parse_args()
    {'groups': cmd_groups, 'check': cmd_check, 'portfolio': cmd_portfolio}[args.command](args)


if __name__ == '__main__':
    main()
