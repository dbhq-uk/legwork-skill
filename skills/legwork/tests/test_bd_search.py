"""The paid rungs of both ladders.

Hermetic: subprocess.run is patched, so the Bright Data CLI is never invoked and
no request is ever billed. What these pin is the mapping from our flags to the
CLI's, which is the only part of this wrapper that can silently do the wrong
thing - a mode that quietly searches something other than what it says it does
is the failure that retired four modes here.
"""

import json
import subprocess

import pytest

import bd_search


class _Recorder:
    def __init__(self, *stdouts, returncode=0, stderr=''):
        self.calls = []
        self._stdouts = list(stdouts) or ['{}']
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        out = self._stdouts.pop(0) if len(self._stdouts) > 1 else self._stdouts[0]
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=out, stderr=self.stderr)


SERP_BODY = json.dumps({'organic': [
    {'rank': 1, 'title': 'Acme pricing', 'link': 'https://acme.example/pricing',
     'description': 'Team plan pricing', 'date': '2026-07-01'}]})

SHOPPING_BODY = json.dumps({'shopping': [
    {'name': 'Widget Pro', 'url': 'https://shop.example/widget', 'price': '£42.00',
     'source': 'Shop Example'}]})

DISCOVER_BODY = json.dumps({'results': [
    {'title': 'A UK write-up', 'url': 'https://uk.example/post', 'snippet': 'Detail',
     'date': '2026-08-01', 'content': '<p>Body text of the post.</p>'}]})


def run(monkeypatch, capsys, argv, recorder):
    monkeypatch.setattr(bd_search.subprocess, 'run', recorder)
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: '/usr/bin/brightdata')
    monkeypatch.setattr('sys.argv', ['bd_search.py'] + argv)
    bd_search.main()
    return json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------------------
# SERP: a second engine is the reason to pay at all
# ---------------------------------------------------------------------------

def test_engine_language_page_and_device_reach_the_cli(monkeypatch, capsys):
    recorder = _Recorder(SERP_BODY)
    run(monkeypatch, capsys, ['acme pricing', '-m', 'general', '--engine', 'bing',
                              '--language', 'en', '--page', '2', '--device', 'mobile',
                              '--country', 'gb'], recorder)
    cmd = recorder.calls[0]
    for flag, value in (('--engine', 'bing'), ('--language', 'en'), ('--page', '2'),
                        ('--device', 'mobile'), ('--country', 'gb'), ('--type', 'web')):
        assert cmd[cmd.index(flag) + 1] == value


def test_a_shopping_search_asks_for_the_shopping_vertical(monkeypatch, capsys):
    recorder = _Recorder(SHOPPING_BODY)
    payload = run(monkeypatch, capsys, ['widget', '-m', 'shopping'], recorder)
    assert recorder.calls[0][recorder.calls[0].index('--type') + 1] == 'shopping'
    row = payload['results'][0]
    assert row['url'] == 'https://shop.example/widget'
    assert '£42.00' in row['snippet'] and 'Shop Example' in row['snippet']


def test_a_news_search_asks_for_news(monkeypatch, capsys):
    recorder = _Recorder(SERP_BODY)
    run(monkeypatch, capsys, ['acme', '-m', 'news'], recorder)
    assert recorder.calls[0][recorder.calls[0].index('--type') + 1] == 'news'


@pytest.mark.parametrize('mode', sorted(bd_search.RETIRED_MODES))
def test_a_retired_vertical_fails_loudly_rather_than_searching_the_web(monkeypatch, capsys, mode):
    """Each of these ran a plain web search while claiming a vertical."""
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: '/usr/bin/brightdata')
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'x', '-m', mode])
    with pytest.raises(SystemExit) as exit_info:
        bd_search.main()
    assert exit_info.value.code == 1
    error = json.loads(capsys.readouterr().err)['error']
    assert 'was removed' in error and 'discover' in error


# ---------------------------------------------------------------------------
# Pages: cleaned, windowed, and written in the shape the log consumes
# ---------------------------------------------------------------------------

def test_a_scrape_is_cleaned_windowed_and_written_with_a_sidecar(monkeypatch, capsys, tmp_path):
    out = str(tmp_path / 'page.txt')
    body = ('<html><body><nav><a href="/">Home</a></nav><p>Team plan: 30 US dollars '
            'per user per month.</p></body></html>')
    payload = run(monkeypatch, capsys,
                  ['https://acme.example/pricing', '-m', 'scrape', '--out', out,
                   '--find', '30 US dollars'], _Recorder(body))
    assert 'Home' not in payload['content']
    assert '>>>30 US dollars<<<' in payload['find'][0]
    assert 'Team plan' in open(out, encoding='utf-8').read()
    sidecar = json.load(open(str(tmp_path / 'page.json'), encoding='utf-8'))
    assert sidecar['text_file'] == out and sidecar['verdict'] == 'ok'


def test_the_cap_applies_after_cleaning_not_before(monkeypatch, capsys, tmp_path):
    """Head-truncating raw markup returns the navigation and none of the page."""
    body = '<nav>' + ('<a href="/x">nav link</a>' * 200) + '</nav><p>The figure is 1,600 seats.</p>'
    payload = run(monkeypatch, capsys,
                  ['https://acme.example/x', '-m', 'scrape', '--max-chars', '200',
                   '--out', str(tmp_path / 'p.txt')], _Recorder(body))
    assert '1,600 seats' in payload['content']


def test_render_opens_gets_and_always_closes_the_session(monkeypatch, capsys, tmp_path):
    recorder = _Recorder('', '<p>' + 'Rendered body text. ' * 20 + '</p>', '')
    run(monkeypatch, capsys, ['https://app.example/', '-m', 'render',
                              '--out', str(tmp_path / 'p.txt')], recorder)
    verbs = [cmd[cmd.index('browser') + 3] if '--session' in cmd else cmd[2] for cmd in recorder.calls]
    assert verbs == ['open', 'get', 'close']
    assert all('--session' in cmd for cmd in recorder.calls)


def test_two_renders_do_not_share_a_browser_session(monkeypatch, capsys, tmp_path):
    recorder = _Recorder('', '<p>' + 'Body. ' * 40 + '</p>', '')
    run(monkeypatch, capsys, ['https://app.example/', '-m', 'render', '--session', 'run-a',
                              '--out', str(tmp_path / 'p.txt')], recorder)
    assert recorder.calls[0][recorder.calls[0].index('--session') + 1] == 'run-a'


# ---------------------------------------------------------------------------
# Discover: the rung for an angle two engines left thin
# ---------------------------------------------------------------------------

def test_discover_maps_every_flag_and_returns_content(monkeypatch, capsys):
    recorder = _Recorder(DISCOVER_BODY)
    payload = run(monkeypatch, capsys,
                  ['small UK practices email triage', '-m', 'discover',
                   '--intent', 'what a UK accountancy practice pays',
                   '--country', 'gb', '--language', 'en', '--since', '2026-01-01',
                   '--until', '2026-09-01', '--must-contain', 'practice,price',
                   '--with-content', '-c', '5'], recorder)
    cmd = recorder.calls[0]
    assert cmd[1] == 'discover'
    assert cmd[cmd.index('--intent') + 1] == 'what a UK accountancy practice pays'
    assert cmd[cmd.index('--start-date') + 1] == '2026-01-01'
    assert cmd[cmd.index('--end-date') + 1] == '2026-09-01'
    assert cmd[cmd.index('--filter-keywords') + 1] == 'practice,price'
    assert cmd[cmd.index('--num-results') + 1] == '5'
    assert '--include-content' in cmd
    assert payload['results'][0]['content'] == 'Body text of the post.'


def test_discover_without_an_intent_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: '/usr/bin/brightdata')
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'x', '-m', 'discover'])
    with pytest.raises(SystemExit):
        bd_search.main()
    assert '--intent' in json.loads(capsys.readouterr().err)['error']


# ---------------------------------------------------------------------------
# Pipelines: the last rung, billed per record
# ---------------------------------------------------------------------------

def test_reddit_still_maps_to_the_reddit_pipeline(monkeypatch, capsys):
    recorder = _Recorder(json.dumps([{'title': 'A thread'}]))
    payload = run(monkeypatch, capsys,
                  ['https://www.reddit.com/r/x/comments/1/', '-m', 'reddit'], recorder)
    assert recorder.calls[0][1:3] == ['pipelines', 'reddit_posts']
    assert payload['pipeline'] == 'reddit_posts'


def test_any_pipeline_can_be_named(monkeypatch, capsys):
    recorder = _Recorder(json.dumps([{'job': 'one'}]))
    run(monkeypatch, capsys,
        ['https://www.linkedin.com/jobs/x', '-m', 'pipeline',
         '--pipeline', 'linkedin_job_listings'], recorder)
    assert recorder.calls[0][1:3] == ['pipelines', 'linkedin_job_listings']


def test_pipeline_mode_without_a_name_says_where_to_find_one(monkeypatch, capsys):
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: '/usr/bin/brightdata')
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'https://x.example/', '-m', 'pipeline'])
    with pytest.raises(SystemExit):
        bd_search.main()
    assert 'pipelines list' in json.loads(capsys.readouterr().err)['error']


def test_reddit_mode_still_refuses_a_non_reddit_url(monkeypatch, capsys):
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: '/usr/bin/brightdata')
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'https://elsewhere.example/', '-m', 'reddit'])
    with pytest.raises(SystemExit):
        bd_search.main()
    assert 'reddit.com' in json.loads(capsys.readouterr().err)['error']


# ---------------------------------------------------------------------------
# Failure: the caller has to be able to tell "try the next rung" from
# "your credentials are bad"
# ---------------------------------------------------------------------------

def test_an_auth_failure_exits_2_with_the_login_hint(monkeypatch, capsys):
    recorder = _Recorder('', returncode=1, stderr='Invalid or expired API key')
    monkeypatch.setattr(bd_search.subprocess, 'run', recorder)
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: '/usr/bin/brightdata')
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'x', '-m', 'general'])
    with pytest.raises(SystemExit) as exit_info:
        bd_search.main()
    assert exit_info.value.code == 2
    assert 'brightdata login' in json.loads(capsys.readouterr().err)['error']


def test_an_ordinary_failure_exits_1_so_the_caller_drops_down_the_ladder(monkeypatch, capsys):
    recorder = _Recorder('', returncode=1, stderr='upstream timeout')
    monkeypatch.setattr(bd_search.subprocess, 'run', recorder)
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: '/usr/bin/brightdata')
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'x', '-m', 'general'])
    with pytest.raises(SystemExit) as exit_info:
        bd_search.main()
    assert exit_info.value.code == 1


def test_a_missing_cli_is_an_auth_class_failure_not_a_crash(monkeypatch, capsys):
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: None)
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'x', '-m', 'general'])
    with pytest.raises(SystemExit) as exit_info:
        bd_search.main()
    assert exit_info.value.code == 2
    assert 'npm install' in json.loads(capsys.readouterr().err)['error']
