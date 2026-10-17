"""search.py: one angle asked many ways across Bright Data and Exa.

Hermetic. subprocess.Popen, os.killpg and urlopen are replaced, so no CLI runs,
no request is billed, no socket opens and no real process is signalled. What
these pin is the mapping from wordings to calls, the failure table in the spec
(section D) and the deadline contract: no provider can hold the command open
past its limit.
"""

import json
import subprocess
import threading
import time
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
        raise ValueError('bad header SECRET key')

    env.monkeypatch.setattr(search, 'urlopen', refuse)
    result = search.search_exa('q', 'SECRET key', clock())
    assert result['status'] == 'failed' and 'SECRET key' not in result['reason'] and '[key]' in result['reason']


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
