"""Two ways a report with no evidence trail was passing the gate.

Both found by the model sweep on 2026-08-13, not by reading the source. A Haiku
run shipped a comparison matrix in which five of seven rows cited nothing, wrote
its fetch log under a name the gate did not look for, and was reported - and
reported itself - as passing.

Neither failure was in the checks. Both were in what the checks were allowed to
see, and how loudly they were allowed to complain.
"""

import os

import pytest

import check
import matrix


MATRIX_UNCITED = """# Providers

*standard - 3 angles, 4 sources*

## Findings

### Finding 1: The cheap tier is crowded

Several providers cluster at the low end [1].

## Comparison matrix

| Provider | Entry price | Region |
|---|---|---|
| Acme | 15 USD/mo | London |
| Rival | 12 USD/mo | Frankfurt |

## Limitations

Prices move.

## Bibliography

[1] A roundup https://aggregator.example/roundup
"""

MATRIX_CITED = MATRIX_UNCITED.replace(
    '| Acme | 15 USD/mo | London |',
    '| Acme | 15 USD/mo [1] | London [1] |').replace(
    '| Rival | 12 USD/mo | Frankfurt |',
    '| Rival | 12 USD/mo [1] | Frankfurt [1] |')


# ---------------------------------------------------------------------------
# An uncited matrix row is structural, not evidential
# ---------------------------------------------------------------------------

def test_uncited_rows_are_reported_separately():
    parsed = matrix.parse_matrix(MATRIX_UNCITED)
    result = matrix.check_matrix(parsed)
    assert len(result['uncited_rows']) == 2
    for message in result['uncited_rows']:
        assert message in result['problems']


def test_a_cited_matrix_has_no_uncited_rows():
    parsed = matrix.parse_matrix(MATRIX_CITED)
    assert matrix.check_matrix(parsed)['uncited_rows'] == []


@pytest.mark.parametrize('level', ['quick', 'standard', 'deep'])
def test_a_matrix_citing_nothing_fails_at_every_level(tmp_path, level):
    """It used to pass at standard, because it was graded as a judgement about
    evidence strength. It is not - it is the absence of any evidence at all, and
    the prose equivalent has always been structural."""
    report = tmp_path / 'r.md'
    report.write_text(MATRIX_UNCITED, encoding='utf-8')
    problems, _ = check.run(str(report), None, 'brief', level)
    assert any('carries no citation anywhere' in message for message in problems.errors), \
        'uncited matrix rows must be errors at {}'.format(level)


def test_a_blank_cell_stays_graded(tmp_path):
    """The strictness change must be narrow. A blank cell is still a judgement
    the level table is entitled to grade."""
    blank = MATRIX_UNCITED.replace('| Acme | 15 USD/mo | London |', '| Acme |  | London |')
    report = tmp_path / 'r.md'
    report.write_text(blank, encoding='utf-8')
    problems, _ = check.run(str(report), None, 'brief', 'standard')
    assert any('blank' in message for message in problems.warnings)


# ---------------------------------------------------------------------------
# Finding the fetch log
# ---------------------------------------------------------------------------

def test_the_base_name_log_is_preferred(tmp_path):
    (tmp_path / 'run.md').write_text('# r', encoding='utf-8')
    (tmp_path / 'run.tsv').write_text('url\n', encoding='utf-8')
    assert check.discover_tsv(str(tmp_path / 'run.md')) == str(tmp_path / 'run.tsv')


def test_a_differently_named_log_is_still_found(tmp_path):
    """The measured failure: a run wrote sources.tsv, the gate looked only for
    run.tsv, found nothing, and skipped every citation check in silence."""
    (tmp_path / 'run.md').write_text('# r', encoding='utf-8')
    (tmp_path / 'sources.tsv').write_text('url\n', encoding='utf-8')
    assert check.discover_tsv(str(tmp_path / 'run.md')) == str(tmp_path / 'sources.tsv')


def test_two_logs_are_ambiguous_and_neither_is_guessed(tmp_path):
    (tmp_path / 'run.md').write_text('# r', encoding='utf-8')
    (tmp_path / 'a.tsv').write_text('url\n', encoding='utf-8')
    (tmp_path / 'b.tsv').write_text('url\n', encoding='utf-8')
    assert check.discover_tsv(str(tmp_path / 'run.md')) is None


def test_no_log_at_all_is_none(tmp_path):
    (tmp_path / 'run.md').write_text('# r', encoding='utf-8')
    assert check.discover_tsv(str(tmp_path / 'run.md')) is None
