"""The free rung of the page ladder.

Hermetic: urlopen and subprocess are mocked, no socket is ever opened. Every
function under test here is pure apart from `main`, which is driven through a
patched transport.
"""

import json
import os
import subprocess

import pytest

import fetch


PAGE = """<!doctype html>
<html><head>
<title>Pricing - Acme</title>
<meta property="og:title" content="Acme pricing">
<meta property="article:published_time" content="2026-07-01T09:00:00+01:00">
<link rel="canonical" href="https://acme.example/pricing">
<script>var tracking = {"price": 999};</script>
<style>.a{color:red}</style>
</head><body>
<nav><a href="/a">Home</a><a href="/b">About</a></nav>
<h1>Pricing</h1>
<p>Team plan: 30 US dollars per user per month, billed annually.</p>
<p>Enterprise is priced on application &amp; includes SSO.</p>
<footer><a href="/x">Legal</a></footer>
</body></html>
"""


# ---------------------------------------------------------------------------
# HTML to text
# ---------------------------------------------------------------------------

def test_furniture_is_dropped():
    text = fetch.html_to_text(PAGE)
    for absent in ('tracking', 'color:red', 'Home', 'About', 'Legal'):
        assert absent not in text
    assert 'Team plan: 30 US dollars per user per month, billed annually.' in text


def test_block_elements_keep_their_boundaries():
    """Two paragraphs must not run into one sentence when the tags are dropped."""
    text = fetch.html_to_text('<p>First sentence.</p><p>Second sentence.</p>')
    assert text.splitlines()[0] == 'First sentence.'
    assert text.splitlines()[-1] == 'Second sentence.'
    text = fetch.html_to_text('<li>One</li><li>Two</li>')
    assert 'OneTwo' not in text


def test_entities_decode():
    assert 'application & includes SSO' in fetch.html_to_text(PAGE)


def test_malformed_markup_still_yields_its_text():
    assert 'kept' in fetch.html_to_text('<p>kept<div><span>more')


# ---------------------------------------------------------------------------
# Metadata. A date that is absent stays absent: the gate asks whether a
# finding's age can be judged at all, and a guessed date would defeat it.
# ---------------------------------------------------------------------------

def test_the_title_prefers_open_graph():
    assert fetch.extract_meta(PAGE)['title'] == 'Acme pricing'


def test_the_title_falls_back_to_the_title_element():
    assert fetch.extract_meta('<html><head><title>Just this</title></head></html>')['title'] == 'Just this'


@pytest.mark.parametrize('markup,expected', [
    ('<meta property="article:published_time" content="2026-07-01T09:00:00Z">', '2026-07-01'),
    ('<meta name="date" content="1 July 2026">', '2026-07-01'),
    ('<script type="application/ld+json">{"datePublished":"2026-07-01"}</script>', '2026-07-01'),
    ('<time datetime="2026-07-01T00:00:00">1 July</time>', '2026-07-01'),
    ('<meta name="parsely-pub-date" content="July 1, 2026">', '2026-07-01'),
])
def test_every_date_form_a_page_uses_is_found(markup, expected):
    assert fetch.extract_meta(markup)['date'] == expected


def test_last_modified_is_never_treated_as_a_publication_date():
    """Measured live on 2026-09-06: a dynamically rendered vendor page returned
    today in that header. Using it would have stamped a page of unknown age as
    published today, which is worse than recording no date at all - the gate
    asks whether a finding's age can be judged, and a false date answers yes."""
    meta = fetch.extract_meta('<html></html>', {'Last-Modified': 'Wed, 01 Jul 2026 09:00:00 GMT'})
    assert meta['date'] == ''
    assert meta['last_modified'] == '2026-07-01'


def test_a_real_publication_date_still_wins_over_the_header():
    meta = fetch.extract_meta('<meta name="date" content="1 July 2026">',
                              {'Last-Modified': 'Sat, 06 Sep 2026 00:00:00 GMT'})
    assert meta['date'] == '2026-07-01'


def test_a_page_with_no_date_yields_no_date():
    assert fetch.extract_meta('<html><body>No dates here.</body></html>')['date'] == ''


def test_the_canonical_url_is_read_when_present():
    assert fetch.extract_meta(PAGE)['canonical'] == 'https://acme.example/pricing'


# ---------------------------------------------------------------------------
# Blocked and shell detection - the whole point of the exit codes
# ---------------------------------------------------------------------------

def test_a_403_is_blocked():
    verdict, reason = fetch.classify('x' * 900, 403)
    assert verdict == 'blocked' and '403' in reason


def test_a_challenge_page_is_blocked_even_with_a_200():
    verdict, reason = fetch.classify('Just a moment... ' + 'x' * 900, 200)
    assert verdict == 'blocked' and 'challenge' in reason


def test_a_page_with_almost_no_text_is_a_shell():
    verdict, reason = fetch.classify('Loading.', 200)
    assert verdict == 'shell' and 'characters' in reason


def test_a_link_list_is_a_shell():
    links = ''.join('<li><a href="/{0}">Item number {0} in the index</a></li>'.format(i) for i in range(60))
    markup = '<html><body><ul>' + links + '</ul><p>Short intro.</p></body></html>'
    verdict, reason = fetch.classify(fetch.html_to_text(markup), 200, markup)
    assert verdict == 'shell' and 'links' in reason


def test_a_real_page_is_ok():
    body = fetch.html_to_text(PAGE) + ' ' + 'padding sentence. ' * 40
    assert fetch.classify(body, 200, PAGE) == ('ok', '')


def test_link_density_is_low_on_a_prose_page():
    assert fetch.link_density('<p>' + 'words ' * 200 + '<a href="/x">one link</a></p>') < 0.1


# ---------------------------------------------------------------------------
# --find: how a long page yields its sentence without twenty thousand
# characters of context
# ---------------------------------------------------------------------------

def test_find_marks_the_match_and_gives_context():
    text = 'noise ' * 100 + 'Team plan: 30 US dollars per user. ' + 'noise ' * 100
    passage = fetch.find_windows(text, ['30 US dollars'], window=40)[0]
    assert '>>>30 US dollars<<<' in passage
    assert len(passage) < 200


def test_find_caps_the_number_of_hits():
    assert len(fetch.find_windows('hit ' * 50, ['hit'], window=5, max_hits=3)) == 3


def test_find_is_case_insensitive_and_returns_nothing_when_absent():
    assert fetch.find_windows('The Price is right', ['price'])
    assert fetch.find_windows('nothing here', ['price']) == []


# ---------------------------------------------------------------------------
# End to end, transport patched
# ---------------------------------------------------------------------------

class _Response:
    def __init__(self, body, headers, status=200, url='https://acme.example/pricing'):
        self._body = body
        self.headers = headers
        self.status = status
        self._url = url

    def read(self, *_):
        return self._body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _run_main(monkeypatch, capsys, argv, response):
    monkeypatch.setattr(fetch, 'urlopen', lambda *a, **k: response)
    monkeypatch.setattr('sys.argv', ['fetch.py'] + argv)
    with pytest.raises(SystemExit) as exit_info:
        fetch.main()
    return exit_info.value.code, capsys.readouterr()


def test_a_good_page_is_written_with_its_sidecar(monkeypatch, capsys, tmp_path):
    out = str(tmp_path / 'page.txt')
    body = (PAGE + '<p>' + 'padding sentence. ' * 60 + '</p>').encode('utf-8')
    monkeypatch.setattr(fetch, 'urlopen',
                        lambda *a, **k: _Response(body, {'Content-Type': 'text/html; charset=utf-8'}))
    monkeypatch.setattr('sys.argv', ['fetch.py', 'https://acme.example/pricing', '--out', out,
                                     '--find', '30 US dollars'])
    fetch.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload['verdict'] == 'ok'
    assert payload['date'] == '2026-07-01'
    assert payload['title'] == 'Acme pricing'
    assert payload['numbers'] >= 1
    assert '>>>30 US dollars<<<' in payload['find'][0]
    assert 'Team plan: 30 US dollars' in open(out, encoding='utf-8').read()
    assert json.load(open(os.path.splitext(out)[0] + '.json'))['url'] == 'https://acme.example/pricing'


def test_a_403_exits_3_and_names_the_next_rung(monkeypatch, capsys, tmp_path):
    code, captured = _run_main(
        monkeypatch, capsys,
        ['https://acme.example/pricing', '--out', str(tmp_path / 'p.txt')],
        _Response(b'<html><body>Forbidden</body></html>', {'Content-Type': 'text/html'}, status=403))
    payload = json.loads(captured.err)
    assert code == 3
    assert payload['verdict'] == 'blocked'
    assert 'scrape' in payload['next']


def test_a_client_rendered_shell_exits_3_and_points_at_render(monkeypatch, capsys, tmp_path):
    code, captured = _run_main(
        monkeypatch, capsys,
        ['https://acme.example/app', '--out', str(tmp_path / 'p.txt')],
        _Response(b'<html><body><div id="root"></div></body></html>', {'Content-Type': 'text/html'}))
    payload = json.loads(captured.err)
    assert code == 3
    assert payload['verdict'] == 'shell'
    assert 'render' in payload['next']


def test_a_transport_failure_exits_1(monkeypatch, capsys, tmp_path):
    def boom(*_a, **_k):
        raise OSError('connection reset')
    monkeypatch.setattr(fetch, 'urlopen', boom)
    monkeypatch.setattr('sys.argv', ['fetch.py', 'https://acme.example/x'])
    with pytest.raises(SystemExit) as exit_info:
        fetch.main()
    assert exit_info.value.code == 1
    assert 'connection reset' in json.loads(capsys.readouterr().err)['reason']


def test_a_non_http_url_is_refused(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['fetch.py', 'file:///etc/passwd'])
    with pytest.raises(SystemExit) as exit_info:
        fetch.main()
    assert exit_info.value.code == 1


def test_a_pdf_without_pdftotext_exits_4(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(fetch.shutil, 'which', lambda _: None)
    code, captured = _run_main(
        monkeypatch, capsys, ['https://acme.example/filing.pdf'],
        _Response(b'%PDF-1.4 ...', {'Content-Type': 'application/pdf'}))
    assert code == 4
    assert 'pdftotext' in json.loads(captured.err)['reason']


def test_a_pdf_with_pdftotext_is_read(monkeypatch, capsys, tmp_path):
    out = str(tmp_path / 'filing.txt')
    monkeypatch.setattr(fetch.shutil, 'which', lambda _: '/usr/bin/pdftotext')
    monkeypatch.setattr(fetch.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout='The company reported 1,600 active seats. ' + 'padding. ' * 60, stderr=''))
    monkeypatch.setattr(fetch, 'urlopen',
                        lambda *a, **k: _Response(b'%PDF-1.4', {'Content-Type': 'application/pdf'}))
    monkeypatch.setattr('sys.argv', ['fetch.py', 'https://acme.example/filing.pdf', '--out', out])
    fetch.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload['verdict'] == 'ok'
    assert '1,600 active seats' in open(out, encoding='utf-8').read()


def test_gzip_bodies_are_decompressed(monkeypatch, capsys, tmp_path):
    import gzip as gziplib
    out = str(tmp_path / 'p.txt')
    body = gziplib.compress((PAGE + '<p>' + 'padding sentence. ' * 60 + '</p>').encode('utf-8'))
    monkeypatch.setattr(fetch, 'urlopen', lambda *a, **k: _Response(
        body, {'Content-Type': 'text/html', 'Content-Encoding': 'gzip'}))
    monkeypatch.setattr('sys.argv', ['fetch.py', 'https://acme.example/pricing', '--out', out])
    fetch.main()
    assert 'Team plan' in open(out, encoding='utf-8').read()


def test_the_default_out_path_is_scratch_not_the_run_folder():
    path = fetch.default_out_path('https://acme.example/pricing')
    assert path.endswith('.txt') and '/legwork/' in path
    assert path.startswith(os.environ.get('TMPDIR', '/tmp'))
