"""The gate's view of the matrix and the index.

Both are self-enforcing on purpose. A matrix the gate never looks at drifts into
blank cells; an index nothing checks stays empty, and an index nobody writes to
is the same as no index at all.
"""

import json
import os

import check
from conftest import fixture, saturated_ledger


def report_with(tmp_path, extra, name='r.md'):
    """A valid report with an extra section spliced in before Findings."""
    source = open(fixture('valid_report.md'), encoding='utf-8').read()
    target = tmp_path / name
    target.write_text(source.replace('## Findings', extra + '\n## Findings', 1), encoding='utf-8')
    log = tmp_path / (os.path.splitext(name)[0] + '.tsv')
    log.write_text(open(fixture('valid_report.tsv'), encoding='utf-8').read(), encoding='utf-8')
    saturated_ledger(log)
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


def contoso_seen_only_in_search(log):
    """Rewrite the log so Contoso's page [2] was only ever a search result."""
    text = open(log, encoding='utf-8').read()
    lines = [line.replace('\twebfetch\t', '\twebsearch\t') if 'contoso' in line else line
             for line in text.splitlines(keepends=True)]
    open(log, 'w', encoding='utf-8').write(''.join(lines))


def contoso_never_logged(log):
    text = open(log, encoding='utf-8').read()
    open(log, 'w', encoding='utf-8').write(
        ''.join(line for line in text.splitlines(keepends=True) if 'contoso' not in line))


def snippet_row_errors(problems):
    return [e for e in problems.errors if 'Contoso' in e and 'every citation in this row' in e]


def test_a_matrix_row_resting_only_on_snippets_fails_at_standard(tmp_path):
    """Measured on 2026-09-24: a banks run widened its matrix on eight search
    snippets and shipped, because at standard the snippet rule only warned."""
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    contoso_seen_only_in_search(log)
    problems, _ = check.run(report, log, 'report', 'standard')
    assert snippet_row_errors(problems), messages_of(problems)


def test_a_matrix_row_resting_only_on_snippets_fails_at_deep(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    contoso_seen_only_in_search(log)
    problems, _ = check.run(report, log, 'report', 'deep')
    assert snippet_row_errors(problems), messages_of(problems)


def test_a_matrix_row_citing_a_page_never_logged_fails_at_standard(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    contoso_never_logged(log)
    problems, _ = check.run(report, log, 'report', 'standard')
    assert snippet_row_errors(problems), messages_of(problems)


def test_quick_is_not_asked_about_snippet_rows(tmp_path):
    """Quick is snippet-first by design."""
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    contoso_seen_only_in_search(log)
    problems, _ = check.run(report, log, 'report', 'quick')
    assert not snippet_row_errors(problems), problems.errors


def test_a_row_with_one_opened_citation_passes(tmp_path):
    """Acme cites its own opened page [1] and the snippet [2]: one page was read."""
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    contoso_seen_only_in_search(log)
    problems, _ = check.run(report, log, 'report', 'standard')
    assert not [e for e in problems.errors if 'Acme' in e], problems.errors


def test_snippet_citations_in_prose_stay_a_warning_at_standard(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    contoso_seen_only_in_search(log)
    problems, _ = check.run(report, log, 'report', 'standard')
    assert any('cited from a search snippet' in w for w in problems.warnings), messages_of(problems)
    assert not any('cited from a search snippet' in e for e in problems.errors), problems.errors


def messages_of(problems):
    return ' | '.join(problems.errors + problems.warnings)


# ---------------------------------------------------------------------------
# An entity's own site settles it. Graded on 2026-09-27, wide runs got facts
# wrong where an aggregator or review stood in for the entity's own page; this
# check is the rebuild, for main, of that branch's fix (b8a90a4).
# ---------------------------------------------------------------------------

def with_sites(log, sites):
    """Record own sites in the ledger beside `log`, as log-returns would."""
    path = os.path.splitext(log)[0] + '.entities.json'
    data = json.load(open(path, encoding='utf-8'))
    first = next(iter(data.values()))
    first['sites'] = {name: list(keys) for name, keys in sites.items()}
    json.dump(data, open(path, 'w', encoding='utf-8'))


def own_site_errors(problems, entity):
    return [e for e in problems.errors if e.startswith(entity + ':') and 'own site' in e and 'never rendered' not in e]


def test_a_row_citing_no_page_on_its_own_site_fails(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    with_sites(log, {'acme': ['acme.example']})  # Acme cites acme-software.example and contoso
    problems, _ = check.run(report, log, 'report', 'standard')
    assert own_site_errors(problems, 'Acme'), messages_of(problems)


def test_a_row_citing_an_opened_page_on_a_subdomain_of_its_site_passes(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    with_sites(log, {'contoso': ['contoso.example']})  # Contoso cites learn.contoso.example, opened
    problems, _ = check.run(report, log, 'report', 'standard')
    assert not own_site_errors(problems, 'Contoso'), problems.errors


def test_an_own_site_page_seen_only_in_search_does_not_count(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    contoso_seen_only_in_search(log)
    with_sites(log, {'contoso': ['contoso.example']})
    problems, _ = check.run(report, log, 'report', 'standard')
    assert own_site_errors(problems, 'Contoso'), messages_of(problems)


def test_a_row_of_unknowns_is_not_checked(tmp_path):
    matrix = COMPLETE_MATRIX.replace('| Acme | 30 USD/seat [1] | No [2] |', '| Acme | [unknown] | [unknown] |')
    report, log = report_with(tmp_path, matrix)
    with_sites(log, {'acme': ['acme.example']})
    problems, _ = check.run(report, log, 'report', 'standard')
    assert not own_site_errors(problems, 'Acme'), problems.errors


def test_a_partly_unknown_row_is_still_checked(tmp_path):
    matrix = COMPLETE_MATRIX.replace('| Acme | 30 USD/seat [1] | No [2] |', '| Acme | 30 USD/seat [1] | [unknown] |')
    report, log = report_with(tmp_path, matrix)
    with_sites(log, {'acme': ['acme.example']})
    problems, _ = check.run(report, log, 'report', 'standard')
    assert own_site_errors(problems, 'Acme'), messages_of(problems)


def test_another_entitys_site_does_not_satisfy_the_row(tmp_path):
    matrix = COMPLETE_MATRIX.replace('| Acme |', '| Acme Analytics |')
    report, log = report_with(tmp_path, matrix)
    # Acme Analytics' own site is analytics.example.com; its row cites only Acme Software and Contoso
    with_sites(log, {'acme analytics': ['analytics.example.com'], 'acme': ['acme-software.example']})
    problems, _ = check.run(report, log, 'report', 'standard')
    assert own_site_errors(problems, 'Acme Analytics'), messages_of(problems)


def test_a_formatted_entity_cell_is_still_matched(tmp_path):
    for index, label in enumerate(('**Acme**', '[Acme](https://acme.example)', 'Acme [1]')):
        matrix = COMPLETE_MATRIX.replace('| Acme |', '| {} |'.format(label))
        report, log = report_with(tmp_path, matrix, name='r{}.md'.format(index))
        with_sites(log, {'acme': ['acme.example']})
        problems, _ = check.run(report, log, 'report', 'standard')
        assert [e for e in problems.errors if 'own site' in e], (label, messages_of(problems))


def test_an_entity_with_no_recorded_site_is_not_checked(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    problems, _ = check.run(report, log, 'report', 'standard')
    assert not [e for e in problems.errors if 'own site' in e], problems.errors


def test_quick_does_not_run_the_own_site_check(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    with_sites(log, {'acme': ['acme.example']})
    problems, _ = check.run(report, log, 'report', 'quick')
    assert not [e for e in problems.errors if 'own site' in e], problems.errors


def test_the_own_site_check_changes_nothing_without_a_tsv_path():
    import matrix
    parsed = matrix.parse_matrix(COMPLETE_MATRIX)
    problems = check.Problems('standard')
    check.check_rows_on_own_site(parsed, {}, [], None, problems)
    assert problems.errors == []


def test_a_row_for_a_longer_name_is_not_checked_against_a_shorter_recorded_one(tmp_path):
    """Exact names only: "Acme Hosting" is not "Acme", so a site recorded for
    Acme neither fails nor passes Acme Hosting's row."""
    matrix = COMPLETE_MATRIX.replace('| Acme |', '| Acme Hosting |')
    report, log = report_with(tmp_path, matrix)
    with_sites(log, {'acme': ['acme.example']})
    problems, _ = check.run(report, log, 'report', 'standard')
    assert not [e for e in problems.errors if 'own site' in e], problems.errors


def test_names_differing_only_in_parentheses_keep_separate_sites(tmp_path):
    matrix = COMPLETE_MATRIX.replace('| Acme |', '| Acme (UK) |')
    report, log = report_with(tmp_path, matrix)
    # Acme (UK)'s own site is acme-software.example, which its row cites and was opened;
    # Acme (US) has a different site. The UK row must pass on its own site alone.
    with_sites(log, {'acme (uk)': ['acme-software.example'], 'acme (us)': ['acme-us.example']})
    problems, _ = check.run(report, log, 'report', 'standard')
    assert not own_site_errors(problems, 'Acme (UK)'), problems.errors
    with_sites(log, {'acme (uk)': ['acme-us.example']})
    problems, _ = check.run(report, log, 'report', 'standard')
    assert own_site_errors(problems, 'Acme (UK)'), messages_of(problems)


def test_a_log_with_no_ledger_file_means_no_own_site_check(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    os.remove(os.path.splitext(log)[0] + '.entities.json')
    import matrix as matrix_module
    problems = check.Problems('standard')
    check.check_rows_on_own_site(matrix_module.parse_matrix(COMPLETE_MATRIX), {}, [], log, problems)
    assert problems.errors == []


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
    saturated_ledger(log)
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
    saturated_ledger(log)
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
    saturated_ledger(log)
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
    saturated_ledger(log)
    problems, _ = check.run(str(report), str(log), 'report', 'deep')
    assert any('index' in w for w in problems.warnings)
    assert problems.errors == []


# ---------------------------------------------------------------------------
# A blocked own page is rendered before it is given up, and an entity may have
# several own sites (spec L, 17 Oct 2026). Graded against the banks key, the
# branch lost cores whose own pages came back blocked or as shells and were
# never rendered; main rendered the same pages and got them.
# ---------------------------------------------------------------------------

ALL_UNKNOWN_ACME = COMPLETE_MATRIX.replace('| Acme | 30 USD/seat [1] | No [2] |', '| Acme | [unknown] | [unknown] |')


def add_log_row(log, url, status, via='webfetch', query=''):
    """Append a fetch-log row, as fetch.py or log-returns would."""
    lines = open(log, encoding='utf-8').read().splitlines()
    if 'query' not in lines[0].split('\t'):
        lines[0] += '\tquery'
        open(log, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    with open(log, 'a', encoding='utf-8') as handle:
        handle.write('\t'.join([url, 'vendor_pricing', 'incumbent pricing', via, '2026-07-28T09:05:00+00:00',
                                status, '2026-07-01', '', 'Page', 'A line.', query]) + '\n')


def render_errors(problems, entity):
    return [e for e in problems.errors if e.startswith(entity + ':') and 'never rendered' in e]


def run_with_bright_data(report, log, installed=True, level='standard'):
    original = check._bright_data_installed
    check._bright_data_installed = lambda: installed
    try:
        return check.run(report, log, 'report', level)[0]
    finally:
        check._bright_data_installed = original


def test_an_all_unknown_row_with_a_blocked_own_page_never_rendered_fails(tmp_path):
    report, log = report_with(tmp_path, ALL_UNKNOWN_ACME)
    with_sites(log, {'acme': ['acme.example']})
    add_log_row(log, 'https://acme.example/pricing', 'blocked')
    problems = run_with_bright_data(report, log)
    errors = render_errors(problems, 'Acme')
    assert len(errors) == 1, messages_of(problems)
    assert 'https://acme.example/pricing came back blocked and was never rendered' in errors[0]
    assert 'bd_search.py "https://acme.example/pricing" -m render' in errors[0]
    assert '--via brightdata' in errors[0] and '[unknown]' in errors[0]
    assert 'cite a page you opened on its own site' in errors[0]
    assert 'sources.py log --url https://acme.example/pricing --via brightdata --status blocked' in errors[0]
    assert 'bd_search.py exits 2' in errors[0]


def test_a_shell_own_page_never_rendered_fails_the_same_way(tmp_path):
    report, log = report_with(tmp_path, ALL_UNKNOWN_ACME)
    with_sites(log, {'acme': ['acme.example']})
    add_log_row(log, 'https://acme.example/pricing', 'SHELL')
    problems = run_with_bright_data(report, log)
    errors = render_errors(problems, 'Acme')
    assert errors and 'came back SHELL' not in errors[0] and 'came back shell' in errors[0], messages_of(problems)


def test_without_bright_data_a_blocked_own_page_is_not_an_error(tmp_path):
    report, log = report_with(tmp_path, ALL_UNKNOWN_ACME)
    with_sites(log, {'acme': ['acme.example']})
    add_log_row(log, 'https://acme.example/pricing', 'blocked')
    problems = run_with_bright_data(report, log, installed=False)
    assert not render_errors(problems, 'Acme') and not own_site_errors(problems, 'Acme'), problems.errors


def test_a_failed_render_logged_brightdata_counts_as_tried(tmp_path):
    report, log = report_with(tmp_path, ALL_UNKNOWN_ACME)
    with_sites(log, {'acme': ['acme.example']})
    add_log_row(log, 'https://acme.example/pricing', 'blocked')
    add_log_row(log, 'https://acme.example/pricing', 'blocked', via='brightdata')
    problems = run_with_bright_data(report, log)
    assert not render_errors(problems, 'Acme'), problems.errors


def test_an_aggregator_row_with_a_blocked_own_page_gets_the_render_message_only(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    with_sites(log, {'acme': ['acme.example']})  # Acme cites acme-software.example, opened
    add_log_row(log, 'https://acme.example/pricing', 'blocked')
    problems = run_with_bright_data(report, log)
    assert render_errors(problems, 'Acme'), messages_of(problems)
    assert not own_site_errors(problems, 'Acme'), messages_of(problems)


def test_a_row_citing_an_opened_own_page_passes_though_another_own_page_is_blocked(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    with_sites(log, {'acme': ['acme-software.example']})  # [1] is opened on it
    add_log_row(log, 'https://acme-software.example/enterprise', 'blocked')
    problems = run_with_bright_data(report, log)
    assert not render_errors(problems, 'Acme') and not own_site_errors(problems, 'Acme'), problems.errors


def test_an_aggregator_row_with_no_blocked_own_page_keeps_the_own_site_message_and_hint(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    with_sites(log, {'acme': ['acme.example']})
    problems = run_with_bright_data(report, log)
    errors = own_site_errors(problems, 'Acme')
    assert len(errors) == 1 and not render_errors(problems, 'Acme'), messages_of(problems)
    assert errors[0].endswith('If the page you opened is its own on another domain, record that domain too.')


def test_an_entity_with_two_sites_passes_on_an_opened_page_on_the_second(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    with_sites(log, {'acme': ['acme.example', 'acme-software.example']})
    problems = run_with_bright_data(report, log)
    assert not own_site_errors(problems, 'Acme') and not render_errors(problems, 'Acme'), problems.errors


def test_a_scrape_that_returned_a_shell_is_not_a_render(tmp_path):
    report, log = report_with(tmp_path, ALL_UNKNOWN_ACME)
    with_sites(log, {'acme': ['acme.example']})
    add_log_row(log, 'https://acme.example/pricing', 'blocked')
    add_log_row(log, 'https://acme.example/pricing', 'shell', via='brightdata', query='bd_search -m scrape')
    assert render_errors(run_with_bright_data(report, log), 'Acme')


def test_a_brightdata_shell_with_no_recorded_mode_is_not_a_render(tmp_path):
    report, log = report_with(tmp_path, ALL_UNKNOWN_ACME)
    with_sites(log, {'acme': ['acme.example']})
    add_log_row(log, 'https://acme.example/pricing', 'blocked')
    add_log_row(log, 'https://acme.example/pricing', 'shell', via='brightdata')
    assert render_errors(run_with_bright_data(report, log), 'Acme')


def test_a_render_that_returned_a_shell_counts_as_tried(tmp_path):
    report, log = report_with(tmp_path, ALL_UNKNOWN_ACME)
    with_sites(log, {'acme': ['acme.example']})
    add_log_row(log, 'https://acme.example/pricing', 'blocked')
    add_log_row(log, 'https://acme.example/pricing', 'shell', via='brightdata', query='bd_search -m render')
    problems = run_with_bright_data(report, log)
    assert not render_errors(problems, 'Acme'), problems.errors


def test_a_render_on_one_site_does_not_excuse_a_blocked_page_on_another(tmp_path):
    report, log = report_with(tmp_path, ALL_UNKNOWN_ACME)
    with_sites(log, {'acme': ['acme.example', 'acmebank.example']})
    add_log_row(log, 'https://acme.example/pricing', 'ok', via='brightdata', query='bd_search -m render')
    add_log_row(log, 'https://acmebank.example/api', 'blocked')
    errors = render_errors(run_with_bright_data(report, log), 'Acme')
    assert len(errors) == 1 and 'https://acmebank.example/api' in errors[0], errors


def test_a_row_failing_the_render_rule_does_not_also_get_the_unopened_error(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    contoso_seen_only_in_search(log)  # Contoso's only citation was never opened
    with_sites(log, {'contoso': ['contoso.example']})
    add_log_row(log, 'https://www.contoso.example/triage', 'shell')
    problems = run_with_bright_data(report, log)
    assert render_errors(problems, 'Contoso'), messages_of(problems)
    assert not snippet_row_errors(problems), messages_of(problems)


def test_the_render_rule_is_an_error_at_deep_and_not_asked_at_quick(tmp_path):
    report, log = report_with(tmp_path, ALL_UNKNOWN_ACME)
    with_sites(log, {'acme': ['acme.example']})
    add_log_row(log, 'https://acme.example/pricing', 'blocked')
    assert render_errors(run_with_bright_data(report, log, level='deep'), 'Acme')
    assert not render_errors(run_with_bright_data(report, log, level='quick'), 'Acme')
