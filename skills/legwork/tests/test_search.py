"""search.py: one angle asked many ways across Bright Data and Exa.

Hermetic. subprocess.Popen, os.killpg and urlopen are replaced, so no CLI runs,
no request is billed, no socket opens and no real process is signalled. What
these pin is the mapping from wordings to calls, the failure table in the spec
(section D) and the deadline contract: no provider can hold the command open
past its limit.
"""

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

import search

# Fake process ids above any real pid_max, so even a stray real os.killpg can
# never reach a process on the machine running the tests.
FAKE_PID_BASE = 10 ** 9


def serp(wording, n=3):
    """Three distinct results per wording, the same every run."""
    slug = '-'.join(''.join(c if c.isalnum() else ' ' for c in wording.lower()).split()) or 'w'
    return json.dumps({'results': [
        {'rank': i + 1, 'title': '{} result {}'.format(wording, i + 1),
         'url': 'https://site{}.example/{}'.format(i + 1, slug),
         'snippet': 'About {}'.format(wording), 'date': ''} for i in range(n)]})


class FakePopen:
    """Stands in for subprocess.Popen. FakePopen.script maps a wording to
    (returncode, stdout, stderr) or to 'hang', which blocks until the process
    is killed. Unscripted wordings return three results. `started` is set as
    soon as any fake process exists, so a test can wait for a launch instead
    of guessing how long a thread takes to start."""
    script = {}
    instances = []
    started = threading.Event()
    on_launch = None

    def __init__(self, cmd, **kwargs):
        self.cmd, self.kwargs = cmd, kwargs
        self.pid = FAKE_PID_BASE + len(FakePopen.instances)
        self.killed = threading.Event()
        self.returncode = None
        FakePopen.instances.append(self)
        FakePopen.started.set()
        self.outcome = FakePopen.script.get(cmd[2], (0, serp(cmd[2]), ''))
        if FakePopen.on_launch:
            FakePopen.on_launch(self)

    def communicate(self, timeout=None):
        if self.outcome == 'hang':
            if not self.killed.wait(timeout):
                raise subprocess.TimeoutExpired(self.cmd, timeout)
            self.returncode = -9
            return '', ''
        self.returncode, out, err = self.outcome
        return out, err

    def kill(self):
        self.killed.set()


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode('utf-8')

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Body:
    def __init__(self, data):
        self.data = data

    def read(self, *args):
        return self.data

    def close(self):
        pass


EXA_PAYLOAD = {'requestId': 'r1', 'answer': 'Acme charges 30 dollars.',
               'costDollars': {'total': 0.005},
               'citations': [{'url': 'https://acme.example/pricing', 'title': 'Acme pricing',
                              'text': 'Team   plan:\n30 USD', 'publishedDate': '2026-07-01T00:00:00Z'}]}


@pytest.fixture
def env(monkeypatch, tmp_path):
    FakePopen.script, FakePopen.instances, FakePopen.on_launch = {}, [], None
    FakePopen.started = threading.Event()
    killed = []
    release = threading.Event()

    def fake_killpg(pid, sig):
        assert pid >= FAKE_PID_BASE, 'a test tried to signal a real process group'
        killed.append(pid)
        for proc in FakePopen.instances:
            if proc.pid == pid:
                proc.killed.set()

    def no_network(*args, **kwargs):
        raise AssertionError('unexpected network call')

    monkeypatch.setattr(search.subprocess, 'Popen', FakePopen)
    monkeypatch.setattr(search.os, 'killpg', fake_killpg, raising=False)
    monkeypatch.setattr(search, '_GROUPS', True)
    monkeypatch.setattr(search.shutil, 'which', lambda name: '/usr/bin/brightdata')
    monkeypatch.setattr(search, 'exa_key', lambda: '')
    monkeypatch.setattr(search, 'urlopen', no_network)
    monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: '')
    monkeypatch.setattr(search.fetch, 'urlopen', no_network)
    search._CLOSED.clear()
    yield SimpleNamespace(tmp=tmp_path, killed=killed, release=release, monkeypatch=monkeypatch)
    # Free every thread a test left blocked before monkeypatch restores the
    # real functions, so no late worker reaches them.
    release.set()
    for proc in FakePopen.instances:
        proc.killed.set()
    time.sleep(0.05)
    search._CLOSED.clear()


def clock(limit=150):
    return search.Clock(limit)


# --- fan-out mapping -------------------------------------------------------

def test_a_wording_becomes_one_bd_search_call_with_engine_country_and_language(env):
    result = search.search_bd('google', 'acme pricing', 1, {'country': 'gb', 'language': 'en'}, clock())
    cmd = FakePopen.instances[0].cmd
    assert cmd[1] == search.BD_SEARCH and cmd[2] == 'acme pricing'
    for flag, value in (('-m', 'general'), ('--engine', 'google'), ('-c', '10'),
                        ('--country', 'gb'), ('--language', 'en')):
        assert cmd[cmd.index(flag) + 1] == value
    assert result['ok'] and result['provider'] == 'google' and result['wording'] == 1
    assert [r['rank'] for r in result['results']] == [1, 2, 3]


def test_a_wording_with_quotes_and_symbols_reaches_bd_search_as_one_argument(env):
    wording = '"per user per month" site:acme.example £30'
    search.search_bd('google', wording, 1, {}, clock())
    assert FakePopen.instances[0].cmd[2] == wording


def test_the_subprocess_starts_its_own_group_and_speaks_utf8(env):
    search.search_bd('google', 'q', 1, {}, clock())
    kwargs = FakePopen.instances[0].kwargs
    assert kwargs.get('start_new_session') is True
    assert kwargs.get('encoding') == 'utf-8' and kwargs['env'].get('PYTHONIOENCODING') == 'utf-8'


def test_a_rank_that_is_not_a_number_falls_back_to_its_position(env):
    FakePopen.script['q'] = (0, json.dumps({'results': [
        {'rank': 'first', 'url': 'https://a.example', 'title': 't'},
        {'url': 'https://b.example'}]}), '')
    result = search.search_bd('google', 'q', 1, {}, clock())
    assert result['ok'] and [r['rank'] for r in result['results']] == [1, 2]


def test_exa_is_asked_once_with_the_key_a_user_agent_and_text(env):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen['url'], seen['timeout'] = request.full_url, timeout
        seen['headers'] = {k.lower(): v for k, v in request.header_items()}
        seen['body'] = json.loads(request.data.decode('utf-8'))
        return FakeResponse(EXA_PAYLOAD)

    env.monkeypatch.setattr(search, 'urlopen', fake_urlopen)
    result = search.search_exa('what does acme charge', 'k123', clock())
    assert seen['url'] == search.EXA_API
    assert seen['headers']['x-api-key'] == 'k123' and seen['headers']['user-agent'] == search.USER_AGENT
    assert seen['body'] == {'query': 'what does acme charge', 'text': True}
    assert seen['timeout'] == search.EXA_TIMEOUT
    assert result['ok'] and result['answer'] == 'Acme charges 30 dollars.' and result['cost'] == 0.005
    row = result['results'][0]
    assert row == {'url': 'https://acme.example/pricing', 'title': 'Acme pricing',
                   'snippet': 'Team plan: 30 USD', 'rank': 1, 'date': '2026-07-01'}


def test_exas_timeout_never_exceeds_the_time_left(env):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen['timeout'] = timeout
        return FakeResponse(EXA_PAYLOAD)

    env.monkeypatch.setattr(search, 'urlopen', fake_urlopen)
    env.monkeypatch.setattr(search, 'RESERVE', 0.0)
    c = search.Clock(10.0)
    search.search_exa('q', 'k', c)
    assert seen['timeout'] <= 10.0


def test_the_exa_key_comes_from_the_environment_then_the_file(monkeypatch, tmp_path):
    monkeypatch.setenv('EXA_API_KEY', ' env-key ')
    assert search.exa_key() == 'env-key'
    monkeypatch.delenv('EXA_API_KEY')
    monkeypatch.setattr(search, 'EXA_KEY_FILE', str(tmp_path / 'exa-api-key'))
    assert search.exa_key() == ''
    (tmp_path / 'exa-api-key').write_text('file-key\n')
    assert search.exa_key() == 'file-key'


# --- the failure table -----------------------------------------------------

def test_exit_2_from_bd_search_is_a_refusal_and_is_not_retried(env):
    FakePopen.script['q'] = (2, '', json.dumps({'provider': 'brightdata', 'error': 'quota exceeded'}))
    result = search.search_bd('google', 'q', 1, {}, clock())
    assert result['status'] == 'refused' and 'quota exceeded' in result['reason']
    assert len(FakePopen.instances) == 1


def test_another_failure_is_retried_once_then_recorded(env):
    FakePopen.script['q'] = (1, '', json.dumps({'provider': 'brightdata', 'error': 'boom'}))
    result = search.search_bd('google', 'q', 1, {}, clock())
    assert result['status'] == 'failed' and 'boom' in result['reason']
    assert len(FakePopen.instances) == 2


def test_stdout_that_is_not_json_is_a_failure(env):
    FakePopen.script['q'] = (0, 'not json', '')
    assert search.search_bd('google', 'q', 1, {}, clock())['status'] == 'failed'


def test_bd_searchs_zero_results_message_is_a_success_with_no_results(env):
    FakePopen.script['q'] = (1, '', json.dumps({'provider': 'brightdata', 'error': search.ZERO_RESULTS}))
    result = search.search_bd('google', 'q', 1, {}, clock())
    assert result['ok'] and result['results'] == [] and len(FakePopen.instances) == 1


def test_a_retry_waits_for_enough_time(env):
    env.monkeypatch.setattr(search, 'RETRY_MIN', 10_000)
    FakePopen.script['q'] = (1, '', '{"error": "boom"}')
    search.search_bd('google', 'q', 1, {}, clock())
    assert len(FakePopen.instances) == 1


def test_exa_http_error_is_recorded_with_its_status_and_body(env):
    def refuse(request, timeout=None):
        raise HTTPError(search.EXA_API, 402, 'Payment Required', {}, _Body(b'{"error": "out of credits"}'))

    env.monkeypatch.setattr(search, 'urlopen', refuse)
    result = search.search_exa('q', 'k', clock())
    assert result['status'] == 'failed' and result['reason'].startswith('HTTP 402') and 'out of credits' in result['reason']
    assert result['answer'] == '' and result['cost'] is None


def test_exa_with_no_citations_is_a_success_with_no_results(env):
    env.monkeypatch.setattr(search, 'urlopen', lambda r, timeout=None: FakeResponse({'answer': 'x', 'citations': []}))
    result = search.search_exa('q', 'k', clock())
    assert result['ok'] and result['results'] == []


def test_exa_returning_something_that_is_not_an_object_is_a_failure(env):
    env.monkeypatch.setattr(search, 'urlopen', lambda r, timeout=None: FakeResponse(['a list']))
    assert search.search_exa('q', 'k', clock())['status'] == 'failed'


# --- the deadline contract -------------------------------------------------

def test_a_bd_search_that_never_returns_is_killed_with_its_group(env):
    env.monkeypatch.setattr(search, 'RESERVE', 0.2)
    FakePopen.script['q'] = 'hang'
    c = search.Clock(3.0)
    jobs = [('g1', lambda: search.search_bd('google', 'q', 1, {}, c),
             search.provider_result('google', 'q', 1, 'deadline'))]
    started = time.monotonic()
    results = search.run_jobs(jobs, c)
    assert FakePopen.started.wait(2), 'the worker never launched bd_search.py'
    assert time.monotonic() - started < 3.0 + 1.0
    assert results[0]['status'] in ('timeout', 'deadline')
    assert FakePopen.instances[0].pid in env.killed


def test_an_exa_call_that_never_returns_cannot_hold_the_call_open(env):
    env.monkeypatch.setattr(search, 'RESERVE', 0.2)

    def hang(request, timeout=None):
        env.release.wait()
        return FakeResponse(EXA_PAYLOAD)

    env.monkeypatch.setattr(search, 'urlopen', hang)
    c = search.Clock(2.0)
    jobs = [('exa', lambda: search.search_exa('q', 'k', c), search.provider_result('exa', 'q', status='deadline'))]
    started = time.monotonic()
    results = search.run_jobs(jobs, c)
    assert time.monotonic() - started < 2.0 + 1.0
    assert results[0]['status'] == 'deadline'


def test_a_launch_after_the_deadline_is_refused(env):
    search._CLOSED.set()
    with pytest.raises(search.Cancelled):
        search.run_process(['x', 'y', 'q'], 5)
    assert FakePopen.instances == []


def test_a_process_launched_as_the_deadline_falls_is_killed_not_missed(env):
    # The deadline lands between Popen returning and the process being
    # registered: kill_all runs from inside the launch.
    FakePopen.on_launch = lambda proc: search.kill_all()
    FakePopen.script['q'] = 'hang'
    with pytest.raises(search.Cancelled):
        search.run_process(['x', 'y', 'q'], 5)
    assert FakePopen.instances[0].pid in env.killed
    assert search._PROCS == set()


def test_run_jobs_returns_results_in_job_order_and_turns_exceptions_into_failures(env):
    def boom():
        raise RuntimeError('worker blew up')

    jobs = [('a', lambda: search.provider_result('google', 'a', 1), {}),
            ('b', boom, search.provider_result('google', 'b', 2, 'deadline')),
            ('c', lambda: search.provider_result('google', 'c', 3), {})]
    results = search.run_jobs(jobs, clock())
    assert [r['query'] for r in results] == ['a', 'b', 'c']
    assert results[1]['status'] == 'failed' and 'worker blew up' in results[1]['reason']


def test_where_killpg_does_not_exist_the_process_alone_is_killed(env):
    env.monkeypatch.setattr(search, '_GROUPS', False)
    env.monkeypatch.setattr(search, 'RESERVE', 0.2)
    FakePopen.script['q'] = 'hang'
    search.search_bd('google', 'q', 1, {}, search.Clock(1.5))
    proc = FakePopen.instances[0]
    assert 'start_new_session' not in proc.kwargs and proc.killed.is_set()


# --- fix round 1 -----------------------------------------------------------

def test_a_key_file_with_a_second_line_gives_the_first_line_only(monkeypatch, tmp_path):
    monkeypatch.delenv('EXA_API_KEY', raising=False)
    monkeypatch.setattr(search, 'EXA_KEY_FILE', str(tmp_path / 'exa-api-key'))
    (tmp_path / 'exa-api-key').write_text('\n  k1  \nx2\n')
    assert search.exa_key() == 'k1'


def test_a_key_with_whitespace_or_control_characters_inside_is_no_key(monkeypatch, tmp_path):
    monkeypatch.delenv('EXA_API_KEY', raising=False)
    monkeypatch.setattr(search, 'EXA_KEY_FILE', str(tmp_path / 'exa-api-key'))
    (tmp_path / 'exa-api-key').write_text('two words\n')
    assert search.exa_key() == ''
    monkeypatch.setenv('EXA_API_KEY', 'bad\x07key')
    assert search.exa_key() == ''


def test_a_key_file_that_is_not_utf8_gives_no_key(monkeypatch, tmp_path):
    monkeypatch.delenv('EXA_API_KEY', raising=False)
    monkeypatch.setattr(search, 'EXA_KEY_FILE', str(tmp_path / 'exa-api-key'))
    (tmp_path / 'exa-api-key').write_bytes(b'\xff\xfe')
    assert search.exa_key() == ''


def test_an_empty_key_file_and_no_variable_gives_no_key(monkeypatch, tmp_path):
    monkeypatch.delenv('EXA_API_KEY', raising=False)
    monkeypatch.setattr(search, 'EXA_KEY_FILE', str(tmp_path / 'exa-api-key'))
    (tmp_path / 'exa-api-key').write_text('')
    assert search.exa_key() == ''


def test_the_key_never_appears_in_a_recorded_reason(env):
    def refuse(request, timeout=None):
        raise ValueError('bad header SECRETkey')

    env.monkeypatch.setattr(search, 'urlopen', refuse)
    result = search.search_exa('q', 'SECRETkey', clock())
    assert result['status'] == 'failed' and 'SECRETkey' not in result['reason'] and '[key]' in result['reason']


def test_every_exa_failure_still_carries_answer_and_cost(env):
    cases = [lambda r, timeout=None: FakeResponse(['a list']),
             lambda r, timeout=None: (_ for _ in ()).throw(OSError('down'))]
    for fake in cases:
        env.monkeypatch.setattr(search, 'urlopen', fake)
        result = search.search_exa('q', 'k', clock())
        assert result['status'] == 'failed' and result['answer'] == '' and result['cost'] is None
    env.monkeypatch.setattr(search, 'RESERVE', 10_000)
    result = search.search_exa('q', 'k', clock())
    assert result['status'] == 'deadline' and result['answer'] == '' and result['cost'] is None


def test_search_bd_with_no_options_sends_neither_country_nor_language(env):
    search.search_bd('google', 'q', 1, {}, clock())
    cmd = FakePopen.instances[0].cmd
    assert '--country' not in cmd and '--language' not in cmd


def test_kill_all_skips_a_process_that_has_already_been_reaped(env):
    reaped = FakePopen(['x', 'y', 'reaped'])
    reaped.returncode = 0
    live = FakePopen(['x', 'y', 'live'])
    with search._PROCS_LOCK:
        search._PROCS.update({reaped, live})
    try:
        search.kill_all()
    finally:
        with search._PROCS_LOCK:
            search._PROCS.difference_update({reaped, live})
    assert live.pid in env.killed and reaped.pid not in env.killed


def test_a_falsy_worker_result_is_kept_not_mistaken_for_a_missed_deadline(env):
    jobs = [('a', lambda: {}, search.provider_result('google', 'a', 1, 'deadline'))]
    assert search.run_jobs(jobs, clock()) == [{}]


# --- fix round 2 -----------------------------------------------------------

def test_a_key_with_a_newline_is_refused_before_any_request(env):
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request)
        raise ValueError("Invalid header value b'SECRET\\nkey'")

    env.monkeypatch.setattr(search, 'urlopen', fake_urlopen)
    result = search.search_exa('q', 'SECRET\nkey', clock())
    assert result['status'] == 'failed' and calls == []
    assert 'SECRET' not in result['reason'] and 'key\n' not in result['reason']
    assert result['answer'] == '' and result['cost'] is None


def test_the_key_is_scrubbed_before_a_long_http_body_is_cut(env):
    key = 'sk-abcdef1234567890zz'
    body = ('x' * 104 + key + 'y' * 40).encode('utf-8')

    def refuse(request, timeout=None):
        raise HTTPError(search.EXA_API, 401, 'Unauthorized', {}, _Body(body))

    env.monkeypatch.setattr(search, 'urlopen', refuse)
    result = search.search_exa('q', key, clock())
    assert result['status'] == 'failed' and result['reason'].startswith('HTTP 401')
    assert key[:6] not in result['reason']


def datetime_utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_by_default_google_gets_no_country_or_language(env, capsys):
    search.main(['--angle', 'q', '--wording', 'w1', '--out-dir', str(env.tmp)])
    cmd = FakePopen.instances[0].cmd
    assert '--country' not in cmd and '--language' not in cmd


def test_the_whole_command_keeps_its_limit_with_everything_hanging(env, capsys):
    """Spec D: a bd_search.py, an Exa call and a Jev batch that never return.
    The network phase ends by the limit and the hanging process group is
    killed. The local work after it is measured, not promised, so the whole
    command gets a loose bound that a starved CPU cannot trip."""
    env.monkeypatch.setattr(search, 'RESERVE', 0.5)
    env.monkeypatch.setattr(search, 'JEV_MIN', 0.1)
    env.monkeypatch.setattr(search, 'JEV_MARGIN', 0.1)
    env.monkeypatch.setattr(search, 'exa_key', lambda: 'k')
    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'k')
    env.monkeypatch.setattr(search.fetch, '_jev_request', lambda *a, **k: env.release.wait())

    def hang(request, timeout=None):
        env.release.wait()
        return FakeResponse(EXA_PAYLOAD)

    env.monkeypatch.setattr(search, 'urlopen', hang)
    FakePopen.script['w-hang'] = 'hang'
    started = time.monotonic()
    code = search.main(['--angle', 'q', '--wording', 'w-ok', '--wording', 'w-hang',
                        '--time-limit', '5', '--out-dir', str(env.tmp)])
    elapsed = time.monotonic() - started
    assert code == 0  # w-ok answered
    record = json.load(open(next(env.tmp.glob('*.json'))))
    assert record['network_seconds'] <= 5 + 0.5, record['network_seconds']  # one poll interval of slack
    assert elapsed < 5 + 5, elapsed
    hung = [p for p in FakePopen.instances if p.cmd[2] == 'w-hang']
    assert hung and all(p.pid in env.killed for p in hung)
    out = capsys.readouterr().out
    assert 'exa: deadline' in out and 'jev: skipped (time)' in out

# --- the provider table ----------------------------------------------------

def test_a_provider_added_only_to_the_table_is_run_merged_and_reported(env, capsys):
    def search_stub(query, number, detail, opts, c):
        return search.provider_result('stub', query, status='ok', results=[
            {'url': 'https://stub.example/x', 'title': 'Stub', 'snippet': 'from the stub', 'rank': 1, 'date': ''}])

    table = search.PROVIDERS + [{'name': 'stub', 'label': 'stub', 'per': 'angle',
                                 'available': lambda: (True, ''), 'run': search_stub}]
    env.monkeypatch.setattr(search, 'PROVIDERS', table)
    assert search.main(['--angle', 'q', '--wording', 'w1', '--out-dir', str(env.tmp)]) == 0
    out = capsys.readouterr().out
    assert 'stub ok' in out.splitlines()[0]
    assert 'https://stub.example/x' in out and '[stub]' in out


# --- merge and rank --------------------------------------------------------

def ok(provider, wording, rows):
    return search.provider_result(provider, 'q', wording, 'ok', results=[
        {'url': url, 'title': title, 'snippet': snippet, 'rank': rank, 'date': ''}
        for rank, (url, title, snippet) in enumerate(rows, 1)])


def test_two_urls_that_canonicalise_alike_merge_and_keep_every_list():
    leads = search.merge([
        ok('google', 1, [('https://www.acme.example/pricing/', 'Acme', 'short')]),
        ok('google', 2, [('https://acme.example/pricing', '', 'a much longer snippet')]),
        ok('exa', None, [('https://acme.example/pricing?utm_source=x', 'Acme pricing', '')]),
    ])
    assert len(leads) == 1
    lead = leads[0]
    assert set(lead['ranks']) == {'g1', 'g2', 'exa'}
    assert lead['snippet'] == 'a much longer snippet' and lead['title'] == 'Acme'


def test_failed_results_contribute_nothing():
    failed = search.provider_result('google', 'q', 1, 'failed', results=[
        {'url': 'https://x.example', 'title': '', 'snippet': '', 'rank': 1, 'date': ''}])
    assert search.merge([failed]) == []


def test_exa_citations_with_no_title_or_text_and_repeats_merge_cleanly():
    leads = search.merge([ok('exa', None, [('https://a.example/1', '', ''), ('https://a.example/1', '', 'x')])])
    assert len(leads) == 1 and leads[0]['ranks'] == {'exa': 1} and leads[0]['snippet'] == 'x'


def test_bing_and_google_are_separate_lists_with_separate_labels():
    leads = search.merge([ok('google', 3, [('https://a.example', 't', 's')]),
                          ok('bing', 3, [('https://a.example', 't', 's')])])
    assert set(leads[0]['ranks']) == {'g3', 'b3'}


def test_a_lead_found_by_three_lists_ranks_above_one_found_once():
    leads = search.merge([
        ok('google', 1, [('https://once.example', 't', 's'), ('https://thrice.example', 't', 's')]),
        ok('google', 2, [('https://thrice.example', 't', 's')]),
        ok('exa', None, [('https://thrice.example', 't', 's')]),
    ])
    ranked = search.rank(leads)
    assert ranked[0]['url'] == 'https://thrice.example'
    assert ranked[0]['score'] == 1.0 and ranked[0]['jev'] is None


def test_jev_scores_average_in_with_scaled_rrf():
    leads = search.merge([ok('google', 1, [('https://a.example', 't', 's'), ('https://b.example', 't', 's')])])
    ranked = search.rank(leads, jev=[0.0, 1.0])  # a ranks first by RRF; Jev prefers b
    by_url = {lead['url']: lead for lead in ranked}
    assert by_url['https://a.example']['score'] == 0.5
    assert by_url['https://b.example']['score'] > 0.5
    assert ranked[0]['url'] == 'https://b.example'


def test_jev_is_off_without_a_key(env):
    assert search.jev_scores('q', [{'title': 't', 'snippet': 's'}], clock()) == (None, 'off')


def test_jev_scores_every_lead_and_gets_the_time_left_less_its_margin(env):
    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'k')
    timeouts = []

    def fake(state, questions, key, timeout=60):
        timeouts.append(timeout)
        return {'answers': {name: {'probabilities': {'3': 1.0}} for name in questions}}

    env.monkeypatch.setattr(search.fetch, '_jev_request', fake)
    c = clock(150)
    leads = [{'title': 't{}'.format(i), 'snippet': 's'} for i in range(45)]  # two batches
    scores, status = search.jev_scores('q', leads, c)
    assert status == 'on' and scores == [1.0] * 45
    expected = 150 - search.RESERVE - search.JEV_MARGIN
    assert len(timeouts) == 2 and all(expected - 1 < t <= expected for t in timeouts)


def test_one_failed_jev_batch_discards_every_jev_score(env):
    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'k')
    lock, calls = threading.Lock(), []

    def fake(state, questions, key, timeout=60):
        with lock:
            calls.append(1)
            second = len(calls) == 2
        if second:
            raise RuntimeError('jev down')
        return {'answers': {name: {'probabilities': {'3': 1.0}} for name in questions}}

    env.monkeypatch.setattr(search.fetch, '_jev_request', fake)
    scores, status = search.jev_scores('q', [{'title': str(i), 'snippet': ''} for i in range(45)], clock())
    assert scores is None and status.startswith('failed')


def test_jev_is_skipped_when_time_is_short(env):
    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'k')
    env.monkeypatch.setattr(search, 'JEV_MIN', 10_000)
    assert search.jev_scores('q', [{'title': 't', 'snippet': 's'}], clock()) == (None, 'skipped (time)')


def test_a_jev_batch_that_never_returns_cannot_hold_the_call_open(env):
    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'k')
    env.monkeypatch.setattr(search, 'JEV_MIN', 0.1)
    env.monkeypatch.setattr(search, 'JEV_MARGIN', 0.1)
    env.monkeypatch.setattr(search, 'RESERVE', 0.2)
    env.monkeypatch.setattr(search.fetch, '_jev_request', lambda *a, **k: env.release.wait())
    started = time.monotonic()
    scores, status = search.jev_scores('q', [{'title': 't', 'snippet': 's'}], search.Clock(2.0))
    assert time.monotonic() - started < 2.0 + 1.0
    assert scores is None and status == 'skipped (time)'


# --- the record ------------------------------------------------------------

def test_the_record_path_sits_beside_the_tsv():
    tsv = '/runs/run/Run_20261017.tsv'
    path = search.record_path('What does Acme charge?', tsv=tsv, now=datetime_utc(2026, 10, 17, 10, 15, 0))
    assert path == '/runs/run/Run_20261017.searches/20261017T101500Z-what-does-acme-charge.json'


def test_without_a_tsv_the_record_goes_to_out_dir_or_tmp():
    assert search.record_path('a', out_dir='/x', now=datetime_utc(2026, 1, 1)).startswith('/x/')
    assert search.record_path('a', now=datetime_utc(2026, 1, 1)).startswith('/tmp/legwork/searches/')


def test_a_call_with_a_fresh_tsv_creates_the_searches_folder(env, capsys):
    tsv = str(env.tmp / 'new-run' / 'Run.tsv')
    assert search.main(['--angle', 'a', '--wording', 'w1', '--tsv', tsv]) == 0
    assert (env.tmp / 'new-run' / 'Run.searches').is_dir()
    assert not os.path.exists(tsv)  # search.py writes nothing to the run's .tsv


def test_two_records_on_the_same_path_never_overwrite_each_other(env):
    path = str(env.tmp / 'r' / 'same.json')
    first = search._write_record(path, {'n': 1})
    second = search._write_record(path, {'n': 2})
    assert first != second
    assert json.load(open(first)) == {'n': 1} and json.load(open(second)) == {'n': 2}


def test_records_written_at_once_on_the_same_path_all_survive(env):
    path = str(env.tmp / 'r' / 'race.json')
    written = []
    threads = [threading.Thread(target=lambda n=n: written.append(search._write_record(path, {'n': n})))
               for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(written)) == 8
    assert sorted(json.load(open(p))['n'] for p in written) == list(range(8))


def test_the_record_holds_wordings_failures_leads_and_the_answer(env, capsys):
    env.monkeypatch.setattr(search, 'exa_key', lambda: 'k')
    env.monkeypatch.setattr(search, 'urlopen', lambda r, timeout=None: FakeResponse(EXA_PAYLOAD))
    FakePopen.script['w2'] = (2, '', '{"error": "quota"}')
    tsv = str(env.tmp / 'run.tsv')
    assert search.main(['--angle', 'what does acme charge', '--wording', 'w1', '--wording', 'w2', '--tsv', tsv]) == 0
    record = json.load(open(next((env.tmp / 'run.searches').iterdir())))
    assert record['angle'] == 'what does acme charge' and record['wordings'] == ['w1', 'w2']
    assert {p['status'] for p in record['providers']} == {'ok', 'refused'}
    assert record['exa_answer'] == 'Acme charges 30 dollars.' and record['exa_cost'] == 0.005
    assert record['jev'] == 'off' and len(record['leads']) == 4
    assert not os.path.exists(tsv)


# --- output ----------------------------------------------------------------

def test_output_has_a_status_line_capped_leads_a_more_line_and_the_answer_last(env, capsys):
    env.monkeypatch.setattr(search, 'exa_key', lambda: 'k')
    env.monkeypatch.setattr(search, 'urlopen', lambda r, timeout=None: FakeResponse(
        dict(EXA_PAYLOAD, answer='A' * 2000)))
    args = ['--angle', 'q', '--show', '5', '--tsv', str(env.tmp / 'run.tsv')]
    for wording in ['w{}'.format(i) for i in range(1, 7)]:
        args += ['--wording', wording]
    assert search.main(args) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].startswith('search: 6 wordings · google 6/6 ok · exa ok · jev: off · 19 leads (top 5 shown)')
    assert ' 5. ' in out and ' 6. ' not in out
    assert '+14 more: search.py --more ' in out and '--from 6' in out
    heading = "Exa's written answer - UNVERIFIED, NOT A SOURCE. Open the cited pages before using anything in it:"
    assert heading in out
    answer = out.split(heading, 1)[1].strip()
    assert len(answer) <= 1500 and out.rstrip().endswith(answer)


def test_exa_is_queued_ahead_of_the_wordings(env, capsys):
    order = []
    env.monkeypatch.setattr(search, 'exa_key', lambda: 'k')

    def fake_urlopen(request, timeout=None):
        order.append('exa')
        return FakeResponse(EXA_PAYLOAD)

    FakePopen.on_launch = lambda proc: order.append(proc.cmd[2])
    env.monkeypatch.setattr(search, 'urlopen', fake_urlopen)
    env.monkeypatch.setattr(search, 'MAX_WORKERS', 1)  # one at a time, so order is the queue's
    search.main(['--angle', 'q', '--wording', 'w1', '--wording', 'w2', '--out-dir', str(env.tmp)])
    assert order[0] == 'exa'


def test_a_lead_line_shows_title_url_snippet_and_its_lists(env):
    lead = {'url': 'https://acme.example/pricing', 'title': 'T' * 150, 'snippet': 'S\n' * 200,
            'ranks': {'exa': 2, 'b2': 1, 'g5': 3, 'g1': 1}}
    lines = search.lead_lines([lead], 1, 40)
    assert lines[0] == ' 1. ' + 'T' * 100
    assert lines[1] == '    https://acme.example/pricing'
    assert lines[2].endswith('[g1 g5 b2 exa]') and '\n' not in lines[2]
    assert len(lines[2].split('"')[1]) <= 163  # 160 characters and an ellipsis


def test_a_more_line_quotes_a_path_with_spaces(env):
    assert search._more_line('/runs/my run/x.json', 3, 41) == "+3 more: search.py --more '/runs/my run/x.json' --from 41"


def test_no_bright_data_and_no_exa_key_exits_4_and_says_use_websearch(env, capsys):
    env.monkeypatch.setattr(search.shutil, 'which', lambda name: None)
    assert search.main(['--angle', 'q', '--wording', 'w1', '--out-dir', str(env.tmp)]) == search.EXIT_NO_PROVIDER
    out = capsys.readouterr().out
    assert 'google: not installed' in out and 'exa: no key' in out
    assert 'search: no search provider available - use WebSearch' in out


def test_every_call_refused_also_exits_4(env, capsys):
    FakePopen.script['w1'] = (2, '', '{"error": "quota"}')
    assert search.main(['--angle', 'q', '--wording', 'w1', '--out-dir', str(env.tmp)]) == 4


def test_zero_results_from_a_working_provider_is_exit_0(env, capsys):
    FakePopen.script['w1'] = (1, '', json.dumps({'error': search.ZERO_RESULTS}))
    assert search.main(['--angle', 'q', '--wording', 'w1', '--out-dir', str(env.tmp)]) == 0
    assert '0 leads' in capsys.readouterr().out


def test_no_exa_flag_sends_nothing_to_exa(env, capsys):
    env.monkeypatch.setattr(search, 'exa_key', lambda: 'k')  # urlopen still raises if called
    assert search.main(['--angle', 'q', '--wording', 'w1', '--no-exa', '--out-dir', str(env.tmp)]) == 0
    assert 'exa: off' in capsys.readouterr().out


def test_engine_both_sends_each_wording_to_google_and_bing(env, capsys):
    search.main(['--angle', 'q', '--wording', 'w1', '--engine', 'both', '--out-dir', str(env.tmp)])
    engines = sorted(p.cmd[p.cmd.index('--engine') + 1] for p in FakePopen.instances)
    assert engines == ['bing', 'google']


@pytest.mark.parametrize('argv', [
    ['--wording', 'w1'],                                        # no angle
    ['--angle', 'q'],                                           # no wording
    ['--angle', 'q'] + ['--wording', 'w'] * 13,                 # too many
    ['--angle', 'q', '--wording', 'w1', '--show', '0'],
    ['--angle', 'q', '--wording', 'w1', '--engine', 'yandex'],
    ['--angle', 'q', '--wording', 'w1', '--time-limit', '3'],   # no time for any search
    ['--angle', 'q', '--wording', 'w1', '--tsv', 'a.tsv', '--out-dir', '/tmp'],
])
def test_bad_arguments_exit_2(env, argv):
    with pytest.raises(SystemExit) as exc:
        search.main(argv)
    assert exc.value.code == 2


# --- --more ------------------------------------------------------------------

def test_more_prints_the_next_slice_with_no_network(env, capsys):
    tsv = str(env.tmp / 'run.tsv')
    search.main(['--angle', 'q', '--show', '3', '--tsv', tsv, '--wording', 'w1', '--wording', 'w2'])
    capsys.readouterr()
    record = str(next((env.tmp / 'run.searches').iterdir()))
    before = len(FakePopen.instances)
    assert search.main(['--more', record, '--from', '4', '--show', '2']) == 0
    out = capsys.readouterr().out
    assert out.startswith('search: leads 4 to 5 of 6 from ')
    assert ' 4. ' in out and ' 5. ' in out and ' 6. ' not in out
    assert '+1 more: search.py --more ' in out and '--from 6' in out
    assert len(FakePopen.instances) == before


def test_more_past_the_end_or_on_an_empty_record_says_so(env, capsys):
    path = env.tmp / 'empty.json'
    path.write_text(json.dumps({'leads': []}))
    assert search.main(['--more', str(path)]) == 0
    assert capsys.readouterr().out.strip() == 'search: no leads from 41; the record has 0'


@pytest.mark.parametrize('content', ['', 'not json', '[1, 2]', '{"leads": "x"}', '{"leads": [{"title": "no url"}]}'])
def test_more_on_a_missing_or_malformed_record_exits_2_without_a_traceback(env, capsys, content):
    path = env.tmp / 'bad.json'
    if content:
        path.write_text(content)
    assert search.main(['--more', str(path)]) == 2
    assert 'search: cannot read' in capsys.readouterr().err


# --- fix round 1 -------------------------------------------------------------

def _jev_env(env, fake):
    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'k')
    env.monkeypatch.setattr(search.fetch, '_jev_request', fake)


def _answers_missing_one(state, questions, key, timeout=60):
    names = sorted(questions)[1:]
    return {'answers': {name: {'probabilities': {'3': 1.0}} for name in names}}


def test_a_jev_answer_left_out_fails_jev_rather_than_scoring_zero(env):
    _jev_env(env, _answers_missing_one)
    leads = [{'title': 't{}'.format(i), 'snippet': 's'} for i in range(3)]
    scores, status = search.jev_scores('q', leads, clock())
    assert scores is None and status.startswith('failed') and '1 unanswered' in status


def test_a_jev_response_with_no_answers_fails_jev(env):
    _jev_env(env, lambda *a, **k: {})
    scores, status = search.jev_scores('q', [{'title': 't', 'snippet': 's'}], clock())
    assert scores is None and status.startswith('failed')


def test_main_shows_jev_failed_and_ranks_on_rrf_alone(env, capsys):
    _jev_env(env, _answers_missing_one)
    assert search.main(['--angle', 'q', '--wording', 'w1', '--out-dir', str(env.tmp)]) == 0
    out = capsys.readouterr().out
    assert 'jev: failed' in out.splitlines()[0]
    record = json.load(open(next(env.tmp.glob('*.json'))))
    assert all(lead['jev'] is None for lead in record['leads'])


def test_a_jev_failure_reason_does_not_carry_the_key(env):
    def boom(*a, **k):
        raise RuntimeError('rejected key sk-secret-123 here')

    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'sk-secret-123')
    env.monkeypatch.setattr(search.fetch, '_jev_request', boom)
    scores, status = search.jev_scores('q', [{'title': 't', 'snippet': 's'}], clock())
    assert scores is None and 'sk-secret-123' not in status and '[key]' in status


def test_a_key_with_no_leads_is_skipped_not_off(env):
    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'k')
    assert search.jev_scores('q', [], clock()) == (None, 'skipped (no leads)')


def test_the_workers_constant_is_read_when_run_jobs_starts(env):
    env.monkeypatch.setattr(search, 'MAX_WORKERS', 1)
    active, peak, lock = [0], [0], threading.Lock()

    def job():
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return {'ok': True}

    search.run_jobs([('j', job, {}) for _ in range(4)], clock())
    assert peak[0] == 1


@pytest.mark.parametrize('lead', [
    {'url': 123},
    {'url': 'https://a.example', 'title': 5},
    {'url': 'https://a.example', 'snippet': ['x']},
    {'url': 'https://a.example', 'date': 20260101},
    {'url': 'https://a.example', 'ranks': {'g1': 'x'}},
    {'url': 'https://a.example', 'ranks': [1]},
])
def test_more_on_a_lead_of_the_wrong_type_exits_2_without_a_traceback(env, capsys, lead):
    path = env.tmp / 'typed.json'
    path.write_text(json.dumps({'leads': [lead]}))
    assert search.main(['--more', str(path), '--from', '1']) == 2
    assert 'search: cannot read' in capsys.readouterr().err


def test_an_unwritable_record_still_prints_the_leads_and_keeps_the_exit_code(env, capsys):
    blocker = env.tmp / 'afile'
    blocker.write_text('x')
    args = ['--angle', 'q', '--wording', 'w1', '--show', '1', '--out-dir', str(blocker / 'sub')]
    assert search.main(args) == 0
    out = capsys.readouterr().out
    assert ' 1. ' in out and 'search: record not written (' in out and '+2 more' not in out


@pytest.mark.parametrize('limit', ['inf', 'nan', '-inf'])
def test_a_time_limit_that_is_not_a_finite_number_exits_2(env, limit):
    with pytest.raises(SystemExit) as exc:
        search.main(['--angle', 'q', '--wording', 'w1', '--time-limit', limit, '--out-dir', str(env.tmp)])
    assert exc.value.code == 2
