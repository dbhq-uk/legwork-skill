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


@pytest.fixture(autouse=True)
def _resolvable(monkeypatch):
    """Every host in these tests resolves to a public address.

    The SSRF guard resolves the hostname before connecting, and a test must
    never touch DNS. The guard itself is tested below with getaddrinfo patched.
    """
    monkeypatch.setattr(fetch, '_is_public', lambda host: True)


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


# ---------------------------------------------------------------------------
# Where this is allowed to connect
#
# The URL comes off the open web, from a search result or a link on a page
# somebody else controls. It is not a URL the user vouched for, so it does not
# get to name an address on this machine's network.
# ---------------------------------------------------------------------------

def _resolves_to(monkeypatch, address):
    monkeypatch.setattr(fetch.socket, 'getaddrinfo',
                        lambda *a, **k: [(2, 1, 6, '', (address, 0))])


@pytest.mark.parametrize('address', [
    '127.0.0.1',        # loopback
    '169.254.169.254',  # cloud instance metadata
    '10.0.0.5',         # RFC1918
    '192.168.1.1',
    '172.16.4.4',
    '0.0.0.0',
    '::1',
    'fd00::1',          # unique local
])
def test_a_host_resolving_somewhere_private_is_refused(monkeypatch, address):
    monkeypatch.undo()
    _resolves_to(monkeypatch, address)
    assert fetch._is_public('anything.example') is False
    with pytest.raises(fetch.BlockedAddress):
        fetch._check_target('https://anything.example/')


def test_a_public_address_is_allowed(monkeypatch):
    monkeypatch.undo()
    _resolves_to(monkeypatch, '93.184.216.34')
    assert fetch._is_public('example.com') is True


def test_one_private_record_among_public_ones_still_refuses(monkeypatch):
    """A name with a public and a loopback record must not be dialled."""
    monkeypatch.undo()
    monkeypatch.setattr(fetch.socket, 'getaddrinfo',
                        lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 0)),
                                         (2, 1, 6, '', ('127.0.0.1', 0))])
    assert fetch._is_public('split.example') is False


def test_a_name_that_does_not_resolve_is_refused(monkeypatch):
    monkeypatch.undo()

    def boom(*_a, **_k):
        raise fetch.socket.gaierror('no such host')
    monkeypatch.setattr(fetch.socket, 'getaddrinfo', boom)
    assert fetch._is_public('nope.invalid') is False


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'ftp://x.example/f', 'gopher://x.example/'])
def test_only_http_and_https_are_dialled(url):
    with pytest.raises(fetch.BlockedAddress):
        fetch._check_target(url)


def test_a_redirect_to_a_private_address_is_refused(monkeypatch):
    """Validating only the URL the caller typed is no protection: a public page
    is free to answer 302 to the instance metadata service."""
    monkeypatch.undo()
    _resolves_to(monkeypatch, '169.254.169.254')
    handler = fetch._ValidatingRedirectHandler()
    with pytest.raises(fetch.BlockedAddress):
        handler.redirect_request(None, None, 302, 'Found', {}, 'http://169.254.169.254/latest/meta-data/')


# ---------------------------------------------------------------------------
# Bounded decompression
# ---------------------------------------------------------------------------

def test_a_compression_bomb_is_truncated_not_expanded():
    """The byte cap on the wire covers the compressed body, which is no cap at
    all: this payload is a few kilobytes and expands to 200 MB."""
    import gzip as gziplib
    bomb = gziplib.compress(b'A' * (200 * 1024 * 1024))
    assert len(bomb) < 1024 * 1024
    out = fetch._decompress(bomb, 'gzip')
    assert len(out) <= fetch.MAX_DECOMPRESSED


def test_ordinary_gzip_still_round_trips():
    import gzip as gziplib
    assert fetch._decompress(gziplib.compress(b'hello page'), 'gzip') == b'hello page'


def test_a_corrupt_body_is_passed_through_rather_than_crashing():
    assert fetch._decompress(b'not actually gzip', 'gzip') == b'not actually gzip'


# ---------------------------------------------------------------------------
# Status handling. A 404 with a long branded body was being written as an
# opened source, because only the blocking codes were checked and the body
# cleared the length test.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('status,expected', [
    (200, 'ok'), (203, 'ok'),
    (404, 'missing'), (410, 'missing'),
    (403, 'blocked'), (429, 'blocked'), (503, 'blocked'),
    (500, 'blocked'), (502, 'blocked'), (302, 'blocked'),
])
def test_status_decides_before_the_body_does(status, expected):
    long_error_page = 'Sorry, we could not find that page. ' * 30
    assert fetch.classify(long_error_page, status)[0] == expected


def test_a_missing_page_exits_3_and_does_not_pretend_to_be_a_source(monkeypatch, capsys, tmp_path):
    code, captured = _run_main(
        monkeypatch, capsys,
        ['https://acme.example/gone', '--out', str(tmp_path / 'p.txt')],
        _Response(('<html><body><p>' + 'Page not found. ' * 40 + '</p></body></html>').encode('utf-8'),
                  {'Content-Type': 'text/html'}, status=404))
    payload = json.loads(captured.err)
    assert code == 3
    assert payload['verdict'] == 'missing'


# ---------------------------------------------------------------------------
# A failed fetch still leaves a sidecar, because the skill's own instruction is
# to log the failure before falling back, and that is done with --from-fetch
# ---------------------------------------------------------------------------

def test_a_blocked_fetch_still_writes_its_sidecar(monkeypatch, capsys, tmp_path):
    out = str(tmp_path / 'p.txt')
    _run_main(monkeypatch, capsys, ['https://acme.example/x', '--out', out],
              _Response(b'<html><body>Forbidden</body></html>', {'Content-Type': 'text/html'}, status=403))
    sidecar = json.load(open(os.path.splitext(out)[0] + '.json', encoding='utf-8'))
    assert sidecar['verdict'] == 'blocked'
    assert sidecar['url'] == 'https://acme.example/x'


def test_scratch_is_namespaced_per_run_so_yesterdays_page_is_never_read_back(monkeypatch):
    monkeypatch.setenv('LEGWORK_RUN_ID', 'run-a')
    first = fetch.default_out_path('https://acme.example/pricing')
    monkeypatch.setenv('LEGWORK_RUN_ID', 'run-b')
    second = fetch.default_out_path('https://acme.example/pricing')
    assert first != second
    assert first.endswith(os.path.basename(second))


def test_a_refused_address_exits_5_and_tells_the_caller_not_to_escalate(monkeypatch, capsys):
    """Distinct from a block. A blocked page means try the next rung; a refused
    address means there is no rung - escalating to a paid scrape would be the
    wrong answer and would spend money reaching it."""
    monkeypatch.setattr(fetch, '_is_public', lambda host: False)
    monkeypatch.setattr('sys.argv', ['fetch.py', 'http://169.254.169.254/latest/meta-data/'])
    with pytest.raises(SystemExit) as exit_info:
        fetch.main()
    assert exit_info.value.code == 5
    payload = json.loads(capsys.readouterr().err)
    assert payload['verdict'] == 'refused'
    assert 'do not fetch' in payload['next']
