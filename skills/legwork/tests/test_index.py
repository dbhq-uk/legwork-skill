"""The research index: a dispatcher so the next run can find the last one.

A report that never reaches the index is a report the next session cannot find,
and the next session re-runs it. These tests pin the table's identity rules.
"""

from datetime import datetime, timezone

import pytest

import index


NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)

TABLE = """# Research index

| Topic | Folder | Level | Last verified | One-liner |
|---|---|---|---|---|
| Outlook triage | Outlook_Research_20260728 | deep | 2026-07-28 | No native triage below E5 |
| Plugin gallery | Plugin_Research_20260714 | standard | 2026-07-14 | No submission route exists |
"""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_an_absent_index_parses_as_empty_rather_than_raising():
    assert index.parse_index('') == []


def test_rows_come_back_with_every_column():
    entries = index.parse_index(TABLE)
    assert len(entries) == 2
    assert entries[0] == {
        'topic': 'Outlook triage',
        'folder': 'Outlook_Research_20260728',
        'level': 'deep',
        'verified': '2026-07-28',
        'one_liner': 'No native triage below E5',
    }


def test_the_header_and_separator_rows_are_not_entries():
    entries = index.parse_index(TABLE)
    assert all(entry['folder'] not in ('Folder', '---') for entry in entries)


def test_a_topic_that_collides_with_a_column_heading_is_still_an_entry():
    """The header is the first row, not any row whose first cell reads 'Topic'.
    Identifying it by content silently drops a real run."""
    entries = index.parse_index(
        '# Research index\n\n'
        '| Topic | Folder | Level | Last verified | One-liner |\n'
        '|---|---|---|---|---|\n'
        '| Topic | Topic_Research_20260802 | deep | 2026-08-02 | A real run |\n')
    assert [entry['folder'] for entry in entries] == ['Topic_Research_20260802']


def test_a_round_trip_preserves_every_entry():
    entries = index.parse_index(TABLE)
    assert index.parse_index(index.render_index(entries)) == entries


# ---------------------------------------------------------------------------
# Upsert - identity is the folder, because topics get reworded
# ---------------------------------------------------------------------------

def test_a_new_folder_is_appended():
    entries = index.parse_index(TABLE)
    updated = index.upsert(entries, {
        'topic': 'Pricing scan', 'folder': 'Pricing_Research_20260802',
        'level': 'quick', 'verified': '2026-08-02', 'one_liner': 'Three vendors, one price point'})
    assert len(updated) == 3
    assert updated[-1]['folder'] == 'Pricing_Research_20260802'


def test_re_running_the_same_folder_updates_in_place_rather_than_duplicating():
    """A refresh must not leave two rows competing to describe one folder."""
    entries = index.parse_index(TABLE)
    updated = index.upsert(entries, {
        'topic': 'Outlook triage', 'folder': 'Outlook_Research_20260728',
        'level': 'deep', 'verified': '2026-08-02', 'one_liner': 'Now shipping natively on Business Premium'})
    assert len(updated) == 2
    assert updated[0]['verified'] == '2026-08-02'
    assert updated[0]['one_liner'] == 'Now shipping natively on Business Premium'


def test_upsert_keeps_the_original_position_on_refresh():
    entries = index.parse_index(TABLE)
    updated = index.upsert(entries, {
        'topic': 'Outlook triage', 'folder': 'Outlook_Research_20260728',
        'level': 'deep', 'verified': '2026-08-02', 'one_liner': 'Changed'})
    assert updated[0]['folder'] == 'Outlook_Research_20260728'


def test_a_pipe_in_a_one_liner_cannot_break_the_table():
    entries = index.upsert([], {
        'topic': 'A topic', 'folder': 'F_20260802', 'level': 'quick',
        'verified': '2026-08-02', 'one_liner': 'Costs 30 | 40 depending on tier'})
    rendered = index.render_index(entries)
    assert index.parse_index(rendered)[0]['one_liner'] == 'Costs 30 / 40 depending on tier'


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------

def test_entries_older_than_the_horizon_are_flagged():
    entries = index.parse_index(TABLE)
    stale = index.stale_entries(entries, days=15, now=NOW)
    assert [entry['folder'] for entry in stale] == ['Plugin_Research_20260714']


def test_nothing_is_stale_under_a_generous_horizon():
    entries = index.parse_index(TABLE)
    assert index.stale_entries(entries, days=365, now=NOW) == []


def test_an_entry_with_an_unreadable_date_is_treated_as_stale():
    """Unknown age is not the same as fresh, and defaulting to fresh is how a
    three-year-old entry gets quoted as current truth."""
    entries = [{'topic': 'T', 'folder': 'F', 'level': 'quick',
                'verified': 'sometime', 'one_liner': 'x'}]
    assert index.stale_entries(entries, days=30, now=NOW) == entries
