#!/usr/bin/env python3
"""
search.py - ask one angle many ways, across Google and Exa, in one call.

    search.py --angle "what does the incumbent charge" \\
      --wording "..." --wording "..." [--wording ...]    # 1 to 12; 6 to 10 expected
      [--tsv RUN.tsv | --out-dir DIR] [--country CC] [--language LL]
      [--engine google|bing|both] [--no-exa] [--show 40] [--time-limit 150]
    search.py --more RECORD.json [--from 41] [--show 40]

Every wording goes to Bright Data (through bd_search.py) in parallel, and the
angle goes to Exa Answer once. Results are merged by canonical URL, ranked by
reciprocal rank fusion (averaged with Jev's relevance score when a key is set),
and printed as compact leads. Nothing is filtered: every lead is in the search
record, and --more prints the next slice of it.

Leads are search results, not opened pages. Nothing here writes to the run's
.tsv: a subagent returns a lead it relied on with "via": "serp", and opens a
page with fetch.py before quoting it.

Every provider is optional. A missing key, an exhausted credit or a refusal
skips that provider and says so. Exit 4 means no provider answered at all, and
the caller searches with WebSearch instead.

Exit codes: 0 when at least one provider call succeeded, even with no results;
4 when none did; 2 on bad arguments or an unreadable --more record.

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BD_SEARCH = os.path.join(HERE, 'bd_search.py')
EXA_API = 'https://api.exa.ai/answer'
EXA_KEY_FILE = os.path.join('~', '.dbhq', 'legwork', 'exa-api-key')
# Cloudflare in front of Exa refused Python's default User-Agent with 403 on
# 16 Oct 2026, so every request names itself.
USER_AGENT = 'legwork-search/1.0 (+https://github.com/dbhq-uk/legwork-skill)'
# bd_search.py reports an empty SERP as an error with exit 1. Subagents calling
# it directly rely on that to fall down the ladder, so it stays; here it is a
# success with no results.
ZERO_RESULTS = 'SERP returned zero organic results'
EXIT_NO_PROVIDER = 4

MAX_WORKERS = 10
GOOGLE_TIMEOUT = 60   # Bright Data Google: a median of 13-17s, up to 90 (16 Oct 2026)
EXA_TIMEOUT = 30
RESERVE = 3.0         # seconds kept back at the end for ranking, writing and printing
RETRY_MIN = 15.0      # a retry starts only with at least this much time left
JEV_MIN = 20.0        # Jev runs only with at least this much time left
JEV_MARGIN = 5.0
SNIPPET_KEEP = 600

# Killing a process group takes the Bright Data CLI that bd_search.py starts
# with it. Where there are no process groups (Windows), the process alone is
# killed and its child may outlive it.
_GROUPS = hasattr(os, 'killpg')
_PROCS = set()
_PROCS_LOCK = threading.Lock()
# Set by kill_all at the deadline, under the same lock that registers a
# process, so a process launched as the deadline falls is killed rather than
# missed.
_CLOSED = threading.Event()


class Cancelled(Exception):
    """The deadline passed before or while a process was being launched."""


def exa_key():
    """EXA_API_KEY from the environment, else ~/.dbhq/legwork/exa-api-key."""
    key = os.environ.get('EXA_API_KEY', '').strip()
    if key:
        return key
    try:
        with open(os.path.expanduser(EXA_KEY_FILE), encoding='utf-8') as handle:
            return handle.read().strip()
    except OSError:
        return ''


def bright_data_installed():
    return bool(shutil.which('brightdata') or shutil.which('bdata'))


class Clock:
    """Seconds left before the network phase must stop: the limit minus RESERVE."""

    def __init__(self, limit):
        self.start = time.monotonic()
        self.limit = float(limit)

    def elapsed(self):
        return time.monotonic() - self.start

    def remaining(self):
        return self.limit - RESERVE - self.elapsed()


def provider_result(provider, query, wording=None, status='ok', reason='', seconds=0.0, results=None, **extra):
    out = {'provider': provider, 'wording': wording, 'query': query, 'ok': status == 'ok',
           'status': status, 'reason': reason, 'seconds': round(float(seconds), 1), 'results': results or []}
    out.update(extra)
    return out


def _kill(proc):
    try:
        if _GROUPS:
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        pass


def kill_all():
    """At the deadline: refuse new launches, and kill every bd_search.py still
    running, with its process group."""
    with _PROCS_LOCK:
        _CLOSED.set()
        procs = list(_PROCS)
    for proc in procs:
        _kill(proc)


def run_process(cmd, timeout):
    """(returncode or None, stdout, stderr, timed_out). On timeout the process
    is killed with its whole group. Raises Cancelled when the deadline has
    already passed, or passes while the process is being launched."""
    if _CLOSED.is_set():
        raise Cancelled()
    kwargs = {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'text': True,
              'encoding': 'utf-8', 'errors': 'replace',
              'env': dict(os.environ, PYTHONIOENCODING='utf-8')}
    if _GROUPS:
        kwargs['start_new_session'] = True
    proc = subprocess.Popen(cmd, **kwargs)
    with _PROCS_LOCK:
        _PROCS.add(proc)
        closed = _CLOSED.is_set()
    if closed:
        _kill(proc)
        with _PROCS_LOCK:
            _PROCS.discard(proc)
        raise Cancelled()
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out or '', err or '', False
    except subprocess.TimeoutExpired:
        _kill(proc)
        try:
            out, err = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            out, err = '', ''
        return None, out or '', err or '', True
    finally:
        with _PROCS_LOCK:
            _PROCS.discard(proc)


def _reason(stderr):
    text = (stderr or '').strip()
    try:
        text = json.loads(text.splitlines()[-1]).get('error') or text
    except (ValueError, IndexError, AttributeError):
        pass
    return ' '.join(str(text).split())[:120]


def _rank(value, fallback):
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return fallback
    return rank if rank > 0 else fallback


def search_bd(engine, wording, number, opts, clock):
    """One wording on one Bright Data engine. A failure is retried once, if the
    deadline allows; a refusal (exit 2, auth or quota) is not. Country and
    language are passed only when given: Google is left alone, and bd_search.py
    gives Bing its own gb/en default."""
    cmd = [sys.executable, BD_SEARCH, wording, '-m', 'general', '--engine', engine, '-c', '10']
    if opts.get('country'):
        cmd += ['--country', opts['country']]
    if opts.get('language'):
        cmd += ['--language', opts['language']]
    started = time.monotonic()
    attempt = 0
    while True:
        attempt += 1
        left = clock.remaining()
        if left <= 0:
            return provider_result(engine, wording, number, 'deadline', 'no time left', time.monotonic() - started)
        wait = min(GOOGLE_TIMEOUT, left)
        try:
            code, out, err, timed_out = run_process(cmd, wait)
        except Cancelled:
            return provider_result(engine, wording, number, 'deadline', 'not finished by the time limit',
                                   time.monotonic() - started)
        if timed_out:
            status, reason = 'timeout', 'no answer in {:.0f}s'.format(wait)
        elif code == 0:
            try:
                rows = json.loads(out).get('results') or []
            except (ValueError, AttributeError):
                status, reason = 'failed', 'stdout was not JSON'
            else:
                results = [{'url': row['url'], 'title': row.get('title') or '', 'snippet': row.get('snippet') or '',
                            'rank': _rank(row.get('rank'), index + 1), 'date': row.get('date') or ''}
                           for index, row in enumerate(rows) if isinstance(row, dict) and row.get('url')]
                return provider_result(engine, wording, number, 'ok', '' if results else 'zero results',
                                       time.monotonic() - started, results)
        elif ZERO_RESULTS in (err or ''):
            return provider_result(engine, wording, number, 'ok', 'zero results', time.monotonic() - started, [])
        elif code == 2:
            return provider_result(engine, wording, number, 'refused', _reason(err), time.monotonic() - started)
        else:
            status, reason = 'failed', _reason(err) or 'exit {}'.format(code)
        if attempt >= 2 or clock.remaining() < RETRY_MIN:
            return provider_result(engine, wording, number, status, reason, time.monotonic() - started)


def search_exa(angle, key, clock):
    """The angle to Exa Answer once. Its citations become results in the order
    Exa gave them; its written answer is kept apart, unverified."""
    started = time.monotonic()
    left = clock.remaining()
    if left <= 0:
        return provider_result('exa', angle, status='deadline', reason='no time left')
    request = Request(EXA_API, data=json.dumps({'query': angle, 'text': True}).encode('utf-8'),
                      headers={'x-api-key': key, 'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
    try:
        with urlopen(request, timeout=min(EXA_TIMEOUT, left)) as response:  # noqa: S310 - fixed endpoint
            payload = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', 'replace')
        except Exception:  # noqa: BLE001 - the status code is enough without a body
            body = ''
        return provider_result('exa', angle, status='failed', seconds=time.monotonic() - started,
                               reason='HTTP {}: {}'.format(exc.code, ' '.join(body.split())[:120]).strip())
    except Exception as exc:  # noqa: BLE001 - any failure skips Exa, never the call
        return provider_result('exa', angle, status='failed', seconds=time.monotonic() - started,
                               reason=' '.join(str(exc).split())[:120] or type(exc).__name__)
    if not isinstance(payload, dict):
        return provider_result('exa', angle, status='failed', seconds=time.monotonic() - started,
                               reason='response was not a JSON object')
    results = []
    for index, cite in enumerate(payload.get('citations') or []):
        if isinstance(cite, dict) and cite.get('url'):
            results.append({'url': cite['url'], 'title': cite.get('title') or '',
                            'snippet': ' '.join(str(cite.get('text') or '').split())[:SNIPPET_KEEP],
                            'rank': index + 1, 'date': str(cite.get('publishedDate') or '')[:10]})
    cost = payload.get('costDollars')
    cost = cost.get('total') if isinstance(cost, dict) else None
    return provider_result('exa', angle, status='ok', reason='' if results else 'zero results',
                           seconds=time.monotonic() - started, results=results,
                           answer=str(payload.get('answer') or ''), cost=cost)


def run_jobs(jobs, clock, workers=MAX_WORKERS):
    """Run (label, fn, placeholder) jobs on daemon threads and return their
    results in job order. Python cannot kill a thread, so the main thread never
    joins one: it waits on a queue until the clock runs out, then kills every
    subprocess still running and returns each unfinished job's placeholder,
    marked 'deadline'. A worker that raises becomes a failed result."""
    _CLOSED.clear()
    tasks, done = queue.Queue(), queue.Queue()
    for index, job in enumerate(jobs):
        tasks.put((index, job))

    def worker():
        while True:
            try:
                index, (_label, fn, placeholder) = tasks.get_nowait()
            except queue.Empty:
                return
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - one job never stops the others
                result = dict(placeholder or {}, ok=False, status='failed',
                              reason=' '.join(str(exc).split())[:120] or type(exc).__name__)
            done.put((index, result))

    for _ in range(min(workers, len(jobs))):
        threading.Thread(target=worker, daemon=True).start()
    results = {}
    while len(results) < len(jobs):
        left = clock.remaining()
        if left <= 0:
            break
        try:
            index, result = done.get(timeout=min(left, 0.25))
        except queue.Empty:
            continue
        results[index] = result
    if len(results) < len(jobs):
        kill_all()
        while True:  # queued work never starts
            try:
                tasks.get_nowait()
            except queue.Empty:
                break
    return [results.get(index) or dict(jobs[index][2] or {}, ok=False, status='deadline',
                                       reason='not finished by the time limit')
            for index in range(len(jobs))]
