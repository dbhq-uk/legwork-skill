#!/usr/bin/env python3
"""
platforms.py - free platform-native retrieval, where the platform holds the record.

    platforms.py list
    platforms.py search --on hn --query "pgvector" --limit 10

A search engine returns pages *about* a thing. A platform's own API returns the
thing: the thread, the question, the repository, the package, the dated news
item, the vendor's own changelog entry. Legwork's doctrine already says the
complaints themselves are primary evidence of sentiment and an article about the
complaints is not, and that an enumeration must be rebuilt from its items. This
is how that is done without paying for it.

Every endpoint here needs no key and was probed on 2026-09-06. Reddit is
deliberately absent: both www.reddit.com and old.reddit.com answer 403 to a
plain request, which is what the paid `bd_search.py -m reddit` rung is for.

Results are normalised to one shape, so the caller logs them the same way
whatever the platform:

    {"url", "title", "date", "snippet", "kind", "signal"}

`signal` carries the platform's own numbers - points, comments, stars, weekly
downloads, answer counts. That is the part a search snippet can never supply
and the part a demand question actually turns on.

Rows are logged `--via api`: an API record is the record, not a snippet about
it. Stdlib only, python3 >= 3.9. No credentials are required. GITHUB_TOKEN is
used if it is already in the environment, never required, never written down.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.parse import quote_plus, urlencode, urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch import (  # noqa: E402
    USER_AGENT, BlockedAddress, _check_target, html_to_text, normalise_date)

TIMEOUT = 20
MAX_BYTES = 4 * 1024 * 1024

PLATFORMS = {
    'hn': 'Hacker News threads and comments, with points and comment counts (community)',
    'stackexchange': 'Stack Overflow questions, with scores and answer counts (community)',
    'github': 'Repositories, with stars and last push (registry)',
    'githubissues': 'Issues and pull requests, as evidence of live problems (community)',
    'npm': 'npm packages, with weekly downloads (registry)',
    'pypi': 'A PyPI package: current version and release date (registry)',
    'wikipedia': 'Wikipedia articles, for background and entity checks (blog tier)',
    'news': 'Google News, dated, with real country and language control (press)',
    'feed': 'A site\'s own RSS or Atom feed: changelogs and announcements (vendor_announcement)',
    'wayback': 'The Internet Archive: what a dead or changed page used to say (pass --kind yourself)',
}


def _assert_vocabulary_agrees():
    """Every kind emitted here must be one `sources.py log --kind` accepts.

    The two scripts are a pipeline: platforms.py hands rows to sources.py. A
    kind that only one of them knows fails at the far end of a long run, which
    is the worst place to find it.
    """
    from sources import SOURCE_KINDS
    unknown = sorted(set(EMITTED_KINDS) - set(SOURCE_KINDS))
    assert not unknown, 'kinds sources.py will reject: {}'.format(unknown)


def _fail(message, code=1, **extra):
    payload = {'error': message}
    payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)


def _get(url, headers=None, accept='application/json'):
    """One GET against a known endpoint. `feed` mode validates its URL first."""
    request = Request(url, headers=dict({
        'User-Agent': USER_AGENT,
        'Accept': accept,
        'Accept-Language': 'en-GB,en;q=0.9',
    }, **(headers or {})))
    try:
        with urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 - validated or fixed endpoint
            return response.read(MAX_BYTES).decode('utf-8', errors='replace')
    except HTTPError as exc:
        _fail('{} returned HTTP {}'.format(url.split('/')[2], exc.code), code=1, status=exc.code)
    except (URLError, OSError, ValueError) as exc:
        _fail('{}: {}'.format(url.split('/')[2] if '//' in url else url, exc))


def _get_json(url, headers=None):
    raw = _get(url, headers)
    try:
        return json.loads(raw)
    except ValueError:
        _fail('response was not JSON: {}'.format(raw[:200]))


def _clip(text, limit=300):
    return re.sub(r'\s+', ' ', (text or '')).strip()[:limit]


# ---------------------------------------------------------------------------
# One function per platform. Each returns (endpoint, [normalised results]).
# ---------------------------------------------------------------------------

def search_hn(args):
    params = {'query': args.query, 'hitsPerPage': min(args.limit, 50)}
    if args.since:
        params['numericFilters'] = 'created_at_i>{}'.format(_epoch(args.since))
    endpoint = 'https://hn.algolia.com/api/v1/search?' + urlencode(params)
    data = _get_json(endpoint)
    results = []
    for hit in data.get('hits', [])[:args.limit]:
        object_id = hit.get('objectID', '')
        results.append({
            'url': hit.get('url') or 'https://news.ycombinator.com/item?id={}'.format(object_id),
            'title': hit.get('title') or hit.get('story_title') or _clip(hit.get('comment_text'), 120),
            'date': (hit.get('created_at') or '')[:10],
            'snippet': _clip(hit.get('story_text') or hit.get('comment_text') or hit.get('title')),
            'kind': 'community',
            'signal': {'points': hit.get('points') or 0, 'comments': hit.get('num_comments') or 0,
                       'discussion': 'https://news.ycombinator.com/item?id={}'.format(object_id)},
        })
    return endpoint, results


def search_stackexchange(args):
    params = {'order': 'desc', 'sort': 'relevance', 'q': args.query,
              'site': args.site or 'stackoverflow', 'pagesize': min(args.limit, 50),
              'filter': 'withbody'}
    if args.since:
        params['fromdate'] = _epoch(args.since)
    endpoint = 'https://api.stackexchange.com/2.3/search/advanced?' + urlencode(params)
    data = _get_json(endpoint)
    results = []
    for item in data.get('items', [])[:args.limit]:
        results.append({
            'url': item.get('link', ''),
            'title': item.get('title', ''),
            'date': _from_epoch(item.get('creation_date')),
            'snippet': _clip(html_to_text(item.get('body') or '')),
            'kind': 'community',
            'signal': {'score': item.get('score') or 0, 'answers': item.get('answer_count') or 0,
                       'accepted': bool(item.get('is_answered')), 'views': item.get('view_count') or 0,
                       'tags': item.get('tags') or []},
        })
    return endpoint, results


def _github_headers():
    headers = {'Accept': 'application/vnd.github+json'}
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    if token:
        headers['Authorization'] = 'Bearer {}'.format(token)
    return headers


def search_github(args):
    endpoint = 'https://api.github.com/search/repositories?' + urlencode(
        {'q': args.query, 'sort': 'stars', 'order': 'desc', 'per_page': min(args.limit, 50)})
    data = _get_json(endpoint, _github_headers())
    results = []
    for repo in data.get('items', [])[:args.limit]:
        results.append({
            'url': repo.get('html_url', ''),
            'title': repo.get('full_name', ''),
            'date': (repo.get('pushed_at') or '')[:10],
            'snippet': _clip(repo.get('description')),
            'kind': 'registry',
            'signal': {'stars': repo.get('stargazers_count') or 0,
                       'forks': repo.get('forks_count') or 0,
                       'open_issues': repo.get('open_issues_count') or 0,
                       'archived': bool(repo.get('archived')),
                       'license': ((repo.get('license') or {}).get('spdx_id') or '')},
        })
    return endpoint, results


def search_githubissues(args):
    endpoint = 'https://api.github.com/search/issues?' + urlencode(
        {'q': args.query, 'sort': 'comments', 'order': 'desc', 'per_page': min(args.limit, 50)})
    data = _get_json(endpoint, _github_headers())
    results = []
    for issue in data.get('items', [])[:args.limit]:
        results.append({
            'url': issue.get('html_url', ''),
            'title': issue.get('title', ''),
            'date': (issue.get('created_at') or '')[:10],
            'snippet': _clip(issue.get('body')),
            'kind': 'community',
            'signal': {'comments': issue.get('comments') or 0,
                       'state': issue.get('state') or '',
                       'reactions': ((issue.get('reactions') or {}).get('total_count') or 0)},
        })
    return endpoint, results


def search_npm(args):
    endpoint = 'https://registry.npmjs.org/-/v1/search?' + urlencode(
        {'text': args.query, 'size': min(args.limit, 50)})
    data = _get_json(endpoint)
    results = []
    for entry in data.get('objects', [])[:args.limit]:
        package = entry.get('package', {})
        downloads = entry.get('downloads') or {}
        results.append({
            'url': (package.get('links') or {}).get('npm') or
                   'https://www.npmjs.com/package/{}'.format(package.get('name', '')),
            'title': '{} {}'.format(package.get('name', ''), package.get('version', '')).strip(),
            'date': (package.get('date') or '')[:10],
            'snippet': _clip(package.get('description')),
            'kind': 'registry',
            'signal': {'weekly_downloads': downloads.get('weekly') or 0,
                       'monthly_downloads': downloads.get('monthly') or 0,
                       'version': package.get('version') or ''},
        })
    return endpoint, results


def search_pypi(args):
    """PyPI has no search API. The package's own JSON is the record."""
    name = args.query.strip()
    endpoint = 'https://pypi.org/pypi/{}/json'.format(quote_plus(name))
    data = _get_json(endpoint)
    info = data.get('info', {})
    version = info.get('version', '')
    released = ''
    for upload in (data.get('releases', {}).get(version) or []):
        released = (upload.get('upload_time_iso_8601') or upload.get('upload_time') or '')[:10]
        if released:
            break
    return endpoint, [{
        'url': info.get('package_url') or 'https://pypi.org/project/{}/'.format(name),
        'title': '{} {}'.format(info.get('name', name), version).strip(),
        'date': released,
        'snippet': _clip(info.get('summary')),
        'kind': 'registry',
        'signal': {'version': version, 'requires_python': info.get('requires_python') or '',
                   'licence': info.get('license') or '', 'yanked': bool(info.get('yanked'))},
    }]


def search_wikipedia(args):
    endpoint = 'https://{}.wikipedia.org/w/api.php?'.format(args.language or 'en') + urlencode(
        {'action': 'query', 'list': 'search', 'srsearch': args.query,
         'srlimit': min(args.limit, 50), 'format': 'json'})
    data = _get_json(endpoint)
    results = []
    for hit in (data.get('query', {}).get('search') or [])[:args.limit]:
        title = hit.get('title', '')
        results.append({
            'url': 'https://{}.wikipedia.org/wiki/{}'.format(
                args.language or 'en', quote_plus(title.replace(' ', '_'))),
            'title': title,
            'date': (hit.get('timestamp') or '')[:10],
            'snippet': _clip(html_to_text(hit.get('snippet') or '')),
            # 'blog' is the vocabulary's commentary tier. A tertiary summary is
            # not primary evidence of anything, and scoring it as such would be
            # the "respectable domain" mistake the redesign removed.
            'kind': 'blog',
            'signal': {'words': hit.get('wordcount') or 0},
        })
    return endpoint, results


def search_news(args):
    """Google News RSS. Free, dated, and the only free path with real geo control."""
    country = (args.country or 'GB').upper()
    language = args.language or 'en'
    endpoint = 'https://news.google.com/rss/search?' + urlencode({
        'q': args.query, 'hl': '{}-{}'.format(language, country),
        'gl': country, 'ceid': '{}:{}'.format(country, language)})
    return endpoint, _parse_feed(_get(endpoint, accept='application/rss+xml'), args, kind='press')


_FEED_LINK_RE = re.compile(
    r'<link\b[^>]*application/(?:rss|atom)\+xml[^>]*>', re.I)
_HREF_RE = re.compile(r'\bhref\s*=\s*["\']([^"\']+)', re.I)


def search_feed(args):
    """A site's own feed: changelogs and announcements, each with its own date."""
    target = args.query.strip()
    if not target.startswith(('http://', 'https://')):
        _fail('feed mode takes a site or feed URL, got: {}'.format(target[:80]))
    # The only mode here that takes an arbitrary URL rather than a fixed
    # endpoint, so it is the only one that needs the address guard.
    try:
        _check_target(target)
    except BlockedAddress as exc:
        _fail(str(exc))
    body = _get(target, accept='application/rss+xml, application/atom+xml, text/html;q=0.9')
    if '<rss' not in body[:2000].lower() and '<feed' not in body[:2000].lower():
        found = _FEED_LINK_RE.search(body)
        if not found:
            _fail('no RSS or Atom feed advertised at {}'.format(target[:80]))
        href = _HREF_RE.search(found.group(0))
        if not href:
            _fail('feed link carries no href at {}'.format(target[:80]))
        # urljoin, not string surgery: a feed link is as likely to be
        # `feed.xml` or `../rss` as `/feed`, and only the root-relative form
        # survived being pasted together by hand.
        target = urljoin(args.query, href.group(1))
        _check_target(target)
        body = _get(target, accept='application/rss+xml, application/atom+xml')
    return target, _parse_feed(body, args, kind='vendor_announcement')


def _parse_feed(body, args, kind):
    try:
        root = ElementTree.fromstring(body.encode('utf-8'))
    except ElementTree.ParseError as exc:
        _fail('feed did not parse: {}'.format(exc))
    atom = '{http://www.w3.org/2005/Atom}'
    entries = root.findall('.//item') or root.findall('.//{}entry'.format(atom))
    results = []
    for entry in entries:
        def text(*names):
            for name in names:
                node = entry.find(name)
                if node is not None:
                    if node.text:
                        return node.text
                    if node.get('href'):
                        return node.get('href')
            return ''
        date = normalise_date(text('pubDate', 'published', '{}published'.format(atom),
                                   '{}updated'.format(atom), 'updated', 'dc:date'))
        if args.since and date and date < args.since:
            continue
        results.append({
            'url': text('link', '{}link'.format(atom)),
            'title': _clip(html_to_text(text('title', '{}title'.format(atom))), 200),
            'date': date,
            'snippet': _clip(html_to_text(text('description', 'summary', '{}summary'.format(atom),
                                               '{}content'.format(atom)))),
            'kind': kind,
            'signal': {'source': _clip(text('source'), 80)},
        })
        if len(results) >= args.limit:
            break
    return results


def search_wayback(args):
    """What a page said before it changed, or before it died."""
    target = args.query.strip()
    params = {'url': target}
    if args.since:
        params['timestamp'] = args.since.replace('-', '')
    endpoint = 'https://archive.org/wayback/available?' + urlencode(params)
    data = _get_json(endpoint)
    snapshot = ((data.get('archived_snapshots') or {}).get('closest') or {})
    if not snapshot.get('available'):
        return endpoint, []
    stamp = snapshot.get('timestamp', '')
    return endpoint, [{
        'url': snapshot.get('url', ''),
        'title': 'Archived snapshot of {}'.format(target),
        'date': '{}-{}-{}'.format(stamp[0:4], stamp[4:6], stamp[6:8]) if len(stamp) >= 8 else '',
        'snippet': 'Internet Archive snapshot taken {}.'.format(stamp),
        # An archived page keeps the kind of the page it archives; only the
        # caller knows what that was, so log this row with --kind explicitly.
        'kind': 'unknown',
        'signal': {'status': snapshot.get('status', ''), 'timestamp': stamp},
    }]


# Kept beside the searchers so the guard below has something to check.
EMITTED_KINDS = ('community', 'registry', 'blog', 'press', 'vendor_announcement', 'unknown')

SEARCHERS = {
    'hn': search_hn,
    'stackexchange': search_stackexchange,
    'github': search_github,
    'githubissues': search_githubissues,
    'npm': search_npm,
    'pypi': search_pypi,
    'wikipedia': search_wikipedia,
    'news': search_news,
    'feed': search_feed,
    'wayback': search_wayback,
}


def _epoch(date_string):
    from datetime import datetime, timezone
    return int(datetime.strptime(date_string, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())


def _from_epoch(value):
    if not value:
        return ''
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(value), tz=timezone.utc).date().isoformat()


def cmd_list(_args):
    for name in sorted(PLATFORMS):
        print('{:<15} {}'.format(name, PLATFORMS[name]))


def cmd_search(args):
    endpoint, results = SEARCHERS[args.on](args)
    if args.since:
        results = [r for r in results if not r['date'] or r['date'] >= args.since]
    payload = {'platform': args.on, 'query': args.query, 'endpoint': endpoint,
               'results': results[:args.limit]}
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='platforms.py', description=__doc__.split('\n')[1])
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('list', help='The platforms, and which source kind each produces')

    p_search = sub.add_parser('search', help='Query one platform')
    p_search.add_argument('--on', required=True, choices=sorted(SEARCHERS))
    p_search.add_argument('--query', required=True,
                          help='Search terms; a package name for pypi; a URL for feed and wayback')
    p_search.add_argument('--limit', type=int, default=10)
    p_search.add_argument('--since', default='', metavar='YYYY-MM-DD')
    p_search.add_argument('--country', default=os.environ.get('LEGWORK_COUNTRY', ''),
                          help='Two-letter code; news only')
    p_search.add_argument('--language', default='', help='Two-letter code; news and wikipedia')
    p_search.add_argument('--site', default='', help='Stack Exchange site, default stackoverflow')
    p_search.add_argument('--out', default=None, help='Also write the JSON here')
    p_search.add_argument('--json', action='store_true', help='Accepted for compat; output is always JSON')

    args = parser.parse_args(argv)
    {'list': cmd_list, 'search': cmd_search}[args.command](args)


main_with_args = main


if __name__ == '__main__':
    main()
