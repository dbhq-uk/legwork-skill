"""The shippability gate."""

import os
import shutil

import pytest

import check
from conftest import fixture


def run(name, level='deep', fmt='report', tsv=None):
    report = fixture(name)
    if tsv is None:
        candidate = os.path.splitext(report)[0] + '.tsv'
        tsv = candidate if os.path.exists(candidate) else None
    return check.run(report, tsv, fmt, level)


def messages(problems):
    return ' | '.join(problems.errors + problems.warnings)


# ---------------------------------------------------------------------------
# The two ends of the gate
# ---------------------------------------------------------------------------

def test_a_sound_report_passes_at_the_strictest_level():
    problems, summary = run('valid_report.md', level='deep')
    assert problems.errors == [], problems.errors
    assert summary['sources'] == 3


def test_the_fixture_that_is_meant_to_fail_still_fails():
    """This is what makes 'the gate is proved to bite' true rather than assumed."""
    problems, _ = run('invalid_report.md', level='deep')
    assert problems.errors


@pytest.mark.parametrize('needle', [
    'placeholder text present',
    'truncation marker present',
    'no inline [N] citations',
    'missing section: Introduction',
])
def test_the_invalid_fixture_fails_for_each_reason_it_should(needle):
    problems, _ = run('invalid_report.md', level='deep')
    assert needle in messages(problems)


# ---------------------------------------------------------------------------
# Anti-fabrication
# ---------------------------------------------------------------------------

def test_citing_a_page_that_was_never_fetched_fails():
    problems, _ = run('unfetched_citation.md', level='deep')
    assert any('never fetched' in error for error in problems.errors)


def test_the_unfetched_check_is_a_warning_at_standard_and_an_error_at_deep():
    standard, _ = run('unfetched_citation.md', level='standard')
    deep, _ = run('unfetched_citation.md', level='deep')
    assert any('never fetched' in w for w in standard.warnings)
    assert not any('never fetched' in e for e in standard.errors)
    assert any('never fetched' in e for e in deep.errors)


def test_quick_level_runs_structure_only():
    problems, _ = run('unfetched_citation.md', level='quick')
    assert problems.errors == []


# ---------------------------------------------------------------------------
# Independence
# ---------------------------------------------------------------------------

def test_a_strong_finding_backed_by_one_line_of_enquiry_fails():
    problems, _ = run('one_origin.md', level='deep')
    assert any('claims strong confidence' in error for error in problems.errors)


def test_the_failure_names_the_group_and_angle_counts():
    problems, _ = run('one_origin.md', level='deep')
    error = next(e for e in problems.errors if 'claims strong confidence' in e)
    assert '5 independent group(s)' in error
    assert '1 angle(s)' in error


def test_downgrading_the_same_finding_to_weak_makes_it_shippable(tmp_path):
    source = fixture('one_origin.md')
    target = tmp_path / 'downgraded.md'
    target.write_text(open(source, encoding='utf-8').read().replace(
        '**Confidence: Strong**', '**Confidence: Weak**'), encoding='utf-8')
    shutil.copy(fixture('one_origin.tsv'), tmp_path / 'downgraded.tsv')
    problems, _ = check.run(str(target), str(tmp_path / 'downgraded.tsv'), 'report', 'deep')
    assert problems.errors == [], problems.errors


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def test_a_figure_absent_from_every_cited_page_fails(tmp_path):
    source = fixture('valid_report.md')
    target = tmp_path / 'bad_figure.md'
    target.write_text(open(source, encoding='utf-8').read().replace(
        'a gap of 60 percent', 'a gap of 85 percent'), encoding='utf-8')
    shutil.copy(fixture('valid_report.tsv'), tmp_path / 'bad_figure.tsv')
    problems, _ = check.run(str(target), str(tmp_path / 'bad_figure.tsv'), 'report', 'deep')
    assert any('85' in error and 'figures not found' in error for error in problems.errors)


def test_small_prose_counts_are_not_traced():
    assert check.traced_figures('Three of the five practices agreed [1].') == set()


def test_percentages_are_traced_however_small():
    assert '5' in check.traced_figures('Adoption sits at 5% today [1].')


def test_citation_markers_are_never_mistaken_for_figures():
    assert check.traced_figures('The claim holds [12][34].') == set()


# ---------------------------------------------------------------------------
# The honest empty outcome
# ---------------------------------------------------------------------------

def test_a_could_not_answer_report_is_a_valid_outcome_not_a_failure():
    problems, summary = run('could_not_answer.md', level='deep')
    assert problems.errors == [], problems.errors
    assert summary['outcome'] == 'could-not-answer'


def test_could_not_answer_must_name_the_closest_thing_found(tmp_path):
    source = open(fixture('could_not_answer.md'), encoding='utf-8').read()
    target = tmp_path / 'nameless.md'
    target.write_text(source.replace('Closest thing found:', 'Nothing else to report:'), encoding='utf-8')
    problems, _ = check.run(str(target), None, 'report', 'deep')
    assert any('closest' in error.lower() for error in problems.errors)


def test_could_not_answer_cannot_also_ship_findings(tmp_path):
    source = open(fixture('could_not_answer.md'), encoding='utf-8').read()
    target = tmp_path / 'hedged.md'
    target.write_text(source + '\n\n## Finding 1: A finding that should not be here\n\nText [1].\n',
                      encoding='utf-8')
    problems, _ = check.run(str(target), None, 'report', 'deep')
    assert any('must not also ship findings' in error for error in problems.errors)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def test_the_bibliography_is_excluded_from_the_inline_citation_check():
    body, bibliography = check.split_bibliography(
        '# T\n\nProse with no marker.\n\n## Bibliography\n\n[1] A. https://a.example/\n')
    assert '[1]' not in body
    assert '[1]' in bibliography


def test_a_multi_line_bibliography_entry_keeps_its_url():
    entries = check.parse_bibliography('[1] Someone (2026). "A long title\nthat wrapped". https://a.example/x\n')
    assert entries[1]['url'] == 'https://a.example/x'


def test_findings_are_found_at_either_heading_level():
    two = check.finding_sections('## Finding 1: A\n\nText.\n')
    three = check.finding_sections('### Finding 1: A\n\nText.\n')
    assert len(two) == len(three) == 1


def test_a_finding_section_stops_at_the_next_heading():
    sections = check.finding_sections(
        '### Finding 1: A\n\nInside.\n\n## Synthesis\n\nOutside.\n')
    assert 'Inside' in sections[0]['text']
    assert 'Outside' not in sections[0]['text']


# ---------------------------------------------------------------------------
# Quotes. Roughly half of real findings carry no figure at all, so figure
# tracing alone leaves them checked only by "somebody opened the page".
# ---------------------------------------------------------------------------

def test_a_finding_with_no_figure_and_no_quote_fails():
    problems, _ = run('no_evidence.md', level='deep')
    assert any('rests on no recorded evidence' in error for error in problems.errors)


def test_a_quote_is_enough_on_its_own_for_a_qualitative_finding(tmp_path):
    """No figure anywhere in the finding, but a cited source carries a quote."""
    import shutil
    report = tmp_path / 'quoted.md'
    report.write_text(open(fixture('no_evidence.md'), encoding='utf-8').read(), encoding='utf-8')
    log = tmp_path / 'quoted.tsv'
    shutil.copy(fixture('no_evidence.tsv'), log)
    text = log.read_text(encoding='utf-8').rstrip('\n')
    log.write_text(text + 'Publishing to the official catalogue is not currently supported.\n',
                   encoding='utf-8')
    problems, _ = check.run(str(report), str(log), 'report', 'deep')
    assert problems.errors == [], problems.errors


def test_the_quote_check_is_graded_like_the_others():
    standard, _ = run('no_evidence.md', level='standard')
    quick, _ = run('no_evidence.md', level='quick')
    assert any('no recorded evidence' in w for w in standard.warnings)
    assert not standard.errors
    assert not quick.errors


def test_a_finding_with_a_traceable_figure_needs_no_quote():
    """valid_report Finding 1 is carried by figures; the quote check must not
    double-charge a finding that already traces."""
    problems, _ = run('valid_report.md', level='deep')
    assert not any('no recorded evidence' in e for e in problems.errors)
