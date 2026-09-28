"""facts.py - every fact held to the standard of its kind."""

import argparse
import json

import pytest

import facts
import sources


def _run(tmp_path, passages, subjects=None):
    """A run folder: pages, the ids file, a log row per page, a round-2 plan."""
    tsv = tmp_path / 'run.tsv'
    ids = {}
    for passage_id, (url, party, text) in passages.items():
        page = tmp_path / (passage_id + '.txt')
        page.write_text(text, encoding='utf-8')
        ids[passage_id] = {'url': url, 'party': party, 'text': text, 'text_file': str(page)}
        sources.log_row(argparse.Namespace(
            tsv=str(tsv), url=url, kind=None, angle='a', via='direct', status='ok', quote='', title='',
            date='', text_file=str(page), numbers='', query='', from_fetch=None))
    (tmp_path / 'run.ids.json').write_text(json.dumps(ids), encoding='utf-8')
    plan = {'round': 2, 'angles': [{'id': s.lower(), 'question': 'q', 'subject': s, 'sites': sites, 'expected': True}
                                   for s, sites in (subjects or {}).items()]}
    (tmp_path / 'plan-2.json').write_text(json.dumps(plan), encoding='utf-8')
    return str(tsv)


def _add(tmp_path, tsv, fact_list):
    path = tmp_path / 'new.json'
    path.write_text(json.dumps(fact_list), encoding='utf-8')
    try:
        facts.main(['add', '--tsv', tsv, '--file', str(path)])
    except SystemExit:
        pass
    return facts.check_facts(tsv)


OWN = 'Render Postgres starts at $6 per month for the Basic instance.'
REVIEW = 'Render Postgres costs $7 per month on its cheapest paid plan.'


def test_an_own_fact_resting_on_a_review_fails(tmp_path):
    """Graded 2026-09-27: most wrong facts came from a review standing in for the entity's own page."""
    tsv = _run(tmp_path, {'r2-render-1': ('https://reviews.example/pg', 'reviews.example', REVIEW)},
               {'Render': ['render.com']})
    errors, _, _ = _add(tmp_path, tsv, [{'entity': 'Render', 'kind': 'own', 'claim': 'Render costs $7 a month',
                                         'sources': [{'id': 'r2-render-1', 'quote': REVIEW}]}])
    assert any('own site' in e for e in errors)


def test_an_own_fact_quoting_its_own_site_passes(tmp_path):
    tsv = _run(tmp_path, {'r2-render-1': ('https://render.com/pricing', 'render.com', OWN)},
               {'Render': ['render.com']})
    errors, _, _ = _add(tmp_path, tsv, [{'entity': 'Render', 'kind': 'own', 'claim': 'Render Postgres costs $6 a month',
                                         'sources': [{'id': 'r2-render-1', 'quote': OWN}]}])
    assert errors == []
    assert sources.read_rows(tsv)[0]['verified'] == 'true'


def test_a_price_its_own_site_does_not_show_must_be_resolved(tmp_path):
    """Tested 2026-09-28: Render's $7 was wrong against a $6 page on its own site."""
    tsv = _run(tmp_path, {'r2-render-1': ('https://render.com/pricing', 'render.com', OWN),
                          'r2-render-2': ('https://reviews.example/pg', 'reviews.example', REVIEW)},
               {'Render': ['render.com']})
    fact = {'entity': 'Render', 'kind': 'own', 'claim': 'Render Postgres costs $7 a month',
            'sources': [{'id': 'r2-render-1', 'quote': 'Render Postgres starts at'}]}
    errors, _, _ = _add(tmp_path, tsv, [fact])
    assert any('r2-render-1' in e and 'status' in e for e in errors)
    errors, notes, _ = _add(tmp_path, tsv, [dict(fact, status='contested')])
    assert not any('status' in e for e in errors) and any('contested' in n for n in notes)


def test_a_quote_not_on_its_page_fails(tmp_path):
    tsv = _run(tmp_path, {'r2-render-1': ('https://render.com/pricing', 'render.com', OWN)},
               {'Render': ['render.com']})
    errors, _, _ = _add(tmp_path, tsv, [{'entity': 'Render', 'kind': 'own', 'claim': 'x',
                                         'sources': [{'id': 'r2-render-1', 'quote': 'Render is free forever'}]}])
    assert any('not on its page' in e for e in errors)


LINE = 'Most small practices still triage email by hand, a survey of 400 firms found.'


def test_a_world_fact_carried_by_two_sites_in_the_same_words_is_one_source(tmp_path):
    tsv = _run(tmp_path, {'r1-a-1': ('https://news.example/a', 'news.example', LINE),
                          'r1-a-2': ('https://blog.example/b', 'blog.example', LINE)})
    errors, _, _ = _add(tmp_path, tsv, [{'entity': 'practices', 'kind': 'world', 'claim': 'most triage by hand',
                                         'sources': [{'id': 'r1-a-1', 'quote': LINE}, {'id': 'r1-a-2', 'quote': LINE}]}])
    assert any('two independent sources' in e for e in errors)


def test_a_world_fact_from_two_independent_sources_passes(tmp_path):
    other = 'In our client base, nine in ten accountants sort their inbox manually.'
    tsv = _run(tmp_path, {'r1-a-1': ('https://news.example/a', 'news.example', LINE),
                          'r1-a-2': ('https://vendor.example/b', 'vendor.example', other)})
    errors, _, _ = _add(tmp_path, tsv, [{'entity': 'practices', 'kind': 'world', 'claim': 'most triage by hand',
                                         'sources': [{'id': 'r1-a-1', 'quote': LINE}, {'id': 'r1-a-2', 'quote': other}]}])
    assert errors == []


def test_adding_a_fact_again_replaces_it(tmp_path):
    tsv = _run(tmp_path, {'r2-render-1': ('https://render.com/pricing', 'render.com', OWN)},
               {'Render': ['render.com']})
    fact = {'entity': 'Render', 'kind': 'own', 'claim': 'Render Postgres costs $6 a month',
            'sources': [{'id': 'r2-render-1', 'quote': OWN}]}
    _add(tmp_path, tsv, [fact])
    _, _, kept = _add(tmp_path, tsv, [fact])
    assert len(kept) == 1


def test_distinctive_skips_generic_words():
    assert facts.distinctive('Bank of Ireland UK') == 'ireland'
    assert facts.names('Lloyds Banking Group', 'Lloyds')


@pytest.mark.parametrize('kind', ['', 'maybe'])
def test_a_fact_needs_a_known_kind(tmp_path, kind):
    tsv = _run(tmp_path, {'r2-render-1': ('https://render.com/pricing', 'render.com', OWN)})
    errors, _, _ = _add(tmp_path, tsv, [{'entity': 'Render', 'kind': kind, 'claim': 'x',
                                         'sources': [{'id': 'r2-render-1', 'quote': OWN}]}])
    assert any('kind' in e for e in errors)
