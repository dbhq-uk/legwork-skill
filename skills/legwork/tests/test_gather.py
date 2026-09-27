"""gather.py - the scripted gathering that replaces retrieval subagents.

Hermetic: every call out to bd_search.py, platforms.py and fetch.py goes
through gather.run_script, which these tests replace with a fake that answers
like the real scripts do.
"""

import json
import os

import pytest

import gather
import sources


# ---------------------------------------------------------------------------
# A fake of the three scripts
# ---------------------------------------------------------------------------

class FakeScripts:
    """Answers bd_search.py, platforms.py and fetch.py the way they answer."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.calls = []
        self.serp = {}          # (query, engine) -> [urls]
        self.platform = {}      # (platform, query) -> [urls] or an int exit code
        self.pages = {}         # url -> text; missing means blocked on fetch.py
        self.scrape = {}        # url -> text when bd scrape gets through
        self.serp_exit = 0

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        script = os.path.basename(argv[1])
        args = argv[2:]
        if script == 'bd_search.py':
            target, mode = args[0], args[args.index('-m') + 1]
            if mode == 'general':
                if self.serp_exit:
                    return self.serp_exit, '', json.dumps({'error': 'auth'})
                engine = args[args.index('--engine') + 1]
                urls = self.serp.get((target, engine), [])
                results = [{'rank': i + 1, 'title': 'T ' + u, 'url': u, 'snippet': 'S ' + u, 'date': None}
                           for i, u in enumerate(urls)]
                return 0, json.dumps({'query': target, 'log_via': 'serp', 'results': results}), ''
            if mode in ('scrape', 'render'):
                text = self.scrape.get(target)
                if text is None:
                    return 3, '', json.dumps({'verdict': 'blocked'})
                return 0, self._write(args, target, text, provider='brightdata'), ''
            return 1, '', 'unexpected mode'
        if script == 'platforms.py':
            on, query = args[args.index('--on') + 1], args[args.index('--query') + 1]
            answer = self.platform.get((on, query), [])
            if isinstance(answer, int):
                return answer, '', json.dumps({'error': 'refused'})
            results = [{'url': u, 'title': 'P ' + u, 'date': '2026-01-01', 'snippet': 'x', 'kind': 'community'}
                       for u in answer]
            return 0, json.dumps({'platform': on, 'results': results}), ''
        if script == 'fetch.py':
            url = args[0]
            text = self.pages.get(url)
            if text is None:
                return 3, '', json.dumps({'url': url, 'verdict': 'blocked'})
            return 0, self._write(args, url, text), ''
        return 1, '', 'unknown script'

    def _write(self, args, url, text, provider=None):
        out = args[args.index('--out') + 1]
        with open(out, 'w', encoding='utf-8') as handle:
            handle.write(text)
        payload = {'url': url, 'title': 'Title of ' + url, 'date': '2026-07-01', 'verdict': 'ok',
                   'text_file': out, 'headings': [[1, 'Heading']]}
        if provider:
            payload['provider'] = provider
        with open(os.path.splitext(out)[0] + '.json', 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)
        return json.dumps(payload)

    def ran(self, script, *needles):
        return [c for c in self.calls if os.path.basename(c[1]) == script and all(n in c for n in needles)]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    scripts = FakeScripts(tmp_path)
    monkeypatch.setattr(gather, 'run_script', scripts)
    return scripts


def _plan(tmp_path, angles, round_=1):
    plan = {'date': '2026-09-27', 'round': round_, 'country': 'gb', 'language': 'en', 'angles': angles}
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(plan), encoding='utf-8')
    return str(path)


def _angle(**extra):
    angle = {'id': 'offer', 'question': 'who offers a sandbox?', 'phrasings': ['bank api sandbox uk'],
             'disconfirming': ['bank sandbox not available']}
    angle.update(extra)
    return angle


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

def test_a_round_two_subject_without_a_source_is_refused(tmp_path):
    path = _plan(tmp_path, [_angle(subject='Barclays')], round_=2)
    with pytest.raises(gather.PlanError) as err:
        gather.load_plan(path)
    assert 'Barclays' in str(err.value)


def test_a_subject_with_a_source_or_marked_expected_is_accepted(tmp_path):
    gather.load_plan(_plan(tmp_path, [_angle(subject='Barclays', **{'from': ['b1']})], round_=2))
    gather.load_plan(_plan(tmp_path, [_angle(id='x', subject='Metro', expected=True)], round_=2))


def test_an_angle_with_nothing_to_search_is_refused(tmp_path):
    with pytest.raises(gather.PlanError):
        gather.load_plan(_plan(tmp_path, [{'id': 'a', 'question': 'q', 'phrasings': []}]))


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def test_every_phrasing_is_searched_on_google_and_bing(tmp_path, fake):
    gather.run(gather.load_plan(_plan(tmp_path, [_angle()])), str(tmp_path / 'run.tsv'), str(tmp_path))
    for query in ('bank api sandbox uk', 'bank sandbox not available'):
        for engine in ('google', 'bing'):
            assert fake.ran('bd_search.py', query, engine, 'gb', 'en'), (query, engine)


def test_people_angles_also_ask_the_platforms_and_reddit(tmp_path, fake):
    gather.run(gather.load_plan(_plan(tmp_path, [_angle(people=True)])), str(tmp_path / 'run.tsv'), str(tmp_path))
    for platform in ('hn', 'stackexchange', 'githubissues', 'reddit'):
        assert fake.ran('platforms.py', platform), platform


def test_reddit_refused_falls_back_to_a_reddit_search_on_bright_data(tmp_path, fake):
    fake.platform[('reddit', 'bank api sandbox uk')] = 1
    gather.run(gather.load_plan(_plan(tmp_path, [_angle(people=True)])), str(tmp_path / 'run.tsv'), str(tmp_path))
    assert fake.ran('bd_search.py', 'site:reddit.com bank api sandbox uk')


def test_bright_data_refusing_stops_the_run(tmp_path, fake):
    fake.serp_exit = 2
    with pytest.raises(gather.SearchAborted) as err:
        gather.run(gather.load_plan(_plan(tmp_path, [_angle()])), str(tmp_path / 'run.tsv'), str(tmp_path))
    assert 'brightdata login' in str(err.value)


def test_a_failing_search_is_retried_once_then_recorded(tmp_path, fake, monkeypatch):
    real = fake.__call__
    failures = []

    def flaky(argv, timeout):
        if os.path.basename(argv[1]) == 'bd_search.py' and 'google' in argv:
            failures.append(argv)
            return 1, '', 'timeout'
        return real(argv, timeout)

    monkeypatch.setattr(gather, 'run_script', flaky)
    result = gather.run(gather.load_plan(_plan(tmp_path, [_angle()])), str(tmp_path / 'run.tsv'), str(tmp_path))
    assert len(failures) == 4  # two queries on google, each tried twice
    assert result['angles']['offer']['failed_searches'] == 2


# ---------------------------------------------------------------------------
# Open and log
# ---------------------------------------------------------------------------

def test_a_link_found_twice_is_opened_once_and_logged(tmp_path, fake):
    url = 'https://bank.example/sandbox'
    fake.serp[('bank api sandbox uk', 'google')] = [url]
    fake.serp[('bank api sandbox uk', 'bing')] = [url + '?utm_source=x']
    fake.pages[url] = 'The sandbox needs a test certificate.'
    tsv = str(tmp_path / 'run.tsv')
    gather.run(gather.load_plan(_plan(tmp_path, [_angle()])), tsv, str(tmp_path))
    assert len(fake.ran('fetch.py')) == 1
    rows = sources.read_rows(tsv)
    assert len(rows) == 1 and rows[0]['via'] == 'direct' and rows[0]['status'] == 'ok'
    assert rows[0]['angle'] == 'who offers a sandbox?' and rows[0]['query'] == 'bank api sandbox uk'


def test_a_blocked_page_climbs_the_ladder_and_the_refusal_is_logged(tmp_path, fake):
    url = 'https://bank.example/portal'
    fake.serp[('bank api sandbox uk', 'google')] = [url]
    fake.scrape[url] = 'Register an application to use the sandbox.'
    tsv = str(tmp_path / 'run.tsv')
    gather.run(gather.load_plan(_plan(tmp_path, [_angle()])), tsv, str(tmp_path))
    rows = sources.read_rows(tsv)
    assert [(r['via'], r['status']) for r in rows] == [('direct', 'blocked'), ('brightdata', 'ok')]


def test_a_page_nothing_opens_is_logged_blocked(tmp_path, fake):
    url = 'https://bank.example/locked'
    fake.serp[('bank api sandbox uk', 'google')] = [url]
    tsv = str(tmp_path / 'run.tsv')
    result = gather.run(gather.load_plan(_plan(tmp_path, [_angle()])), tsv, str(tmp_path))
    assert [r['status'] for r in sources.read_rows(tsv)] == ['blocked']
    assert result['angles']['offer']['blocked'] == 1


def test_one_link_in_two_angles_is_opened_once_and_logged_for_each(tmp_path, fake):
    url = 'https://bank.example/sandbox'
    fake.serp[('bank api sandbox uk', 'google')] = [url]
    fake.serp[('sandbox rules', 'google')] = [url]
    fake.pages[url] = 'text'
    tsv = str(tmp_path / 'run.tsv')
    angles = [_angle(), {'id': 'rules', 'question': 'what are the rules?', 'phrasings': ['sandbox rules']}]
    gather.run(gather.load_plan(_plan(tmp_path, angles)), tsv, str(tmp_path))
    assert len(fake.ran('fetch.py')) == 1
    assert sorted(r['angle'] for r in sources.read_rows(tsv)) == ['what are the rules?', 'who offers a sandbox?']


def test_urls_in_the_plan_are_opened_without_searching(tmp_path, fake):
    url = 'https://bank.example/item'
    fake.pages[url] = 'text'
    tsv = str(tmp_path / 'run.tsv')
    angle = {'id': 'list', 'question': 'rebuild the list', 'phrasings': [], 'urls': [url]}
    gather.run(gather.load_plan(_plan(tmp_path, [angle])), tsv, str(tmp_path))
    assert not fake.ran('bd_search.py') and fake.ran('fetch.py', url)


def test_the_time_limit_leaves_unopened_links_as_leads(tmp_path, fake):
    fake.serp[('bank api sandbox uk', 'google')] = ['https://a.example/1', 'https://b.example/2']
    tsv = str(tmp_path / 'run.tsv')
    result = gather.run(gather.load_plan(_plan(tmp_path, [_angle()])), tsv, str(tmp_path), time_limit=0)
    rows = sources.read_rows(tsv)
    assert {r['via'] for r in rows} == {'serp'} and len(rows) == 2
    assert result['angles']['offer']['not_reached'] == 2
