"""The gate's view of the matrix and the index.

Both are self-enforcing on purpose. A matrix the gate never looks at drifts into
blank cells; an index nothing checks stays empty, and an index nobody writes to
is the same as no index at all.
"""

import os

import check
from conftest import fixture


def report_with(tmp_path, extra, name='r.md'):
    """A valid report with an extra section spliced in before Findings."""
    source = open(fixture('valid_report.md'), encoding='utf-8').read()
    target = tmp_path / name
    target.write_text(source.replace('## Findings', extra + '\n## Findings', 1), encoding='utf-8')
    log = tmp_path / (os.path.splitext(name)[0] + '.tsv')
    log.write_text(open(fixture('valid_report.tsv'), encoding='utf-8').read(), encoding='utf-8')
    return str(target), str(log)


COMPLETE_MATRIX = """## Comparison matrix

| Vendor | Price | Native triage |
|---|---|---|
| Acme | 30 USD/seat [1] | No [2] |
| Contoso | [unknown] | Yes [2] |

"""

BLANK_CELL_MATRIX = """## Comparison matrix

| Vendor | Price | Native triage |
|---|---|---|
| Acme | 30 USD/seat [1] |  |
| Contoso | [unknown] | Yes [2] |

"""

UNCITED_MATRIX = """## Comparison matrix

| Vendor | Price | Native triage |
|---|---|---|
| Acme | 30 USD/seat | No |
| Contoso | [unknown] | Yes [2] |

"""


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------

def test_a_report_with_no_matrix_is_unaffected():
    problems, _ = check.run(fixture('valid_report.md'), fixture('valid_report.tsv'), 'report', 'deep')
    assert problems.errors == [], problems.errors


def test_a_complete_matrix_passes(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    problems, _ = check.run(report, log, 'report', 'deep')
    assert problems.errors == [], problems.errors


def test_a_blank_cell_fails(tmp_path):
    report, log = report_with(tmp_path, BLANK_CELL_MATRIX)
    problems, _ = check.run(report, log, 'report', 'deep')
    assert any('blank' in e and 'Acme' in e for e in problems.errors), problems.errors


def test_a_row_stating_values_with_no_citation_fails(tmp_path):
    report, log = report_with(tmp_path, UNCITED_MATRIX)
    problems, _ = check.run(report, log, 'report', 'deep')
    assert any('no citation' in e and 'Acme' in e for e in problems.errors), problems.errors


def test_matrix_problems_are_graded_like_the_rest(tmp_path):
    report, log = report_with(tmp_path, BLANK_CELL_MATRIX)
    standard, _ = check.run(report, log, 'report', 'standard')
    assert any('blank' in w for w in standard.warnings)
    assert not any('blank' in e for e in standard.errors)


# ---------------------------------------------------------------------------
# Index registration
# ---------------------------------------------------------------------------

def test_no_index_means_no_complaint(tmp_path):
    """The index is opt-in. A user who never made one must not be nagged."""
    run_dir = tmp_path / 'Topic_Research_20260802'
    run_dir.mkdir()
    report = run_dir / 'Topic_Research_20260802.md'
    report.write_text(open(fixture('valid_report.md'), encoding='utf-8').read(), encoding='utf-8')
    log = run_dir / 'Topic_Research_20260802.tsv'
    log.write_text(open(fixture('valid_report.tsv'), encoding='utf-8').read(), encoding='utf-8')
    problems, _ = check.run(str(report), str(log), 'report', 'deep')
    assert not any('index' in m for m in problems.errors + problems.warnings)


def test_an_unregistered_run_is_flagged_once_an_index_exists(tmp_path):
    (tmp_path / 'index.md').write_text(
        '# Research index\n\n| Topic | Folder | Level | Last verified | One-liner |\n'
        '|---|---|---|---|---|\n| Other | Other_Research_20260701 | deep | 2026-07-01 | x |\n',
        encoding='utf-8')
    run_dir = tmp_path / 'Topic_Research_20260802'
    run_dir.mkdir()
    report = run_dir / 'Topic_Research_20260802.md'
    report.write_text(open(fixture('valid_report.md'), encoding='utf-8').read(), encoding='utf-8')
    log = run_dir / 'Topic_Research_20260802.tsv'
    log.write_text(open(fixture('valid_report.tsv'), encoding='utf-8').read(), encoding='utf-8')
    problems, _ = check.run(str(report), str(log), 'report', 'deep')
    assert any('index' in m for m in problems.errors + problems.warnings), problems.warnings


def test_a_registered_run_is_not_flagged(tmp_path):
    (tmp_path / 'index.md').write_text(
        '# Research index\n\n| Topic | Folder | Level | Last verified | One-liner |\n'
        '|---|---|---|---|---|\n| Topic | Topic_Research_20260802 | deep | 2026-08-02 | x |\n',
        encoding='utf-8')
    run_dir = tmp_path / 'Topic_Research_20260802'
    run_dir.mkdir()
    report = run_dir / 'Topic_Research_20260802.md'
    report.write_text(open(fixture('valid_report.md'), encoding='utf-8').read(), encoding='utf-8')
    log = run_dir / 'Topic_Research_20260802.tsv'
    log.write_text(open(fixture('valid_report.tsv'), encoding='utf-8').read(), encoding='utf-8')
    problems, _ = check.run(str(report), str(log), 'report', 'deep')
    assert not any('index' in m for m in problems.errors + problems.warnings)


def test_registration_is_a_warning_not_an_error_even_at_deep(tmp_path):
    """Filing is housekeeping. It should nag, never block a sound deliverable."""
    (tmp_path / 'index.md').write_text(
        '# Research index\n\n| Topic | Folder | Level | Last verified | One-liner |\n'
        '|---|---|---|---|---|\n| Other | Other_Research_20260701 | deep | 2026-07-01 | x |\n',
        encoding='utf-8')
    run_dir = tmp_path / 'Topic_Research_20260802'
    run_dir.mkdir()
    report = run_dir / 'Topic_Research_20260802.md'
    report.write_text(open(fixture('valid_report.md'), encoding='utf-8').read(), encoding='utf-8')
    log = run_dir / 'Topic_Research_20260802.tsv'
    log.write_text(open(fixture('valid_report.tsv'), encoding='utf-8').read(), encoding='utf-8')
    problems, _ = check.run(str(report), str(log), 'report', 'deep')
    assert any('index' in w for w in problems.warnings)
    assert problems.errors == []
