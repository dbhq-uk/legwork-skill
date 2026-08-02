"""Report-wide source concentration.

Per-finding independence can pass on every finding while the document as a whole
rests on one party. These tests pin the property that makes that visible.
"""

import pytest

import independence


def row(url, angle='an angle', title='', kind='press'):
    return {'url': url, 'angle': angle, 'title': title, 'kind': kind, 'status': 'ok'}


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------

def test_portfolio_reports_counts_over_the_whole_run():
    rows = [
        row('https://a.example/1', angle='one'),
        row('https://b.example/2', angle='two'),
        row('https://c.example/3', angle='three'),
    ]
    result = independence.portfolio(rows)
    assert result['sources'] == 3
    assert result['groups'] == 3
    assert result['parties'] == 3
    assert result['angles'] == 3


def test_portfolio_of_an_empty_log_is_all_zero_and_does_not_divide_by_zero():
    result = independence.portfolio([])
    assert result['sources'] == 0
    assert result['groups'] == 0
    assert result['top_party_share'] == 0.0
    assert result['top_group_share'] == 0.0


# ---------------------------------------------------------------------------
# Concentration - the property this exists for
# ---------------------------------------------------------------------------

def test_one_party_supplying_most_of_the_run_shows_up_as_a_high_share():
    rows = [row('https://vendor.example/p{}'.format(i), angle='angle {}'.format(i)) for i in range(8)]
    rows.append(row('https://other.example/x', angle='different'))
    result = independence.portfolio(rows)
    assert result['top_party'] == 'vendor.example'
    assert result['top_party_share'] == pytest.approx(8 / 9, abs=0.01)


def test_share_is_counted_on_sources_not_on_groups():
    """Eight pages from one vendor collapse to one group. The share must still
    report that eight of the nine retrievals came from that vendor, or a run
    dominated by one party looks balanced at group level."""
    rows = [row('https://vendor.example/p{}'.format(i), angle='angle {}'.format(i)) for i in range(8)]
    rows.append(row('https://other.example/x', angle='different'))
    result = independence.portfolio(rows)
    assert result['groups'] == 2
    assert result['top_party_share'] > 0.8


def test_a_balanced_run_has_a_low_top_share():
    rows = [row('https://p{}.example/x'.format(i), angle='angle {}'.format(i)) for i in range(10)]
    result = independence.portfolio(rows)
    assert result['top_party_share'] == pytest.approx(0.1, abs=0.01)


def test_subdomains_of_one_party_count_as_that_party():
    rows = [
        row('https://learn.microsoft.com/a', angle='one'),
        row('https://azure.microsoft.com/b', angle='two'),
        row('https://devblogs.microsoft.com/c', angle='three'),
        row('https://other.example/d', angle='four'),
    ]
    result = independence.portfolio(rows)
    assert result['top_party'] == 'microsoft.com'
    assert result['top_party_share'] == pytest.approx(0.75, abs=0.01)


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

def test_concentration_above_the_limit_fails_the_check():
    rows = [row('https://vendor.example/p{}'.format(i), angle='a{}'.format(i)) for i in range(9)]
    rows.append(row('https://other.example/x', angle='z'))
    result = independence.portfolio(rows, max_party_share=0.5, min_parties=2)
    assert result['passed'] is False
    assert any('vendor.example' in reason for reason in result['failures'])


def test_too_few_distinct_parties_fails_the_check():
    rows = [
        row('https://a.example/1', angle='one'),
        row('https://b.example/2', angle='two'),
    ]
    result = independence.portfolio(rows, max_party_share=0.9, min_parties=5)
    assert result['passed'] is False
    assert any('parties' in reason for reason in result['failures'])


def test_many_parties_all_carrying_one_story_is_still_a_concentrated_run():
    """Six outlets syndicating one wire story are six parties and one voice.
    Party share alone reports that as perfectly balanced, which is the exact
    illusion the independence layer exists to strip."""
    rows = [
        row('https://outlet{}.example/x'.format(i),
            angle='angle {}'.format(i),
            title='Regulator opens consultation on record keeping duties')
        for i in range(6)
    ]
    result = independence.portfolio(rows, max_party_share=0.9, min_parties=2)
    assert result['parties'] == 6
    assert result['groups'] == 1
    assert result['top_group_share'] == 1.0
    assert result['passed'] is False
    assert any('one voice' in reason or 'group' in reason for reason in result['failures'])


def test_a_diverse_run_passes_both_thresholds():
    rows = [row('https://p{}.example/x'.format(i), angle='angle {}'.format(i)) for i in range(6)]
    result = independence.portfolio(rows, max_party_share=0.5, min_parties=5)
    assert result['passed'] is True
    assert result['failures'] == []
