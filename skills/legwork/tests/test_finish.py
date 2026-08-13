"""Closing out a run in one call.

The gate, the staleness sweep and the index entry are the three things a run
has to do after the writing is done, which is when there is least attention
left for procedure. These tests pin the two rules that make one command safer
than three: a failing run is never filed, and the sweep reports conditionally
rather than guessing which claim a source backed.
"""

import os
import shutil
from datetime import datetime, timezone

import pytest

import finish
import index as index_module
from conftest import fixture

NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


@pytest.fixture
def run_dir(tmp_path):
    """A run laid out the way legwork writes one: <base>/<folder>/<base>.md."""
    def build(stem):
        base = tmp_path / 'research'
        folder = base / 'Topic_Research_20260812'
        folder.mkdir(parents=True)
        report = folder / 'Topic_Research_20260812.md'
        shutil.copy(fixture(stem + '.md'), report)
        tsv_source = fixture(stem + '.tsv')
        if os.path.exists(tsv_source):
            shutil.copy(tsv_source, folder / 'Topic_Research_20260812.tsv')
        return str(base), str(report)
    return build


# ---------------------------------------------------------------------------
# Format inference
# ---------------------------------------------------------------------------

def test_a_report_is_recognised_by_its_executive_summary():
    assert finish.infer_format('# T\n\n## Executive Summary\n\nx') == 'report'


def test_anything_without_one_is_treated_as_a_brief():
    assert finish.infer_format('# T\n\n## Findings\n\nx') == 'brief'


# ---------------------------------------------------------------------------
# Filing
# ---------------------------------------------------------------------------

def test_a_passing_run_is_filed(run_dir, monkeypatch):
    base, report = run_dir('valid_report')
    monkeypatch.setattr('sys.argv', ['finish', '--report', report, '--level', 'deep',
                                     '--topic', 'A settled question',
                                     '--one-liner', 'It settles this way'])
    with pytest.raises(SystemExit) as exit_info:
        finish.main()
    assert exit_info.value.code == 0

    entries = index_module.read_index(base)
    assert [e['folder'] for e in entries] == ['Topic_Research_20260812']
    assert entries[0]['one_liner'] == 'It settles this way'


def test_a_failing_run_is_not_filed(run_dir, monkeypatch):
    """The index is what a later session trusts instead of re-searching, so a
    run that could not clear its own gate must not appear in it."""
    base, report = run_dir('invalid_report')
    monkeypatch.setattr('sys.argv', ['finish', '--report', report, '--level', 'deep',
                                     '--topic', 'A question that failed',
                                     '--one-liner', 'Should never be filed'])
    with pytest.raises(SystemExit) as exit_info:
        finish.main()
    assert exit_info.value.code == 1
    assert index_module.read_index(base) == []


def test_filing_twice_updates_the_row_rather_than_adding_one(run_dir, monkeypatch):
    base, report = run_dir('valid_report')
    for one_liner in ('First conclusion', 'Revised conclusion'):
        monkeypatch.setattr('sys.argv', ['finish', '--report', report, '--level', 'deep',
                                         '--topic', 'A settled question',
                                         '--one-liner', one_liner])
        with pytest.raises(SystemExit):
            finish.main()

    entries = index_module.read_index(base)
    assert len(entries) == 1
    assert entries[0]['one_liner'] == 'Revised conclusion'


def test_a_passing_run_without_a_topic_is_left_unfiled(run_dir, monkeypatch):
    base, report = run_dir('valid_report')
    monkeypatch.setattr('sys.argv', ['finish', '--report', report, '--level', 'deep'])
    with pytest.raises(SystemExit) as exit_info:
        finish.main()
    assert exit_info.value.code == 0
    assert index_module.read_index(base) == []


# ---------------------------------------------------------------------------
# Staleness sweep
# ---------------------------------------------------------------------------

def test_the_sweep_reports_nothing_when_evidence_is_current():
    rows = [{'url': 'https://a.example/x', 'kind': 'vendor_pricing',
             'date': '2026-08-01', 'angle': 'what does it cost'}]
    assert finish.staleness_sweep(rows, ['price'], now=NOW) == []


def test_the_sweep_names_the_claim_kinds_whose_evidence_has_aged():
    """A pricing page from 2024 is well past a price horizon and comfortably
    inside a market one, which is the whole reason the horizon is per claim
    kind rather than one global number."""
    rows = [{'url': 'https://a.example/x', 'kind': 'vendor_pricing',
             'date': '2024-01-01', 'angle': 'what does it cost'}]
    flagged = {entry['claim_kind']
               for entry in finish.staleness_sweep(rows, ['price', 'market'], now=NOW)}
    assert 'price' in flagged
    assert 'market' not in flagged


def test_the_base_is_inferred_from_the_run_folder(tmp_path):
    report = tmp_path / 'research' / 'Topic_Research_20260812' / 'Topic_Research_20260812.md'
    assert finish.default_base(str(report)) == str(tmp_path / 'research')
