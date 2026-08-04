"""Staleness, measured against the half-life the claim kind already carries.

`sources.py` models decay per claim kind but nothing ever asked it whether the
evidence behind a run has gone off. These tests pin that question.
"""

from datetime import datetime, timedelta, timezone

import pytest

import sources


NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


def row(url, date='', kind='press', angle='an angle'):
    return {'url': url, 'date': date, 'kind': kind, 'angle': angle, 'status': 'ok'}


def days_ago(n):
    return (NOW - timedelta(days=n)).date().isoformat()


# ---------------------------------------------------------------------------
# The horizon
# ---------------------------------------------------------------------------

def test_horizon_is_a_multiple_of_the_claim_kinds_half_life():
    # price halves every 180 days, market every 1095.
    assert sources.staleness_horizon_days('price', half_lives=2) == 360
    assert sources.staleness_horizon_days('market', half_lives=2) == 2190


def test_an_unknown_claim_kind_falls_back_to_general():
    assert (sources.staleness_horizon_days('nonsense', half_lives=1)
            == sources.staleness_horizon_days('general', half_lives=1))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_a_fresh_source_is_current():
    result = sources.freshness(row('https://a.example/x', date=days_ago(10)), 'price', now=NOW)
    assert result['state'] == 'current'


def test_a_price_source_older_than_two_half_lives_is_stale():
    result = sources.freshness(row('https://a.example/x', date=days_ago(400)), 'price', now=NOW)
    assert result['state'] == 'stale'
    assert result['age_days'] == pytest.approx(400, abs=1)


def test_the_same_age_is_fine_for_a_slower_moving_claim():
    """A 400-day-old pricing page is worthless; a 400-day-old filing is fine.
    This is the whole reason the horizon is per claim kind."""
    result = sources.freshness(row('https://a.example/x', date=days_ago(400)), 'market', now=NOW)
    assert result['state'] == 'current'


def test_a_source_with_no_date_is_undated_not_stale():
    """Undated and stale are different problems with different fixes: one needs
    a date recorded, the other needs a newer source."""
    result = sources.freshness(row('https://a.example/x', date=''), 'price', now=NOW)
    assert result['state'] == 'undated'
    assert result['age_days'] is None


def test_an_unparseable_date_is_undated():
    result = sources.freshness(row('https://a.example/x', date='last spring'), 'price', now=NOW)
    assert result['state'] == 'undated'


# ---------------------------------------------------------------------------
# Over a whole log
# ---------------------------------------------------------------------------

def test_audit_splits_a_log_into_current_stale_and_undated():
    rows = [
        row('https://a.example/1', date=days_ago(5)),
        row('https://b.example/2', date=days_ago(900)),
        row('https://c.example/3', date=''),
    ]
    result = sources.freshness_audit(rows, 'price', now=NOW)
    assert result['current'] == 1
    assert result['stale'] == 1
    assert result['undated'] == 1
    assert len(result['flagged']) == 2


def test_audit_of_an_all_fresh_log_flags_nothing():
    rows = [row('https://a.example/{}'.format(i), date=days_ago(3)) for i in range(4)]
    result = sources.freshness_audit(rows, 'price', now=NOW)
    assert result['flagged'] == []
    assert result['stale'] == 0
