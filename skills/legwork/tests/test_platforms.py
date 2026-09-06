"""Free platform-native retrieval.

Hermetic: every response body below is a trimmed recording of the real endpoint,
probed on 2026-09-06, and urlopen is patched to return it. No socket is opened.

What these pin is the normalisation. A platform that changes its field names
should fail here rather than silently returning rows with empty dates, because
an undated row is exactly what the gate cannot judge.
"""

import json

import pytest

import fetch
import platforms


class _Response:
    def __init__(self, body):
        self._body = body.encode('utf-8') if isinstance(body, str) else body

    def read(self, *_):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture(autouse=True)
def _resolvable(monkeypatch):
    """Feed mode validates the address it is given; a test must not touch DNS."""
    monkeypatch.setattr(fetch, '_is_public', lambda host: True)


def run(monkeypatch, capsys, body, argv):
    monkeypatch.setattr(platforms, 'urlopen', lambda *a, **k: _Response(body))
    platforms.main_with_args(argv)
    return json.loads(capsys.readouterr().out)


HN = json.dumps({'hits': [
    {'objectID': '41194990', 'title': 'The Case Against PGVector', 'url': 'https://blog.example/case',
     'points': 381, 'num_comments': 137, 'created_at': '2025-11-03T14:02:11.000Z',
     'story_text': 'Vector search in Postgres has costs people underestimate.'}]})

SE = json.dumps({'items': [
    {'title': 'Installing PGVector', 'link': 'https://stackoverflow.com/questions/1',
     'creation_date': 1732060800, 'score': 4, 'answer_count': 1, 'is_answered': True,
     'view_count': 3396, 'tags': ['postgresql'], 'body': '<p>How do I <b>install</b> it?</p>'}]})

GH = json.dumps({'items': [
    {'full_name': 'pgvector/pgvector', 'html_url': 'https://github.com/pgvector/pgvector',
     'description': 'Open-source vector similarity search for Postgres',
     'stargazers_count': 18000, 'forks_count': 900, 'open_issues_count': 12,
     'pushed_at': '2026-08-31T10:00:00Z', 'archived': False, 'license': {'spdx_id': 'PostgreSQL'}}]})

GH_ISSUES = json.dumps({'items': [
    {'title': 'HNSW index build is slow above 10M rows',
     'html_url': 'https://github.com/pgvector/pgvector/issues/500',
     'created_at': '2026-07-14T08:00:00Z', 'comments': 42, 'state': 'open',
     'reactions': {'total_count': 18}, 'body': 'Index build takes hours.'}]})

NPM = json.dumps({'objects': [
    {'package': {'name': 'pgvector', 'version': '0.3.0', 'date': '2026-05-31T09:00:00.000Z',
                 'description': 'pgvector support for Node.js',
                 'links': {'npm': 'https://www.npmjs.com/package/pgvector'}},
     'downloads': {'weekly': 461325, 'monthly': 1742940}}]})

PYPI = json.dumps({'info': {'name': 'requests', 'version': '2.34.2', 'summary': 'HTTP for Humans.',
                            'package_url': 'https://pypi.org/project/requests/',
                            'requires_python': '>=3.10', 'license': 'Apache-2.0', 'yanked': False},
                   'releases': {'2.34.2': [{'upload_time_iso_8601': '2026-05-14T12:00:00.000000Z'}]}})

WIKI = json.dumps({'query': {'search': [
    {'title': 'Vector database', 'timestamp': '2026-08-27T00:00:00Z', 'wordcount': 1876,
     'snippet': 'A <span class="searchmatch">vector</span> database stores embeddings'}]}})

NEWS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Running pgvector in production</title><link>https://news.example/a</link>
<pubDate>Thu, 25 Jun 2026 09:00:00 GMT</pubDate>
<description>&lt;p&gt;A production write-up.&lt;/p&gt;</description><source>AWS</source></item>
<item><title>An older piece</title><link>https://news.example/b</link>
<pubDate>Mon, 05 Jan 2026 09:00:00 GMT</pubDate><description>Older.</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Release 3.1</title><link href="https://vendor.example/notes/3-1"/>
<published>2026-08-02T00:00:00Z</published><summary>Adds SSO.</summary></entry></feed>"""

WAYBACK = json.dumps({'archived_snapshots': {'closest': {
    'available': True, 'url': 'http://web.archive.org/web/20240101000000/https://gone.example/',
    'timestamp': '20240101000000', 'status': '200'}}})


# ---------------------------------------------------------------------------
# Every platform normalises to one shape, with a date and a signal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('body,argv,expected', [
    (HN, ['search', '--on', 'hn', '--query', 'pgvector'],
     {'kind': 'community', 'date': '2025-11-03', 'signal_key': 'points'}),
    (SE, ['search', '--on', 'stackexchange', '--query', 'pgvector'],
     {'kind': 'community', 'date': '2024-11-20', 'signal_key': 'answers'}),
    (GH, ['search', '--on', 'github', '--query', 'pgvector'],
     {'kind': 'registry', 'date': '2026-08-31', 'signal_key': 'stars'}),
    (GH_ISSUES, ['search', '--on', 'githubissues', '--query', 'pgvector'],
     {'kind': 'community', 'date': '2026-07-14', 'signal_key': 'comments'}),
    (NPM, ['search', '--on', 'npm', '--query', 'pgvector'],
     {'kind': 'registry', 'date': '2026-05-31', 'signal_key': 'weekly_downloads'}),
    (PYPI, ['search', '--on', 'pypi', '--query', 'requests'],
     {'kind': 'registry', 'date': '2026-05-14', 'signal_key': 'version'}),
    (WIKI, ['search', '--on', 'wikipedia', '--query', 'vector database'],
     {'kind': 'blog', 'date': '2026-08-27', 'signal_key': 'words'}),
    (NEWS, ['search', '--on', 'news', '--query', 'pgvector'],
     {'kind': 'press', 'date': '2026-06-25', 'signal_key': 'source'}),
    (WAYBACK, ['search', '--on', 'wayback', '--query', 'https://gone.example/'],
     {'kind': 'unknown', 'date': '2024-01-01', 'signal_key': 'timestamp'}),
])
def test_each_platform_returns_the_common_shape(monkeypatch, capsys, body, argv, expected):
    payload = run(monkeypatch, capsys, body, argv)
    row = payload['results'][0]
    assert set(row) == {'url', 'title', 'date', 'snippet', 'kind', 'signal'}
    assert row['url'].startswith('http')
    assert row['title']
    assert row['date'] == expected['date']
    assert row['kind'] == expected['kind']
    assert expected['signal_key'] in row['signal']


def test_the_signal_is_the_thing_a_snippet_cannot_give(monkeypatch, capsys):
    """Points and comment counts are the evidence a demand question turns on."""
    row = run(monkeypatch, capsys, HN, ['search', '--on', 'hn', '--query', 'x'])['results'][0]
    assert row['signal']['points'] == 381
    assert row['signal']['comments'] == 137
    assert row['signal']['discussion'].startswith('https://news.ycombinator.com/item?id=')


def test_html_in_a_body_is_reduced_to_text(monkeypatch, capsys):
    row = run(monkeypatch, capsys, SE, ['search', '--on', 'stackexchange', '--query', 'x'])['results'][0]
    assert row['snippet'] == 'How do I install it?'


def test_a_hacker_news_comment_with_no_url_falls_back_to_the_thread(monkeypatch, capsys):
    body = json.dumps({'hits': [{'objectID': '99', 'comment_text': 'We moved off it after a year.',
                                 'created_at': '2026-01-02T00:00:00.000Z', 'points': 3,
                                 'num_comments': 0}]})
    row = run(monkeypatch, capsys, body, ['search', '--on', 'hn', '--query', 'x'])['results'][0]
    assert row['url'] == 'https://news.ycombinator.com/item?id=99'


# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------

def test_an_atom_feed_parses_as_readily_as_rss(monkeypatch, capsys):
    row = run(monkeypatch, capsys, ATOM,
              ['search', '--on', 'feed', '--query', 'https://vendor.example/feed'])['results'][0]
    assert row['date'] == '2026-08-02'
    assert row['url'] == 'https://vendor.example/notes/3-1'
    assert row['kind'] == 'vendor_announcement'


@pytest.mark.parametrize('href,expected', [
    ('https://vendor.example/feed.xml', 'https://vendor.example/feed.xml'),
    ('/feed.xml', 'https://vendor.example/feed.xml'),
    ('feed.xml', 'https://vendor.example/blog/feed.xml'),
    ('../rss', 'https://vendor.example/rss'),
])
def test_a_relative_feed_link_resolves_against_the_page(monkeypatch, capsys, href, expected):
    """Only the root-relative form survived the old string surgery."""
    pages = ['<html><head><link rel="alternate" type="application/rss+xml" '
             'href="{}"></head></html>'.format(href), NEWS]
    monkeypatch.setattr(platforms, 'urlopen', lambda *a, **k: _Response(pages.pop(0)))
    platforms.main_with_args(['search', '--on', 'feed', '--query', 'https://vendor.example/blog/'])
    assert json.loads(capsys.readouterr().out)['endpoint'] == expected


def test_a_feed_is_discovered_from_a_site_page(monkeypatch, capsys):
    pages = ['<html><head><link rel="alternate" type="application/rss+xml" '
             'href="https://vendor.example/feed.xml"></head></html>', NEWS]
    monkeypatch.setattr(platforms, 'urlopen', lambda *a, **k: _Response(pages.pop(0)))
    platforms.main_with_args(['search', '--on', 'feed', '--query', 'https://vendor.example/'])
    payload = json.loads(capsys.readouterr().out)
    assert payload['endpoint'] == 'https://vendor.example/feed.xml'
    assert payload['results'][0]['date'] == '2026-06-25'


def test_a_site_with_no_feed_says_so(monkeypatch, capsys):
    monkeypatch.setattr(platforms, 'urlopen', lambda *a, **k: _Response('<html><body>no feed</body></html>'))
    with pytest.raises(SystemExit) as exit_info:
        platforms.main_with_args(['search', '--on', 'feed', '--query', 'https://vendor.example/'])
    assert exit_info.value.code == 1
    assert 'no RSS or Atom feed' in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Filters, limits, and the empty answer
# ---------------------------------------------------------------------------

def test_since_drops_anything_older(monkeypatch, capsys):
    payload = run(monkeypatch, capsys, NEWS,
                  ['search', '--on', 'news', '--query', 'x', '--since', '2026-03-01'])
    assert [r['date'] for r in payload['results']] == ['2026-06-25']


def test_limit_caps_the_rows(monkeypatch, capsys):
    payload = run(monkeypatch, capsys, NEWS, ['search', '--on', 'news', '--query', 'x', '--limit', '1'])
    assert len(payload['results']) == 1


def test_nothing_found_is_an_answer_not_an_error(monkeypatch, capsys):
    payload = run(monkeypatch, capsys, json.dumps({'hits': []}),
                  ['search', '--on', 'hn', '--query', 'nothing at all'])
    assert payload['results'] == []


def test_a_wayback_miss_returns_no_rows(monkeypatch, capsys):
    payload = run(monkeypatch, capsys, json.dumps({'archived_snapshots': {}}),
                  ['search', '--on', 'wayback', '--query', 'https://never-archived.example/'])
    assert payload['results'] == []


def test_an_http_error_exits_1_with_json_on_stderr(monkeypatch, capsys):
    from urllib.error import HTTPError

    def boom(*_a, **_k):
        raise HTTPError('https://api.github.com/x', 403, 'rate limited', {}, None)
    monkeypatch.setattr(platforms, 'urlopen', boom)
    with pytest.raises(SystemExit) as exit_info:
        platforms.main_with_args(['search', '--on', 'github', '--query', 'x'])
    assert exit_info.value.code == 1
    assert json.loads(capsys.readouterr().err)['status'] == 403


# ---------------------------------------------------------------------------
# Credentials: used if already present, never required, never stored
# ---------------------------------------------------------------------------

def test_a_github_token_is_sent_when_the_environment_has_one(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'ghp_example')
    assert platforms._github_headers()['Authorization'] == 'Bearer ghp_example'


def test_no_token_means_no_authorization_header(monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    assert 'Authorization' not in platforms._github_headers()


def test_reddit_is_not_offered_because_it_blocks_plain_requests():
    """Probed 2026-09-06: www and old both answer 403. That is the paid rung's job."""
    assert 'reddit' not in platforms.SEARCHERS


def test_the_out_file_is_written_when_asked(monkeypatch, capsys, tmp_path):
    out = tmp_path / 'hn.json'
    run(monkeypatch, capsys, HN, ['search', '--on', 'hn', '--query', 'x', '--out', str(out)])
    assert json.loads(out.read_text(encoding='utf-8'))['platform'] == 'hn'


def test_every_kind_this_emits_is_one_the_fetch_log_accepts():
    """The two scripts are a pipeline. A kind only one of them knows fails at
    the far end of a long run, which is the worst place to find it."""
    platforms._assert_vocabulary_agrees()


def test_an_archived_snapshot_does_not_invent_a_source_kind(monkeypatch, capsys):
    row = run(monkeypatch, capsys, WAYBACK,
              ['search', '--on', 'wayback', '--query', 'https://gone.example/'])['results'][0]
    assert row['kind'] == 'unknown'


def test_feed_mode_refuses_a_private_address(monkeypatch, capsys):
    """The one mode that takes an arbitrary URL is the one that needs the guard."""
    monkeypatch.setattr(fetch, '_is_public', lambda host: False)
    with pytest.raises(SystemExit) as exit_info:
        platforms.main_with_args(['search', '--on', 'feed', '--query', 'http://192.168.1.1/feed'])
    assert exit_info.value.code == 1
    assert 'private' in json.loads(capsys.readouterr().err)['error']
