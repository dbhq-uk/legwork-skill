#!/usr/bin/env python3
"""
gather.py - search every source, open every result, log it, and digest it.

    gather.py --plan PLAN.json --tsv RUN.tsv --out DIGEST.md [--time-limit 600]

The retrieval half of a legwork run, with no model in the loop. Claude writes
the plan - each angle's question phrased several ways, naming nothing - and
this does the rest for every angle at once:

  1. search    every phrasing on Bing, asked directly and free, and on Bright
               Data (Google and Bing) only when that is refused or empty; for
               angles about people's experience also Hacker News, Stack
               Exchange, GitHub issues and Reddit
  2. narrow    one entry per page, however many searches found it
  3. open      every page: fetch.py, then Bright Data scrape and render, then
               a copy of the same document on another host
  4. log       every retrieval into the fetch log with its page text, so every
               quote taken from it can be checked
  5. digest    (see the digest section) the passages Claude reads instead of
               the pages

It exists because retrieval subagents were most of a run's cost and none of
its judgement. Measured on 2026-09-25: an orchestrator spent 34 of its 55
steps waiting for subagents, and search results were 45% of what subagents
read, all of it re-read on every later step. Here search results never reach
a conversation, and there is nothing to wait for.

Exit codes: 0 done; 1 the plan is invalid; 2 every search failed and Bright
Data refused (auth, quota or rate limit) - there is nothing to digest, and the
run stops rather than finding nothing and calling it an answer. A refusal that
leaves anything found is not an abort: the run finishes, and the digest says
how many calls Bright Data refused and why. Measured on 2026-09-27, aborting on
the first refused page threw away 286 opened pages.

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)

import fetch  # noqa: E402
import rerank  # noqa: E402
import sources  # noqa: E402
from independence import canonicalize, party_of  # noqa: E402

ENGINES = ('google', 'bing')
PEOPLE_PLATFORMS = ('hn', 'stackexchange', 'githubissues', 'reddit')
RESULTS_PER_SEARCH = 10
DEFAULT_TIME_LIMIT = 360
DEFAULT_WORKERS = 12
SEARCH_TIMEOUT = 90
OPEN_TIMEOUT = 120
REFUSAL_BACKOFF = 5


class PlanError(ValueError):
    """The plan cannot be run as written."""


class SearchAborted(RuntimeError):
    """Every search failed and Bright Data refused: nothing to digest."""


# Every Bright Data refusal in this run, as its first line of stderr. Worker
# threads append; list.append is atomic, and run() resets it.
_REFUSALS = []


def _refused(err):
    lines = [line for line in (err or '').strip().splitlines() if line.strip()]
    _REFUSALS.append((lines[-1] if lines else 'refused')[:200])


def run_script(argv, timeout):
    """(exit code, stdout, stderr). The one seam the tests replace."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, '', 'timed out after {}s'.format(timeout)
    return done.returncode, done.stdout, done.stderr


def _script(name, *args):
    return [sys.executable, os.path.join(SCRIPTS, name)] + [str(a) for a in args]


def _json(text):
    try:
        return json.loads(text)
    except ValueError:
        return {}


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

def load_plan(path):
    """The plan, checked. Every name in a round-2 angle must come from a source."""
    try:
        with open(path, encoding='utf-8') as handle:
            plan = json.load(handle)
    except (OSError, ValueError) as exc:
        raise PlanError('cannot read the plan: {}'.format(exc))
    angles = plan.get('angles') or []
    if not angles:
        raise PlanError('the plan has no angles')
    seen = set()
    for angle in angles:
        angle_id = angle.get('id')
        if not angle_id or not angle.get('question'):
            raise PlanError('every angle needs an id and a question')
        if angle_id in seen:
            raise PlanError('angle id {!r} is used twice'.format(angle_id))
        seen.add(angle_id)
        angle.setdefault('phrasings', [])
        angle.setdefault('disconfirming', [])
        angle.setdefault('urls', [])
        if not (angle['phrasings'] or angle['urls']):
            raise PlanError('angle {!r} has nothing to search and no links to open'.format(angle_id))
        if angle.get('subject') and not (angle.get('from') or angle.get('expected') is True):
            raise PlanError(
                'angle {!r} names {!r}, which no source has named - add "from" with the ids of the '
                'round-1 sources that named it, or "expected": true to search for it as a check on '
                'memory'.format(angle_id, angle['subject']))
    plan.setdefault('country', '')
    plan.setdefault('language', '')
    return plan


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _serp(query, engine, plan):
    """Bright Data results for one query on one engine, or None if it failed twice."""
    argv = _script('bd_search.py', query, '-m', 'general', '--engine', engine, '-c', RESULTS_PER_SEARCH, '--json')
    if plan.get('country'):
        argv += ['--country', plan['country']]
    if plan.get('language'):
        argv += ['--language', plan['language']]
    for attempt in range(2):
        code, out, err = run_script(argv, SEARCH_TIMEOUT)
        if code == 0:
            return [dict(r, via='serp', query=query) for r in _json(out).get('results') or []]
        if code == 2:
            # Auth, quota, or a rate limit when several runs share the account.
            # Only the last is worth waiting out, and it is the common one.
            _refused(err)
            if attempt == 0:
                time.sleep(REFUSAL_BACKOFF)
    return None


def _platform(platform, query, plan=None):
    argv = _script('platforms.py', 'search', '--on', platform, '--query', query, '--limit', RESULTS_PER_SEARCH)
    if plan and platform == 'bing':
        if plan.get('country'):
            argv += ['--country', plan['country']]
        if plan.get('language'):
            argv += ['--language', plan['language']]
    code, out, _err = run_script(argv, SEARCH_TIMEOUT)
    if code != 0:
        return None
    return [dict(r, via='api', query=query) for r in _json(out).get('results') or []]


def _search_jobs(angle, plan):
    jobs = []
    for query in angle['phrasings'] + angle['disconfirming']:
        jobs.append(('web', query, 'bing-local'))
    if angle.get('people'):
        for query in angle['phrasings']:
            for platform in PEOPLE_PLATFORMS:
                jobs.append(('platform', query, platform))
    return jobs


def _run_search(job, plan):
    kind, query, where = job
    if kind == 'web':
        # Free first: Bing asked directly from this machine. Bright Data only
        # when that is refused or empty (Dan, 27 Sep 2026: "curl locally
        # first then bdata").
        local = _platform('bing', query, plan)
        if local:
            return [dict(hit, via='serp') for hit in local]
        found = [_serp(query, engine, plan) for engine in ENGINES]
        if all(result is None for result in found):
            return None
        return [hit for result in found if result for hit in result]
    found = _platform(where, query)
    if found is None and where == 'reddit':
        # Reddit's RSS refused: find its threads through a search instead.
        found = _serp('site:reddit.com ' + query, 'google', plan)
    return found


# ---------------------------------------------------------------------------
# Open
# ---------------------------------------------------------------------------

def _page_path(out_dir, url, suffix=''):
    folder = os.path.join(out_dir, 'pages')
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, hashlib.sha1((url + suffix).encode('utf-8')).hexdigest()[:16] + '.txt')


def _flatten(value, out):
    if isinstance(value, str):
        if value.strip():
            out.append(value.strip())
    elif isinstance(value, dict):
        for item in value.values():
            _flatten(item, out)
    elif isinstance(value, list):
        for item in value:
            _flatten(item, out)


def _open_reddit(url, out_dir):
    """A Reddit thread with its comments, through Bright Data's Reddit dataset,
    saved as text with a sidecar like any other page."""
    code, out, err = run_script(_script('bd_search.py', url, '-m', 'reddit', '--json'), OPEN_TIMEOUT)
    if code == 2:
        _refused(err)
    if code != 0:
        return None
    parts = []
    _flatten(_json(_json(out).get('content') or '[]'), parts)
    if not parts:
        return None
    path = _page_path(out_dir, url, '#reddit')
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write('\n\n'.join(parts))
    sidecar = os.path.splitext(path)[0] + '.json'
    with open(sidecar, 'w', encoding='utf-8') as handle:
        json.dump({'url': url, 'title': '', 'date': '', 'verdict': 'ok', 'text_file': path,
                   'provider': 'brightdata'}, handle)
    return sidecar


def _step_timeout(deadline):
    """Seconds one step of the ladder may take: OPEN_TIMEOUT, or what is left
    of the run's time limit, whichever is less; 0 when it has run out."""
    if deadline is None:
        return OPEN_TIMEOUT
    left = deadline - time.monotonic()
    return 0 if left <= 0 else int(min(OPEN_TIMEOUT, max(10, left)))


def open_url(url, title, out_dir, plan, deadline=None):
    """{'sidecar': path or None, 'refused': bool, 'copy_of': url or None, 'url': url}.

    fetch.py, then Bright Data scrape and render; for a Reddit thread its
    dataset first; then a copy of the same document on another host. Each step
    starts only while the run's time limit allows, so one slow host cannot hold
    the run past it.
    """
    refused = False
    path = _page_path(out_dir, url)
    code, _out, _err = run_script(_script('fetch.py', url, '--out', path), _step_timeout(deadline) or 10)
    if code == 0:
        return {'url': url, 'sidecar': os.path.splitext(path)[0] + '.json', 'refused': False, 'copy_of': None}
    if code == 5:
        return {'url': url, 'sidecar': None, 'refused': False, 'policy': True, 'copy_of': None}
    refused = True
    if not _step_timeout(deadline):
        return {'url': url, 'sidecar': None, 'refused': refused, 'copy_of': None}
    if 'reddit.com/' in url:
        sidecar = _open_reddit(url, out_dir)
        if sidecar:
            return {'url': url, 'sidecar': sidecar, 'refused': refused, 'copy_of': None}
    for mode in ('scrape', 'render'):
        timeout = _step_timeout(deadline)
        if not timeout:
            return {'url': url, 'sidecar': None, 'refused': refused, 'copy_of': None}
        alt = _page_path(out_dir, url, '#' + mode)
        code, _out, err = run_script(_script('bd_search.py', url, '-m', mode, '--out', alt, '--json'), timeout)
        if code == 0:
            return {'url': url, 'sidecar': os.path.splitext(alt)[0] + '.json', 'refused': refused, 'copy_of': None}
        if code == 2:
            _refused(err)
    # Every transport asks the same host for the same URL; a publisher refusing
    # by policy refuses them all. A copy on another host often opens for free.
    if title and len(title) > 12 and _step_timeout(deadline):
        wanted = '"{}"'.format(title[:120])
        copies = _platform('bing', wanted, plan) or _serp(wanted, 'google', plan) or []
        for copy in copies[:3]:
            other = copy.get('url') or ''
            if other and party_of(other) != party_of(url):
                cpath = _page_path(out_dir, other)
                code, _out, _err = run_script(_script('fetch.py', other, '--out', cpath), OPEN_TIMEOUT)
                if code == 0:
                    return {'url': other, 'sidecar': os.path.splitext(cpath)[0] + '.json',
                            'refused': refused, 'copy_of': url}
    return {'url': url, 'sidecar': None, 'refused': refused, 'copy_of': None}


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

class _Log:
    """Serialised writes to the fetch log from worker threads."""

    def __init__(self, tsv):
        self.tsv = tsv
        self.lock = threading.Lock()

    def row(self, **fields):
        args = argparse.Namespace(
            tsv=self.tsv, url=fields.get('url', ''), kind=None, angle=fields['angle'],
            via=fields.get('via', ''), status=fields.get('status', 'ok'), quote='',
            title=fields.get('title', ''), date=fields.get('date', ''), text_file=None,
            numbers='', query=fields.get('query', ''), from_fetch=fields.get('sidecar'))
        with self.lock:
            try:
                sources.log_row(args)
            except sources.LogError:
                return False
        return True


def run(plan, tsv, out_dir, time_limit=DEFAULT_TIME_LIMIT, workers=DEFAULT_WORKERS):
    """Search, open and log every angle. Returns what the digest is built from."""
    deadline = time.monotonic() + time_limit
    log = _Log(tsv)
    report = {'angles': {}}
    del _REFUSALS[:]

    # 1. Search, every angle at once.
    jobs = [(angle['id'], job) for angle in plan['angles'] for job in _search_jobs(angle, plan)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [(angle_id, job, pool.submit(_run_search, job, plan)) for angle_id, job in jobs]
        results = [(angle_id, job, future.result()) for angle_id, job, future in futures]
    if _REFUSALS and all(found is None for _a, _j, found in results) \
            and not any(angle['urls'] for angle in plan['angles']):
        raise SearchAborted('every search failed and Bright Data refused ({}): run `brightdata login`, or '
                            'check the balance with `brightdata budget`, then run gather.py again.'
                            .format(_REFUSALS[0]))

    # 2. Narrow: one entry per page per angle, keeping the first query that found it.
    hits = {angle['id']: {} for angle in plan['angles']}
    stats = {angle['id']: {'searches': 0, 'failed_searches': 0} for angle in plan['angles']}
    new_parties = {angle['id']: [] for angle in plan['angles']}
    seen_parties = {angle['id']: set() for angle in plan['angles']}
    for angle_id, _job, found in results:
        stats[angle_id]['searches'] += 1
        if found is None:
            stats[angle_id]['failed_searches'] += 1
            continue
        parties = {party_of(hit['url']) for hit in found if hit.get('url')}
        new_parties[angle_id].append(len(parties - seen_parties[angle_id]))
        seen_parties[angle_id] |= parties
        for hit in found:
            if hit.get('url'):
                hits[angle_id].setdefault(canonicalize(hit['url']), hit)
    for angle_id, counts in new_parties.items():
        # Saturated: the last three searches found no party the earlier ones had
        # not. Unsaturated means more phrasings would still turn up new voices.
        stats[angle_id]['saturated'] = (len(counts) >= 4 and sum(counts[-3:]) == 0
                                        and bool(seen_parties[angle_id]))
        stats[angle_id]['parties_found'] = len(seen_parties[angle_id])
    for angle in plan['angles']:
        for url in angle['urls']:
            hits[angle['id']].setdefault(canonicalize(url), {'url': url, 'title': '', 'via': 'direct',
                                                            'query': 'from the plan'})

    # 3. Open each page once, however many angles found it.
    unique = {}
    for angle_hits in hits.values():
        for key, hit in angle_hits.items():
            unique.setdefault(key, hit)
    opened = {}

    def open_one(key, hit):
        if time.monotonic() > deadline:
            return key, None
        return key, open_url(hit['url'], hit.get('title', ''), out_dir, plan, deadline)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, result in pool.map(lambda kv: open_one(*kv), list(unique.items())):
            opened[key] = result

    # 4. Log one row per page per angle.
    by_id = {angle['id']: angle for angle in plan['angles']}
    for angle_id, angle_hits in hits.items():
        question = by_id[angle_id]['question']
        entry = dict(stats[angle_id], question=question, opened=[], blocked=0, not_reached=0, leads=0,
                     hits=len(angle_hits))
        for key, hit in angle_hits.items():
            result = opened.get(key)
            if result is None:
                via = hit.get('via') if hit.get('via') in ('serp', 'api') else 'serp'
                log.row(angle=question, url=hit['url'], via=via, title=hit.get('title', ''),
                        query=hit.get('query', ''))
                entry['not_reached'] += 1
                entry['leads'] += 1
                continue
            if result.get('policy'):
                continue
            if result['refused']:
                log.row(angle=question, url=hit['url'], via='direct', status='blocked',
                        title=hit.get('title', ''), query=hit.get('query', ''))
                entry['blocked'] += 1
            if result['sidecar']:
                log.row(angle=question, sidecar=result['sidecar'], query=hit.get('query', ''))
                entry['opened'].append({'url': result['url'], 'sidecar': result['sidecar'],
                                        'party': party_of(result['url']), 'copy_of': result['copy_of'],
                                        'query': hit.get('query', '')})
        report['angles'][angle_id] = entry
    report['refused'] = list(_REFUSALS)
    return report


# ---------------------------------------------------------------------------
# The digest
# ---------------------------------------------------------------------------

PASSAGE_SHOWN = 600
NAMES_SHOWN = 40
_NAME = re.compile(r"\b[A-Z][\w&'-]*(?:[ \t]+(?:of[ \t]+)?[A-Z][\w&'-]*){0,3}")
_NOT_NAMES = frozenset("""
a an and as at be but by for from how if in is it its of on or our so that the their them then there
these they this those to we what when where which who why will with you your all any each more most
no not only other some such than too very can may must should would could also however here new
january february march april may june july august september october november december
monday tuesday wednesday thursday friday saturday sunday home menu login sign contact about terms
privacy cookies policy read learn find get see click skip search next previous share
once can i help type content yes please thank thanks note step first last page back
""".split())


def _names(text):
    found = set()
    for match in _NAME.finditer(text or ''):
        name = ' '.join(match.group(0).split()).strip(".-'")
        words = [w.lower().strip(".'") for w in name.split() if w.lower() != 'of']
        if not words or all(w in _NOT_NAMES for w in words) or len(name) < 3:
            continue
        found.add(name)
    return found


NAME_POOL = 200


def _named(items):
    """{name: parties} from the best-ranked passages only.

    Measured on the first live run, 2026-09-27: counted over whole pages, the
    list was led by GitHub's own page furniture - Star, Fork, Dismiss - which
    every issue page repeats. Relevant passages carry names; furniture does
    not rank. A word the pool uses in lowercase more often than capitalised is
    an ordinary word at the start of a sentence, not a name.
    """
    ranked = sorted(items, key=lambda item: item.get('score', 0), reverse=True)[:NAME_POOL]
    names = {}
    for item in ranked:
        for name in _names(item['text']):
            names.setdefault(name, set()).add(item['party'])
    if not names:
        return names
    pool = ' '.join(item['text'] for item in items)
    for name in list(names):
        if ' ' not in name and len(re.findall(r'\b{}\b'.format(re.escape(name.lower())), pool)) > \
                len(re.findall(r'\b{}\b'.format(re.escape(name)), pool)):
            del names[name]
    return names


def _subject_party(angle, items):
    """The party that is the angle's subject: the one whose domain carries the
    subject's name. Its pages are primary evidence and are never capped."""
    subject = re.sub(r'[^a-z0-9]', '', (angle.get('subject') or '').lower())
    if not subject:
        return None
    counts = {}
    for item in items:
        if subject[:12] in re.sub(r'[^a-z0-9]', '', item['party']):
            counts[item['party']] = counts.get(item['party'], 0) + 1
    return max(counts, key=counts.get) if counts else None


def _load_ids(path):
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def write_digest(plan, report, tsv, out):
    """The digest Claude reads: per angle, the top of the reranked passage pool,
    capped per party with the overflow listed, plus in round 1 the names the
    sources mention and how many independent parties mention each."""
    round_ = plan.get('round', 1)
    ids_path = os.path.splitext(tsv)[0] + '.ids.json'
    ids = _load_ids(ids_path)
    angles_out, scorers = [], set()
    all_parties, totals = set(), {'searches': 0, 'failed': 0, 'hits': 0, 'opened': 0, 'blocked': 0,
                                  'not_reached': 0}
    for angle in plan['angles']:
        entry = report['angles'][angle['id']]
        totals['searches'] += entry['searches']
        totals['failed'] += entry['failed_searches']
        totals['hits'] += entry['hits']
        totals['opened'] += len(entry['opened'])
        totals['blocked'] += entry['blocked']
        totals['not_reached'] += entry['not_reached']
        items, names = [], {}
        for page in entry['opened']:
            try:
                with open(page['sidecar'], encoding='utf-8') as handle:
                    sidecar = json.load(handle)
                with open(sidecar['text_file'], encoding='utf-8', errors='replace') as handle:
                    text = handle.read()
            except (OSError, ValueError, KeyError):
                continue
            all_parties.add(page['party'])
            headings = [tuple(h) for h in sidecar.get('headings') or []]
            for passage in fetch.passages_with_trail(text, headings):
                items.append({'url': page['url'], 'party': page['party'], 'text': passage['text'],
                              'trail': passage['trail'], 'title': sidecar.get('title') or '',
                              'date': sidecar.get('date') or '', 'text_file': sidecar['text_file']})
        terms = [angle['question']] + angle['phrasings'] + angle['disconfirming']
        scores, scorer = rerank.pool_scores([item['text'] for item in items], terms, angle['question'])
        scorers.add(scorer)
        for number, (item, score) in enumerate(zip(items, scores), 1):
            item['id'] = 'r{}-{}-{}'.format(round_, angle['id'], number)
            item['score'] = score
            ids[item['id']] = {k: item[k] for k in ('url', 'party', 'text', 'trail', 'title', 'date', 'text_file')}
            ids[item['id']]['angle'] = angle['question']
        if round_ == 1:
            names = _named(items)
        chosen, overflow = rerank.select_digest(items, _subject_party(angle, items))
        angles_out.append((angle, entry, chosen, overflow, names))

    lines = ['# Gather digest - round {} - {}'.format(round_, plan.get('date', '')), '',
             '*{} searches ({} failed) · {} pages found · {} opened from {} parties · {} blocked · '
             '{} not reached · passages ranked by {}*'.format(
                 totals['searches'], totals['failed'], totals['hits'], totals['opened'], len(all_parties),
                 totals['blocked'], totals['not_reached'], ' and '.join(sorted(scorers)) or 'nothing'),
             '']
    if report.get('refused'):
        reasons = sorted(set(report['refused']))
        lines += ['**Bright Data refused {} call{}** ({}). Those pages and searches are missing from '
                  'this digest. A rate limit passes; if it says auth or balance, run `brightdata login` '
                  'or `brightdata budget`.'.format(len(report['refused']), '' if len(report['refused']) == 1
                                                   else 's', '; '.join(reasons[:2])), '']
    lines += ['Read any passage in full, or any listed in overflow: `gather.py --show ID --tsv {}`. '
              'Record a quote you rely on: `sources.py quote --tsv {} --id ID --quote "..."`.'.format(tsv, tsv)]
    for angle, entry, chosen, overflow, names in angles_out:
        lines += ['', '## {} - {}'.format(angle['id'], angle['question']), '',
                  '{} pages found · {} opened · {} blocked · {} not reached · search {}'.format(
                      entry['hits'], len(entry['opened']), entry['blocked'], entry['not_reached'],
                      'saturated' if entry.get('saturated') else 'not saturated - more phrasings may find more')]
        if angle.get('subject'):
            lines.append('Subject: {} (from {})'.format(
                angle['subject'], ', '.join(angle.get('from') or []) or 'memory, searched as a check'))
        named = sorted(((n, len(p)) for n, p in names.items() if len(p) >= 2), key=lambda x: (-x[1], x[0]))
        if named:
            lines += ['', 'Named by sources (independent parties naming each):', '',
                      ' · '.join('{} {}'.format(n, c) for n, c in named[:NAMES_SHOWN])]
        lines.append('')
        for item in chosen:
            kind = sources.infer_source_kind(item['url'], item['title'])
            meta = ' · '.join(x for x in (item['party'], kind, item['date'] or 'undated', item['trail']) if x)
            text = ' '.join(item['text'].split())
            if len(text) > PASSAGE_SHOWN:
                text = text[:PASSAGE_SHOWN].rsplit(' ', 1)[0] + ' ...'
            lines += ['- **{}** · {}'.format(item['id'], meta), '  {}'.format(text)]
        for party, left in sorted(overflow.items(), key=lambda kv: -len(kv[1])):
            lines.append('- +{} more from {}: {}'.format(len(left), party, ', '.join(left[:12])
                                                        + (' ...' if len(left) > 12 else '')))
    with open(out, 'w', encoding='utf-8') as handle:
        handle.write('\n'.join(lines) + '\n')
    with open(ids_path, 'w', encoding='utf-8') as handle:
        json.dump(ids, handle, ensure_ascii=False)
    return out


def show(ids_to_show, tsv):
    ids = _load_ids(os.path.splitext(tsv)[0] + '.ids.json')
    for passage_id in ids_to_show:
        entry = ids.get(passage_id)
        if not entry:
            print('{}: no such passage'.format(passage_id))
            continue
        print('## {} · {} · {}\n{}\n'.format(passage_id, entry['url'], entry.get('trail') or '', entry['text']))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='gather.py', description=__doc__.split('\n')[1].strip())
    parser.add_argument('--plan', help='The plan to gather')
    parser.add_argument('--tsv', required=True, help='The run fetch log')
    parser.add_argument('--out', help='Where to write the digest')
    parser.add_argument('--show', nargs='+', metavar='ID', help='Print passages from an earlier digest in full')
    parser.add_argument('--time-limit', type=int, default=DEFAULT_TIME_LIMIT,
                        help='Seconds the run may take; pages not opened by then are logged as leads')
    parser.add_argument('--workers', type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args(argv)
    if args.show:
        show(args.show, args.tsv)
        return
    if not (args.plan and args.out):
        parser.error('--plan and --out are required to gather')
    try:
        plan = load_plan(args.plan)
    except PlanError as exc:
        print('gather.py: {}'.format(exc), file=sys.stderr)
        sys.exit(1)
    out_dir = os.path.dirname(os.path.abspath(args.tsv))
    try:
        report = run(plan, args.tsv, out_dir, args.time_limit, args.workers)
    except SearchAborted as exc:
        print('gather.py: {}'.format(exc), file=sys.stderr)
        sys.exit(2)
    write_digest(plan, report, args.tsv, args.out)
    if report.get('refused'):
        print('gather.py: Bright Data refused {} calls; the digest says which were missed'
              .format(len(report['refused'])), file=sys.stderr)
    summary = {angle_id: {k: v for k, v in entry.items() if k != 'opened'} | {'opened': len(entry['opened'])}
               for angle_id, entry in report['angles'].items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
