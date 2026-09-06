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


# ---------------------------------------------------------------------------
# A search snippet is not an opened page
#
# Measured on a real run filed on 2026-08-16: 18 of its 29 cited sources were
# search results nobody opened. It passed the gate at standard and was filed.
# check_evidence treated every row with an ok status as fetched, whatever
# transport it came from, so "cited but never fetched" could never see this.
# ---------------------------------------------------------------------------

def test_a_report_resting_only_on_snippets_fails_at_deep():
    problems, _ = run('snippet_only.md', level='deep', fmt='brief')
    assert any('never opened' in message for message in problems.errors), problems.errors


def test_the_same_report_only_warns_at_standard():
    problems, _ = run('snippet_only.md', level='standard', fmt='brief')
    assert problems.errors == [], problems.errors
    assert any('never opened' in message for message in problems.warnings)


def test_quick_does_not_complain_because_quick_is_snippet_first_by_design():
    problems, _ = run('snippet_only.md', level='quick', fmt='brief')
    assert problems.errors == [], problems.errors
    assert not any('never opened' in message for message in problems.warnings)


def test_the_snippet_rule_is_the_only_thing_wrong_with_that_fixture():
    """A MUST-fail fixture is evidence about one check only if it fails for one reason."""
    problems, _ = run('snippet_only.md', level='deep', fmt='brief')
    assert len(problems.errors) == 1, problems.errors


def test_opening_the_page_later_clears_the_snippet_rule(tmp_path):
    """Seen in a search result, then opened, is an opened page."""
    report = shutil.copy(fixture('snippet_only.md'), str(tmp_path / 'run.md'))
    tsv = str(tmp_path / 'run.tsv')
    shutil.copy(fixture('snippet_only.tsv'), tsv)
    with open(tsv, 'a', encoding='utf-8') as handle:
        for url, title, quote in (
                ('https://supplier.example/transit', 'Transit category',
                 'All products listed are specified for H3 (high roof) configuration.'),
                ('https://supplier.example/cubicle-d', 'Cubicle D',
                 'External dimensions - height 2088mm.'),
                ('https://roundup.example/transit-kits', 'Transit conversion kits',
                 'The medium roof gives roughly 1886 mm of interior load height.')):
            handle.write('{}\tvendor_docs\tan angle\tdirect\t2026-09-06T10:00:00+00:00\tok\t'
                         '2026-08-01\t\t{}\t{}\tq\n'.format(url, title, quote))
    problems, _ = check.run(report, tsv, 'brief', 'deep')
    assert not any('never opened' in message for message in problems.errors), problems.errors


def test_an_api_record_counts_as_opened(tmp_path):
    """A registry's own JSON is the record, not a snippet about it."""
    report = shutil.copy(fixture('snippet_only.md'), str(tmp_path / 'run.md'))
    tsv = str(tmp_path / 'run.tsv')
    with open(tsv, 'w', encoding='utf-8') as handle:
        handle.write('url\tkind\tangle\tvia\tfetched_at\tstatus\tdate\tnumbers\ttitle\tquote\tquery\n')
        for url in ('https://supplier.example/transit', 'https://supplier.example/cubicle-d',
                    'https://roundup.example/transit-kits'):
            handle.write('{}\tregistry\tan angle\tapi\t2026-09-06T10:00:00+00:00\tok\t2026-08-01\t'
                         '2088,1886\tA record\tA verbatim sentence from the record.\tq\n'.format(url))
    problems, _ = check.run(report, tsv, 'brief', 'deep')
    assert not any('never opened' in message for message in problems.errors), problems.errors


# ---------------------------------------------------------------------------
# The receipt has to agree with the log
# ---------------------------------------------------------------------------

def _report_with_receipt(tmp_path, receipt):
    report = str(tmp_path / 'run.md')
    with open(fixture('snippet_only.md'), encoding='utf-8') as handle:
        content = handle.read()
    content = content.replace(
        '*standard · 3 angles · 3 sources (0 opened, 0 via Bright Data) · 1 disconfirming search*',
        receipt)
    with open(report, 'w', encoding='utf-8') as handle:
        handle.write(content)
    tsv = shutil.copy(fixture('snippet_only.tsv'), str(tmp_path / 'run.tsv'))
    return report, tsv


def test_a_receipt_claiming_more_opened_than_the_log_holds_is_flagged(tmp_path):
    report, tsv = _report_with_receipt(
        tmp_path, '*standard · 3 angles · 3 sources (3 opened, 0 via Bright Data)*')
    problems, _ = check.run(report, tsv, 'brief', 'standard')
    assert any('receipt says 3 opened' in message for message in problems.warnings), problems.warnings


def test_a_receipt_that_agrees_with_the_log_is_silent(tmp_path):
    report, tsv = _report_with_receipt(
        tmp_path, '*standard · 3 angles · 3 sources (0 opened, 0 via Bright Data)*')
    problems, _ = check.run(report, tsv, 'brief', 'standard')
    assert not any('receipt says' in message for message in problems.warnings), problems.warnings


def test_a_receipt_with_no_opened_count_is_not_second_guessed(tmp_path):
    """Old reports predate the count. Absence is not a disagreement."""
    report, tsv = _report_with_receipt(tmp_path, '*standard · 3 angles · 3 sources*')
    problems, _ = check.run(report, tsv, 'brief', 'standard')
    assert not any('receipt says' in message for message in problems.warnings), problems.warnings


# ---------------------------------------------------------------------------
# A quote checked against the page and not found on it is not evidence
#
# Verification used to print a warning on stderr at the moment of logging and
# stop there. Nothing downstream could see it, so a sentence the page never
# contained still satisfied the "this finding rests on something recorded"
# check. Recording a check and then ignoring it is worse than not checking.
# ---------------------------------------------------------------------------

def _one_source_report(tmp_path, verified, quote='A sentence nobody can find on the page.'):
    report = str(tmp_path / 'run.md')
    with open(report, 'w', encoding='utf-8') as handle:
        handle.write(
            '# A title that states the answer\n\n'
            '*standard · 1 angle · 1 source (1 opened, 0 via Bright Data)*\n\n'
            '## Findings\n\n'
            '### Finding 1: The vendor gates the feature behind the top tier\n\n'
            '**Confidence: Weak** - one vendor page, no independent confirmation.\n\n'
            'The vendor says the feature is top-tier only [1].\n\n'
            '## Limitations\n\nOne source.\n\n'
            '## Bibliography\n\n'
            '[1] Vendor (2026). "Pricing". https://vendor.example/pricing\n')
    tsv = str(tmp_path / 'run.tsv')
    with open(tsv, 'w', encoding='utf-8') as handle:
        handle.write('\t'.join(check.read_rows.__globals__['TSV_COLUMNS']) + '\n')
        handle.write('https://vendor.example/pricing\tvendor_pricing\tan angle\tdirect\t'
                     '2026-09-06T09:00:00+00:00\tok\t2026-07-01\t\tPricing\t{}\tq\t{}\n'.format(
                         quote, verified))
    return report, tsv


def test_a_quote_the_page_does_not_contain_cannot_support_a_finding(tmp_path):
    report, tsv = _one_source_report(tmp_path, verified='false')
    problems, _ = check.run(report, tsv, 'brief', 'deep')
    assert any('does not contain it' in message for message in problems.errors), problems.errors


def test_the_same_finding_is_fine_when_the_quote_checks_out(tmp_path):
    report, tsv = _one_source_report(tmp_path, verified='true')
    problems, _ = check.run(report, tsv, 'brief', 'deep')
    assert problems.errors == [], problems.errors


def test_an_unverifiable_quote_is_not_punished(tmp_path):
    """Empty means nobody could check - no page text was supplied. That is the
    ordinary case for WebFetch and must not be treated as a failed check."""
    report, tsv = _one_source_report(tmp_path, verified='')
    problems, _ = check.run(report, tsv, 'brief', 'deep')
    assert problems.errors == [], problems.errors


def test_a_misquoted_source_also_stops_carrying_the_finding(tmp_path):
    """The quote is struck out as evidence, not merely flagged: with no figure
    and no other source, the finding rests on nothing recorded."""
    report, tsv = _one_source_report(tmp_path, verified='false')
    problems, _ = check.run(report, tsv, 'brief', 'deep')
    assert any('rests on no recorded evidence' in message for message in problems.errors), problems.errors


# ---------------------------------------------------------------------------
# A paid search result is still a search result
# ---------------------------------------------------------------------------

def test_a_serp_row_does_not_launder_a_snippet_into_an_opened_page(tmp_path):
    """bd_search SERP and intent search return ranked snippets. Logging them as
    `brightdata` would have walked them straight through the snippet rule, so
    they log as `serp` and the rule treats them as the leads they are."""
    report = shutil.copy(fixture('snippet_only.md'), str(tmp_path / 'run.md'))
    tsv = str(tmp_path / 'run.tsv')
    with open(fixture('snippet_only.tsv'), encoding='utf-8') as handle:
        content = handle.read().replace('\twebsearch\t', '\tserp\t')
    with open(tsv, 'w', encoding='utf-8') as handle:
        handle.write(content)
    problems, _ = check.run(report, tsv, 'brief', 'deep')
    assert any('never opened' in message for message in problems.errors), problems.errors
