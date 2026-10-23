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


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    """The render settle delay is real time; a test must not spend it."""
    monkeypatch.setattr(bd_search.time, 'sleep', lambda _s: None)


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


def test_a_query_starting_with_a_dash_reaches_the_cli_as_the_query(monkeypatch, capsys):
    recorder = _Recorder(SERP_BODY)
    run(monkeypatch, capsys, ['--engine', 'google', '--', '-crypto bank sandbox UK'], recorder)
    cmd = recorder.calls[0]
    assert cmd[-2:] == ['--', '-crypto bank sandbox UK']
    assert cmd.index('--type') < cmd.index('--')


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
            'per user per month. ' + 'Further pricing detail. ' * 30 + '</p></body></html>')
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
    body = ('<nav>' + ('<a href="/x">nav link</a>' * 200) + '</nav><p>The figure is 1,600 seats. '
            + 'Supporting sentence about the plan. ' * 30 + '</p>')
    payload = run(monkeypatch, capsys,
                  ['https://acme.example/x', '-m', 'scrape', '--max-chars', '200',
                   '--out', str(tmp_path / 'p.txt')], _Recorder(body))
    assert '1,600 seats' in payload['content']


def test_render_opens_gets_html_and_always_closes_the_session(monkeypatch, capsys, tmp_path):
    """The full argv, not just the verb.

    The earlier version of this test asserted the verb sequence only, and
    passed while `render` sent a bare `browser get` - which is a command group,
    not a leaf, so the CLI printed its own usage and exited 0 and the usage text
    was taken for the page. An eval arm found that, not this test.
    """
    recorder = _Recorder('', '<p>' + 'Rendered body text. ' * 40 + '</p>', '')
    run(monkeypatch, capsys, ['https://app.example/', '-m', 'render',
                              '--out', str(tmp_path / 'p.txt')], recorder)
    tails = [cmd[cmd.index('--session') + 2:] for cmd in recorder.calls]
    assert tails == [['open', 'https://app.example/'], ['get', 'html'], ['close']]


def test_usage_text_is_never_mistaken_for_a_page(monkeypatch, capsys, tmp_path):
    """A CLI that answers a bad invocation with its own help and exit 0 must not
    end up quoted as evidence."""
    usage = 'Usage: brightdata browser get [options] [command]\n\nGet page content\n'
    monkeypatch.setattr(bd_search.subprocess, 'run', _Recorder('', usage, ''))
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: '/usr/bin/brightdata')
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'https://app.example/', '-m', 'render',
                                     '--out', str(tmp_path / 'p.txt')])
    with pytest.raises(SystemExit) as exit_info:
        bd_search.main()
    assert exit_info.value.code == 1
    assert 'usage text' in json.loads(capsys.readouterr().err)['error']


def test_two_renders_do_not_share_a_browser_session(monkeypatch, capsys, tmp_path):
    recorder = _Recorder('', '<p>' + 'Body of the rendered page. ' * 40 + '</p>', '')
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
# Reddit: scrape a single thread first, fall back to the slow pipeline
# ---------------------------------------------------------------------------

THREAD_URL = 'https://www.reddit.com/r/example/comments/abc123/a_made_up_thread_title/'
SLUGLESS_URL = 'https://www.reddit.com/r/example/comments/abc123/'
LISTING_URL = 'https://www.reddit.com/r/example/new/'
PIPELINE_BODY = json.dumps([{'title': 'A thread', 'num_comments': 3}])

# Three comments: a root, a reply to it, and a second root. Tiny and invented.
THREE_COMMENTS = [
    ('t1_aaa', None, 'alice', 5, 0, '<p>First root comment.</p><p>Second paragraph.</p>'),
    ('t1_bbb', 't1_aaa', 'bob', 2, 1, '<p>A reply to the first.</p>'),
    ('t1_ccc', None, 'carol', 1, 0, '<p>Another root.</p>'),
]


def thread_html(reported=3, comments=THREE_COMMENTS, pad=3000):
    """A small synthetic page in the shape the Unlocker returns for a thread.

    Replies sit inside their parent's element, as on the real page. The filler
    only lifts the body past the empty-page threshold.
    """
    count = '' if reported is None else ' comment-count="{}"'.format(reported)
    out = ['<html><body><div>', '<!-- ' + 'x' * pad + ' -->',
           '<shreddit-post id="t3_abc123" post-title="A made up thread title" '
           'author="dave" score="42"{} created-timestamp="2026-10-01T10:00:00.000000+0000" '
           'subreddit-prefixed-name="r/example">'.format(count),
           '<shreddit-post-text-body slot="text-body"><div slot="text-body">'
           '<div class="md"><p>The post body.</p></div></div></shreddit-post-text-body>',
           '</shreddit-post>']
    open_depths = []
    for thing, parent, author, score, depth, body in comments:
        while open_depths and open_depths[-1] >= depth:
            out.append('</shreddit-comment>')
            open_depths.pop()
        parent_attr = ' parentId="{}"'.format(parent) if parent else ''
        out.append('<shreddit-comment author="{}" thingId="{}" depth="{}"{} score="{}">'
                   '<details><summary><faceplate-tracker><a href="/u/{}">{}</a></faceplate-tracker>'
                   '</summary><div class="md" slot="comment">{}</div></details>'
                   .format(author, thing, depth, parent_attr, score, author, author, body))
        open_depths.append(depth)
    out.extend('</shreddit-comment>' for _ in open_depths)
    out.append('</div></body></html>')
    return '\n'.join(out)


def run_reddit(monkeypatch, capsys, tmp_path, url, *bodies, extra=()):
    recorder = _Recorder(*bodies)
    payload = run(monkeypatch, capsys,
                  [url, '-m', 'reddit', '--out', str(tmp_path / 'thread.txt'), *extra], recorder)
    return recorder, payload


def run_reddit_failing(monkeypatch, capsys, url, *bodies, extra=()):
    recorder = _Recorder(*bodies)
    monkeypatch.setattr(bd_search.subprocess, 'run', recorder)
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: '/usr/bin/brightdata')
    monkeypatch.setattr('sys.argv', ['bd_search.py', url, '-m', 'reddit', *extra])
    with pytest.raises(SystemExit) as exit_info:
        bd_search.main()
    return recorder, exit_info.value.code, json.loads(capsys.readouterr().err)['error']


def test_a_full_thread_is_read_by_the_scrape_alone(monkeypatch, capsys, tmp_path):
    recorder, payload = run_reddit(monkeypatch, capsys, tmp_path, THREAD_URL, thread_html())
    assert len(recorder.calls) == 1
    assert recorder.calls[0][1:] == ['scrape', THREAD_URL, '-f', 'html']
    assert payload['route'] == 'scrape'
    assert (payload['recovered'], payload['reported'], payload['complete']) == (3, 3, True)
    assert 'pipeline' not in payload
    assert payload['log_via'] == 'brightdata'
    assert payload['verdict'] == 'ok'
    body = json.loads(payload['content'])
    assert body['post']['title'] == 'A made up thread title'
    assert (body['post']['author'], body['post']['score']) == ('dave', 42)
    assert body['post']['text'] == 'The post body.'
    first, reply, other = body['comments']
    assert (first['author'], first['score'], first['depth'], first['parent']) == ('alice', 5, 0, None)
    assert first['text'] == 'First root comment.\nSecond paragraph.'
    # The reply's text is its own, and it names its parent.
    assert (reply['author'], reply['depth'], reply['parent'], reply['text']) == (
        'bob', 1, 't1_aaa', 'A reply to the first.')
    assert (other['author'], other['depth'], other['parent']) == ('carol', 0, None)


def test_the_scrape_route_writes_the_text_and_a_sidecar(monkeypatch, capsys, tmp_path):
    _, payload = run_reddit(monkeypatch, capsys, tmp_path, THREAD_URL, thread_html())
    text = (tmp_path / 'thread.txt').read_text(encoding='utf-8')
    assert 'recovered 3 of reported 3' in text
    assert 'A reply to the first.' in text
    sidecar = json.loads((tmp_path / 'thread.json').read_text(encoding='utf-8'))
    assert sidecar['route'] == 'scrape' and sidecar['text_file'] == payload['text_file']
    assert 'content' not in sidecar


def test_fewer_comments_than_reported_falls_back_to_the_pipeline(monkeypatch, capsys, tmp_path):
    recorder, payload = run_reddit(monkeypatch, capsys, tmp_path, THREAD_URL,
                                   thread_html(reported=5), PIPELINE_BODY)
    assert [c[1] for c in recorder.calls] == ['scrape', 'pipelines']
    assert recorder.calls[1][2] == 'reddit_posts'
    assert payload['route'] == 'pipeline'
    assert payload['pipeline'] == 'reddit_posts'
    assert '3 of 5' in payload['fallback_reason']
    assert (payload['scrape_recovered'], payload['scrape_reported']) == (3, 5)


def test_a_post_that_does_not_report_a_count_cannot_be_checked_so_it_falls_back(monkeypatch, capsys, tmp_path):
    _, payload = run_reddit(monkeypatch, capsys, tmp_path, THREAD_URL,
                            thread_html(reported=None), PIPELINE_BODY)
    assert payload['route'] == 'pipeline'
    assert 'does not say' in payload['fallback_reason']


@pytest.mark.parametrize('page, why', [
    ('', 'only 0 bytes'),
    ('<html>' + 'blocked ' * 15 + '</html>', 'bytes'),
    ('<html><body>' + 'a page with no post ' * 200 + '</body></html>', 'no post'),
])
def test_an_empty_or_blocked_page_falls_back_to_the_pipeline(monkeypatch, capsys, tmp_path, page, why):
    recorder, payload = run_reddit(monkeypatch, capsys, tmp_path, THREAD_URL, page, PIPELINE_BODY)
    assert [c[1] for c in recorder.calls] == ['scrape', 'pipelines']
    assert payload['route'] == 'pipeline'
    assert why in payload['fallback_reason']
    assert 'scrape_recovered' not in payload


def test_a_scrape_that_errors_falls_back_to_the_pipeline(monkeypatch, capsys):
    def flaky(cmd, **kwargs):
        if cmd[1] == 'scrape':
            return subprocess.CompletedProcess(cmd, 1, stdout='', stderr='upstream timeout')
        return subprocess.CompletedProcess(cmd, 0, stdout=PIPELINE_BODY, stderr='')

    payload = run(monkeypatch, capsys, [THREAD_URL, '-m', 'reddit'], flaky)
    assert payload['route'] == 'pipeline' and 'upstream timeout' in payload['fallback_reason']


def test_an_auth_failure_on_the_scrape_stops_the_run_rather_than_falling_back(monkeypatch, capsys):
    bad = _Recorder('', returncode=1, stderr='Invalid or expired API key')
    monkeypatch.setattr(bd_search.subprocess, 'run', bad)
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: '/usr/bin/brightdata')
    monkeypatch.setattr('sys.argv', ['bd_search.py', THREAD_URL, '-m', 'reddit'])
    with pytest.raises(SystemExit) as exit_info:
        bd_search.main()
    assert exit_info.value.code == 2
    assert len(bad.calls) == 1


def test_a_thread_url_without_its_slug_goes_to_the_pipeline_and_says_why(monkeypatch, capsys, tmp_path):
    recorder, payload = run_reddit(monkeypatch, capsys, tmp_path, SLUGLESS_URL, PIPELINE_BODY)
    assert [c[1] for c in recorder.calls] == ['pipelines']
    assert payload['route'] == 'pipeline'
    assert 'slug' in payload['route_reason']


def test_a_subreddit_listing_always_uses_the_pipeline(monkeypatch, capsys, tmp_path):
    recorder, payload = run_reddit(monkeypatch, capsys, tmp_path, LISTING_URL, PIPELINE_BODY)
    assert [c[1] for c in recorder.calls] == ['pipelines']
    assert payload['route'] == 'pipeline'
    assert 'listing' in payload['route_reason']


def test_route_pipeline_skips_the_scrape_even_for_a_full_thread(monkeypatch, capsys, tmp_path):
    recorder, payload = run_reddit(monkeypatch, capsys, tmp_path, THREAD_URL, PIPELINE_BODY,
                                   extra=('--route', 'pipeline'))
    assert [c[1] for c in recorder.calls] == ['pipelines']
    assert payload['route'] == 'pipeline' and '--route pipeline' in payload['route_reason']


def test_route_scrape_does_not_fall_back_and_marks_a_partial_thread(monkeypatch, capsys, tmp_path):
    recorder, payload = run_reddit(monkeypatch, capsys, tmp_path, THREAD_URL, thread_html(reported=5),
                                   extra=('--route', 'scrape'))
    assert [c[1] for c in recorder.calls] == ['scrape']
    assert payload['route'] == 'scrape' and payload['complete'] is False
    assert (payload['recovered'], payload['reported']) == (3, 5)
    assert 'partial' in payload['note']


def test_route_scrape_on_an_empty_page_fails_rather_than_falling_back(monkeypatch, capsys):
    recorder, code, error = run_reddit_failing(monkeypatch, capsys, THREAD_URL, 'tiny',
                                               extra=('--route', 'scrape'))
    assert code == 1 and [c[1] for c in recorder.calls] == ['scrape']
    assert '--route scrape' in error


def test_route_scrape_is_refused_for_a_listing(monkeypatch, capsys):
    recorder, code, error = run_reddit_failing(monkeypatch, capsys, LISTING_URL, 'x',
                                               extra=('--route', 'scrape'))
    assert code == 1 and recorder.calls == []
    assert 'single thread' in error


def test_route_scrape_still_tries_a_slugless_url_when_forced(monkeypatch, capsys, tmp_path):
    recorder, payload = run_reddit(monkeypatch, capsys, tmp_path, SLUGLESS_URL, thread_html(),
                                   extra=('--route', 'scrape'))
    assert [c[1] for c in recorder.calls] == ['scrape'] and payload['route'] == 'scrape'


def test_route_applies_to_reddit_mode_only(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'acme', '-m', 'general', '--route', 'scrape'])
    with pytest.raises(SystemExit):
        bd_search.main()
    assert 'reddit mode only' in json.loads(capsys.readouterr().err)['error']


def test_a_long_thread_is_cut_by_whole_comments_so_the_json_stays_valid(monkeypatch, capsys, tmp_path):
    many = [('t1_{:03d}'.format(i), None, 'user{}'.format(i), i, 0, '<p>{}</p>'.format('word ' * 40))
            for i in range(30)]
    _, payload = run_reddit(monkeypatch, capsys, tmp_path, THREAD_URL,
                            thread_html(reported=30, comments=many), extra=('--max-chars', '2000'))
    shown = json.loads(payload['content'])
    assert payload['recovered'] == payload['reported'] == 30 and payload['complete'] is True
    assert 0 < payload['returned_in_content'] == len(shown['comments']) < 30
    assert 'user29' in (tmp_path / 'thread.txt').read_text(encoding='utf-8')


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


def test_a_paid_fetch_that_returns_a_challenge_page_is_not_called_a_page(monkeypatch, capsys, tmp_path):
    """Paying for a page does not mean getting one: the Unlocker returns
    challenge pages with a clean exit code."""
    challenge = '<html><body><h1>Just a moment...</h1><p>' + 'Checking your browser. ' * 40 + '</p></body></html>'
    monkeypatch.setattr(bd_search.subprocess, 'run', _Recorder(challenge))
    monkeypatch.setattr(bd_search.shutil, 'which', lambda _: '/usr/bin/brightdata')
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'https://acme.example/x', '-m', 'scrape',
                                     '--out', str(tmp_path / 'p.txt')])
    with pytest.raises(SystemExit) as exit_info:
        bd_search.main()
    assert exit_info.value.code == 3
    assert json.loads(capsys.readouterr().out)['verdict'] == 'blocked'


def test_a_paid_fetch_of_a_real_page_still_succeeds(monkeypatch, capsys, tmp_path):
    body = '<html><body><p>' + 'Team plan: 30 US dollars per user per month. ' * 20 + '</p></body></html>'
    payload = run(monkeypatch, capsys, ['https://acme.example/pricing', '-m', 'scrape',
                                        '--out', str(tmp_path / 'p.txt')], _Recorder(body))
    assert payload['verdict'] == 'ok'


def test_render_lets_a_single_page_app_settle_before_reading_it(monkeypatch, capsys, tmp_path):
    waited = []
    monkeypatch.setattr(bd_search.time, 'sleep', lambda seconds: waited.append(seconds))
    run(monkeypatch, capsys,
        ['https://app.example/', '-m', 'render', '--settle', '2',
         '--out', str(tmp_path / 'p.txt')],
        _Recorder('', '<p>' + 'Rendered body text. ' * 40 + '</p>', ''))
    assert waited == [2.0]


# ---------------------------------------------------------------------------
# Engine fixes, 17 Oct 2026: Yandex never returned JSON through the CLI, and
# Bing without a country came back in a Spanish locale.
# ---------------------------------------------------------------------------

def test_yandex_is_refused(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'q', '-m', 'general', '--engine', 'yandex'])
    with pytest.raises(SystemExit) as exc:
        bd_search.main()
    assert exc.value.code == 2  # argparse rejects an invalid choice


def test_bing_with_no_country_gets_gb_and_en(monkeypatch, capsys):
    monkeypatch.delenv('BD_COUNTRY', raising=False)
    monkeypatch.delenv('BD_LANGUAGE', raising=False)
    recorder = _Recorder(SERP_BODY)
    run(monkeypatch, capsys, ['acme pricing', '-m', 'general', '--engine', 'bing'], recorder)
    cmd = recorder.calls[0]
    assert cmd[cmd.index('--country') + 1] == 'gb'
    assert cmd[cmd.index('--language') + 1] == 'en'


def test_bing_keeps_a_country_it_was_given(monkeypatch, capsys):
    recorder = _Recorder(SERP_BODY)
    run(monkeypatch, capsys, ['acme pricing', '-m', 'general', '--engine', 'bing',
                              '--country', 'us', '--language', 'fr'], recorder)
    cmd = recorder.calls[0]
    assert cmd[cmd.index('--country') + 1] == 'us'
    assert cmd[cmd.index('--language') + 1] == 'fr'


def test_google_with_no_country_sends_none(monkeypatch, capsys):
    monkeypatch.delenv('BD_COUNTRY', raising=False)
    monkeypatch.delenv('BD_LANGUAGE', raising=False)
    recorder = _Recorder(SERP_BODY)
    run(monkeypatch, capsys, ['acme pricing', '-m', 'general', '--engine', 'google'], recorder)
    assert '--country' not in recorder.calls[0]
