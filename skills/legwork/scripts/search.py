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

import argparse
import json
import math
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch  # noqa: E402
from independence import canonicalize  # noqa: E402

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


def _clean_key(text):
    """The first non-blank line, or '' when what is left holds any whitespace or
    control character: such a key can never be a valid header value, and a
    rejected header would put the key into an error message."""
    for line in (text or '').splitlines():
        line = line.strip()
        if line:
            if any(c.isspace() or not c.isprintable() for c in line):
                return ''
            return line
    return ''


def exa_key():
    """EXA_API_KEY from the environment, else ~/.dbhq/legwork/exa-api-key."""
    key = _clean_key(os.environ.get('EXA_API_KEY', ''))
    if key:
        return key
    try:
        with open(os.path.expanduser(EXA_KEY_FILE), encoding='utf-8') as handle:
            return _clean_key(handle.read())
    except (OSError, ValueError):
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
    except OSError:
        pass


def kill_all():
    """At the deadline: refuse new launches, and kill every bd_search.py still
    running, with its process group."""
    with _PROCS_LOCK:
        _CLOSED.set()
        procs = list(_PROCS)
    for proc in procs:
        if proc.returncode is None:  # a reaped process may have freed its pgid
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

    def failure(status, reason):
        # The key never appears in a recorded reason, whatever raised it.
        if key:
            reason = reason.replace(key, '[key]')
        reason = ' '.join(reason.split())[:120]
        return provider_result('exa', angle, status=status, reason=reason,
                               seconds=time.monotonic() - started, answer='', cost=None)

    # A key that exa_key would not hand back unchanged never reaches a header:
    # every key that does is printable with no whitespace, so it appears in any
    # message literally and the replacement above catches it.
    if key != _clean_key(key):
        return failure('failed', 'the Exa key holds whitespace or a control character')
    left = clock.remaining()
    if left <= 0:
        return failure('deadline', 'no time left')
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
        return failure('failed', 'HTTP {}: {}'.format(exc.code, ' '.join(body.split())).strip())
    except Exception as exc:  # noqa: BLE001 - any failure skips Exa, never the call
        return failure('failed', ' '.join(str(exc).split()) or type(exc).__name__)
    if not isinstance(payload, dict):
        return failure('failed', 'response was not a JSON object')
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


def run_jobs(jobs, clock, workers=None):
    """Run (label, fn, placeholder) jobs on daemon threads and return their
    results in job order. Python cannot kill a thread, so the main thread never
    joins one: it waits on a queue until the clock runs out, then kills every
    subprocess still running and returns each unfinished job's placeholder,
    marked 'deadline'. A worker that raises becomes a failed result."""
    workers = MAX_WORKERS if workers is None else workers
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
    return [results[index] if index in results
            else dict(jobs[index][2] or {}, ok=False, status='deadline', reason='not finished by the time limit')
            for index in range(len(jobs))]


# ---------------------------------------------------------------------------
# Providers: one table. A per-angle provider is a function and an entry here;
# a per-wording search engine also needs its name in ENGINES.
# ---------------------------------------------------------------------------

def _bright_data_available():
    return (True, '') if bright_data_installed() else (False, 'not installed')


def _exa_available():
    key = exa_key()
    return (True, key) if key else (False, 'no key')


# name: the provider's name in results, the status line and the record.
# label: the prefix of its lists in a lead's provenance (g3, b3) or, for a
#   provider asked once per angle, the whole label (exa).
# per: 'wording' (one call per wording, chosen by --engine) or 'angle' (one
#   call with the angle, always run unless switched off).
# available: () -> (ok, detail); detail is the reason when not ok, otherwise
#   whatever the provider needs (Exa's key).
# run: (query, number, detail, opts, clock) -> provider_result.
PROVIDERS = [
    {'name': 'exa', 'label': 'exa', 'per': 'angle', 'available': _exa_available,
     'run': lambda query, number, detail, opts, clock: search_exa(query, detail, clock)},
    {'name': 'google', 'label': 'g', 'per': 'wording', 'available': _bright_data_available,
     'run': lambda query, number, detail, opts, clock: search_bd('google', query, number, opts, clock)},
    {'name': 'bing', 'label': 'b', 'per': 'wording', 'available': _bright_data_available,
     'run': lambda query, number, detail, opts, clock: search_bd('bing', query, number, opts, clock)},
]
ENGINES = {'google': ['google'], 'bing': ['bing'], 'both': ['google', 'bing']}


def _provider(name):
    return next((p for p in PROVIDERS if p['name'] == name), None)


# ---------------------------------------------------------------------------
# Merge, rank, record and print
# ---------------------------------------------------------------------------

RRF_K = 60
SHOW_TITLE = 100
SHOW_SNIPPET = 160
SHOW_ANSWER = 1500
ANSWER_HEADING = ("Exa's written answer - UNVERIFIED, NOT A SOURCE. "
                  "Open the cited pages before using anything in it:")


def list_label(result):
    """One ranked list per provider per wording: g3 and b3 are two lists."""
    provider = _provider(result['provider'])
    label = provider['label'] if provider else result['provider']
    if provider is None or provider['per'] == 'wording':
        return '{}{}'.format(label, result['wording'])
    return label


def merge(results):
    """Leads keyed on the canonical URL. Each keeps every list that found it with
    its best rank there, the longest snippet and the first title."""
    leads = {}
    for result in results:
        if not result.get('ok'):
            continue
        label = list_label(result)
        for row in result.get('results') or []:
            key = canonicalize(row.get('url') or '')
            if not key:
                continue
            lead = leads.get(key)
            if lead is None:
                lead = leads[key] = {'url': row['url'], 'title': row.get('title') or '',
                                     'snippet': row.get('snippet') or '', 'date': row.get('date') or '', 'ranks': {}}
            if len(row.get('snippet') or '') > len(lead['snippet']):
                lead['snippet'] = row['snippet']
            if not lead['title'] and row.get('title'):
                lead['title'] = row['title']
            if not lead['date'] and row.get('date'):
                lead['date'] = row['date']
            rank = _rank(row.get('rank'), 1)
            lead['ranks'][label] = min(rank, lead['ranks'].get(label, rank))
    return list(leads.values())


def rrf(lead):
    return sum(1.0 / (RRF_K + rank) for rank in lead['ranks'].values())


def jev_scores(angle, leads, clock):
    """(scores or None, status). All or nothing: if any batch fails or runs out
    of time, no lead is Jev-scored, so no lead is ranked on a different basis
    from another. Ranking only - nothing is ever dropped on Jev's say."""
    key = fetch.typesafe_key()
    if not key:
        return None, 'off'
    if not leads:
        return None, 'skipped (no leads)'
    timeout = clock.remaining() - JEV_MARGIN
    if clock.remaining() < JEV_MIN or timeout <= 0:
        return None, 'skipped (time)'
    texts = ['{}\n{}'.format(lead.get('title') or '', lead.get('snippet') or '') for lead in leads]
    batches = [texts[i:i + fetch.JEV_BATCH] for i in range(0, len(texts), fetch.JEV_BATCH)]
    out, errors = [None] * len(batches), []

    def work(number, batch):
        state = {'question': angle, 'passages': {'p{}'.format(i): text for i, text in enumerate(batch)}}
        questions = {'p{}'.format(i): {
            'type': 'score', 'criteria': fetch.JEV_LEVELS,
            'instructions': 'How well does search result `passages.p{}` help answer `question`?'.format(i)}
            for i in range(len(batch))}
        try:
            answers = (fetch._jev_request(state, questions, key, timeout=timeout) or {}).get('answers')
            missing = len(batch) if not isinstance(answers, dict) else sum(
                1 for i in range(len(batch)) if 'p{}'.format(i) not in answers)
            if missing:
                raise ValueError('Jev left {} unanswered'.format(missing))
            out[number] = [fetch._expected_score(answers.get('p{}'.format(i))) for i in range(len(batch))]
        except Exception as exc:  # noqa: BLE001 - a ranking aid never fails the search
            reason = ' '.join(str(exc).split()) or type(exc).__name__
            if key:
                reason = reason.replace(key, '[key]')
            errors.append(reason[:80])

    threads = [threading.Thread(target=work, args=(n, b), daemon=True) for n, b in enumerate(batches)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(max(0.0, clock.remaining()))
    if errors:
        return None, 'failed ({})'.format(errors[0])
    if any(scores is None for scores in out):
        return None, 'skipped (time)'
    return [score for scores in out for score in scores], 'on'


def rank(leads, jev=None):
    """RRF scaled to the top lead, averaged with Jev's score when there is one
    (the mean of a lexical and a Jev score ranked best offline on 27 Sep 2026)."""
    raw = [rrf(lead) for lead in leads]
    top = max(raw) if raw else 0.0
    for index, lead in enumerate(leads):
        scaled = raw[index] / top if top else 0.0
        lead['rrf'] = round(raw[index], 6)
        lead['jev'] = None if jev is None else round(jev[index], 3)
        lead['score'] = round(scaled if jev is None else (scaled + jev[index]) / 2, 6)
    return sorted(leads, key=lambda lead: (-lead['score'], lead['url']))


def _slug(text, limit=60):
    return '-'.join(re.findall(r'[a-z0-9]+', (text or '').lower()))[:limit].strip('-') or 'angle'


def record_path(angle, tsv=None, out_dir=None, now=None):
    if tsv:
        folder = os.path.splitext(tsv)[0] + '.searches'
    else:
        folder = out_dir or os.path.join('/tmp', 'legwork', 'searches')
    stamp = (now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%SZ')
    return os.path.join(folder, '{}-{}.json'.format(stamp, _slug(angle)))


def _write_record(path, record):
    """Write the record, never over another: each candidate name is created
    exclusively, so two calls in the same second each get their own file."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    base, ext = os.path.splitext(path)
    n = 1
    while True:
        candidate = path if n == 1 else '{}-{}{}'.format(base, n, ext)
        try:
            with open(candidate, 'x', encoding='utf-8') as handle:
                json.dump(record, handle, ensure_ascii=False, indent=1)
            return candidate
        except FileExistsError:
            n += 1


def _label_order(label):
    for position, provider in enumerate(PROVIDERS):
        prefix = provider['label']
        if provider['per'] == 'angle' and label == prefix:
            return (1, position, 0)
        if provider['per'] == 'wording' and label.startswith(prefix) and label[len(prefix):].isdigit():
            return (0, position, int(label[len(prefix):]))
    return (2, 0, 0)


def lead_lines(leads, start, show):
    lines = []
    for number, lead in enumerate(leads[start - 1:start - 1 + show], start):
        title = ' '.join((lead.get('title') or lead['url']).split())[:SHOW_TITLE]
        snippet = ' '.join((lead.get('snippet') or '').split())
        if len(snippet) > SHOW_SNIPPET:
            snippet = snippet[:SHOW_SNIPPET] + '...'
        labels = ' '.join(sorted(lead.get('ranks') or {}, key=_label_order))
        lines.append('{:>2}. {}'.format(number, title))
        lines.append('    {}'.format(lead['url']))
        lines.append('    "{}"   [{}]'.format(snippet, labels) if snippet else '    [{}]'.format(labels))
    return lines


def _more_line(path, remaining, start):
    return '+{} more: search.py --more {} --from {}'.format(remaining, shlex.quote(path), start)


def _provider_status(results):
    parts = []
    for provider in sorted(PROVIDERS, key=lambda p: p['per'] == 'angle'):
        mine = [r for r in results if r['provider'] == provider['name']]
        if not mine:
            continue
        skipped = [r for r in mine if r['status'] == 'skipped']
        if skipped:
            parts.append('{}: {}'.format(provider['name'], skipped[0]['reason']))
            continue
        if provider['per'] == 'angle':
            result = mine[0]
            parts.append('{} ok'.format(provider['name']) if result['ok']
                         else '{}: {} ({})'.format(provider['name'], result['status'], result['reason']))
            continue
        text = '{} {}/{} ok'.format(provider['name'], sum(r['ok'] for r in mine), len(mine))
        bad = {}
        for r in mine:
            if not r['ok']:
                bad[r['status']] = bad.get(r['status'], 0) + 1
        if bad:
            text += ' ({})'.format(', '.join('{} {}'.format(count, status) for status, count in sorted(bad.items())))
        parts.append(text)
    return parts


def cmd_search(angle, wordings, args):
    clock = Clock(args.time_limit)
    opts = {'country': args.country, 'language': args.language}
    off = {'exa'} if args.no_exa else set()
    chosen = [p for p in PROVIDERS
              if (p['per'] == 'angle' and p['name'] not in off)
              or (p['per'] == 'wording' and p['name'] in ENGINES[args.engine])]
    # Per-angle providers first: Exa answers in about two seconds and must not
    # queue behind Google calls that take thirteen to sixty.
    chosen.sort(key=lambda p: p['per'] != 'angle')
    jobs, skipped = [], []
    for provider in chosen:
        ok, detail = provider['available']()
        queries = [(angle, None)] if provider['per'] == 'angle' else [(w, n) for n, w in enumerate(wordings, 1)]
        if not ok:
            skipped.append(provider_result(provider['name'], angle if provider['per'] == 'angle' else '', None,
                                           'skipped', detail))
            continue
        for query, number in queries:
            jobs.append(('{}:{}'.format(provider['name'], number),
                         (lambda p=provider, q=query, n=number, d=detail: p['run'](q, n, d, opts, clock)),
                         provider_result(provider['name'], query, number, 'deadline')))
    for name in sorted(off):
        skipped.append(provider_result(name, angle, status='skipped', reason='off'))

    results = run_jobs(jobs, clock) + skipped
    leads = merge(results)
    jev, jev_status = jev_scores(angle, leads, clock)
    network_seconds = round(clock.elapsed(), 2)  # every network call has ended or been abandoned
    leads = rank(leads, jev)
    exa = next((r for r in results if r['provider'] == 'exa'), {})
    answer = ' '.join(str(exa.get('answer') or '').split())

    record = {
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'), 'angle': angle, 'wordings': wordings,
        'engine': args.engine, 'country': args.country, 'language': args.language,
        'providers': results, 'jev': jev_status, 'leads': leads,
        'exa_answer': exa.get('answer') or '', 'exa_cost': exa.get('cost'),
        'network_seconds': network_seconds, 'seconds': round(clock.elapsed(), 1)}
    path, write_error = None, ''
    try:
        path = _write_record(record_path(angle, args.tsv, args.out_dir), record)
    except OSError as exc:  # the leads are still worth printing
        write_error = ' '.join(str(exc).split()) or type(exc).__name__

    shown = min(args.show, len(leads))
    count = '{} lead{}'.format(len(leads), '' if len(leads) == 1 else 's')
    if len(leads) > shown:
        count += ' (top {} shown)'.format(shown)
    status = ['search: {} wording{}'.format(len(wordings), '' if len(wordings) == 1 else 's')]
    status += _provider_status(results)
    status += ['jev on' if jev_status == 'on' else 'jev: {}'.format(jev_status), count,
               '{:.0f}s'.format(clock.elapsed())]
    lines = [' · '.join(status)]
    lines += lead_lines(leads, 1, shown)
    if write_error:
        lines.append('search: record not written ({})'.format(write_error))
    elif len(leads) > shown:
        lines.append(_more_line(path, len(leads) - shown, shown + 1))
    if not any(r['ok'] for r in results):
        lines.append('search: no search provider available - use WebSearch')
    if answer:
        lines += ['', ANSWER_HEADING, '    ' + answer[:SHOW_ANSWER]]
    print('\n'.join(lines))
    return 0 if any(r['ok'] for r in results) else EXIT_NO_PROVIDER


def _valid_lead(lead):
    """A lead a hand-edited record can still print: a string url, optional string
    title, snippet and date, and ranks that map string labels to integers."""
    if not isinstance(lead, dict) or not isinstance(lead.get('url'), str) or not lead['url']:
        return False
    if not all(isinstance(lead.get(key) or '', str) for key in ('title', 'snippet', 'date')):
        return False
    ranks = lead.get('ranks') or {}
    return isinstance(ranks, dict) and all(
        isinstance(label, str) and isinstance(rank, int) and not isinstance(rank, bool)
        for label, rank in ranks.items())


def cmd_more(path, start, show):
    try:
        with open(path, encoding='utf-8') as handle:
            record = json.load(handle)
    except (OSError, ValueError) as exc:
        print('search: cannot read {}: {}'.format(path, exc), file=sys.stderr)
        return 2
    leads = record.get('leads') if isinstance(record, dict) else None
    if not isinstance(leads, list) or not all(_valid_lead(lead) for lead in leads):
        print('search: cannot read {}: not a search record'.format(path), file=sys.stderr)
        return 2
    if start > len(leads):
        print('search: no leads from {}; the record has {}'.format(start, len(leads)))
        return 0
    end = min(len(leads), start - 1 + show)
    lines = ['search: leads {} to {} of {} from {}'.format(start, end, len(leads), path)]
    lines += lead_lines(leads, start, show)
    if end < len(leads):
        lines.append(_more_line(path, len(leads) - end, end + 1))
    print('\n'.join(lines))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='search.py', description=__doc__.split('\n')[1].strip())
    parser.add_argument('--angle', help='the angle, verbatim from Frame; this is what Exa is asked')
    parser.add_argument('--wording', action='append', default=[], help='repeatable; 1 to 12, 6 to 10 expected')
    where = parser.add_mutually_exclusive_group()
    where.add_argument('--tsv', help="the run's fetch log; the search record goes beside it")
    where.add_argument('--out-dir', dest='out_dir', help='where the search record goes when there is no --tsv')
    parser.add_argument('--country', default=None,
                        help='passed to Bright Data when given; Bing defaults to gb in bd_search.py')
    parser.add_argument('--language', default=None,
                        help='passed to Bright Data when given; Bing defaults to en in bd_search.py')
    parser.add_argument('--engine', choices=sorted(ENGINES), default='google')
    parser.add_argument('--no-exa', dest='no_exa', action='store_true')
    parser.add_argument('--show', type=int, default=40, help='leads to print; the rest are in the record')
    parser.add_argument('--time-limit', dest='time_limit', type=float, default=150.0,
                        help='seconds for every network call together (default 150)')
    parser.add_argument('--more', help='print further leads from a saved search record; no network')
    parser.add_argument('--from', dest='start', type=int, default=41, help='with --more, the first lead to print')
    args = parser.parse_args(argv)
    if args.show < 1:
        parser.error('--show must be at least 1')
    if args.more:
        return cmd_more(args.more, max(1, args.start), args.show)
    angle = ' '.join((args.angle or '').split())
    wordings = [' '.join(w.split()) for w in args.wording if w.strip()]
    if not angle:
        parser.error('--angle is required')
    if not 1 <= len(wordings) <= 12:
        parser.error('give 1 to 12 --wording values')
    if not math.isfinite(args.time_limit) or args.time_limit <= RESERVE + 1:
        parser.error('--time-limit must be more than {:.0f} seconds'.format(RESERVE + 1))
    return cmd_search(angle, wordings, args)


if __name__ == '__main__':
    sys.exit(main())
