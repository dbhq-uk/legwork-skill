"""The gate's two new questions: is the run lopsided, and can its age be judged.

Both exist because a report can pass every per-finding check and still be
unfit: every finding independently sound, the whole document resting on one
party, and nothing dated so nobody can tell how old any of it is.
"""

import shutil

import check
from conftest import fixture


def messages(problems):
    return ' | '.join(problems.errors + problems.warnings)


def write_log(path, rows):
    header = 'url\tkind\tangle\tvia\tfetched_at\tstatus\tdate\tnumbers\ttitle\tquote\n'
    body = ''.join(
        '{url}\t{kind}\t{angle}\twebfetch\t2026-07-28T09:00:00+00:00\tok\t{date}\t\t{title}\t{quote}\n'.format(**r)
        for r in rows)
    path.write_text(header + body, encoding='utf-8')


def log_row(url, angle, date='2026-07-01', kind='press', title='A title', quote='A quotable sentence.'):
    return {'url': url, 'angle': angle, 'date': date, 'kind': kind, 'title': title, 'quote': quote}


# ---------------------------------------------------------------------------
# Concentration
# ---------------------------------------------------------------------------

def test_a_run_mostly_from_one_party_is_flagged(tmp_path):
    report = tmp_path / 'lopsided.md'
    report.write_text(open(fixture('valid_report.md'), encoding='utf-8').read(), encoding='utf-8')
    log = tmp_path / 'lopsided.tsv'
    rows = [log_row('https://acme-software.example/pricing', 'incumbent pricing', kind='vendor_pricing')]
    rows += [log_row('https://acme-software.example/page{}'.format(i), 'angle {}'.format(i))
             for i in range(7)]
    write_log(log, rows)
    problems, _ = check.run(str(report), str(log), 'report', 'deep')
    assert any('acme-software.example' in m and 'concentration' in m.lower()
               for m in problems.errors + problems.warnings), messages(problems)


def test_concentration_is_not_checked_on_a_run_too_small_to_judge(tmp_path):
    """Two sources from one party is a small run, not a lopsided one. Firing here
    would make every quick run fail for a reason it cannot act on."""
    report = tmp_path / 'small.md'
    report.write_text(open(fixture('valid_report.md'), encoding='utf-8').read(), encoding='utf-8')
    log = tmp_path / 'small.tsv'
    write_log(log, [
        log_row('https://acme-software.example/pricing', 'a', kind='vendor_pricing'),
        log_row('https://acme-software.example/other', 'b'),
    ])
    problems, _ = check.run(str(report), str(log), 'report', 'deep')
    assert not any('concentration' in m.lower() for m in problems.errors + problems.warnings)


def test_the_existing_valid_fixture_is_not_newly_flagged():
    """The gate must not start failing a deliverable it has always passed."""
    problems, _ = check.run(fixture('valid_report.md'), fixture('valid_report.tsv'), 'report', 'deep')
    assert problems.errors == [], problems.errors


def test_concentration_is_graded_like_every_other_evidence_check(tmp_path):
    report = tmp_path / 'graded.md'
    report.write_text(open(fixture('valid_report.md'), encoding='utf-8').read(), encoding='utf-8')
    log = tmp_path / 'graded.tsv'
    rows = [log_row('https://acme-software.example/pricing', 'incumbent pricing', kind='vendor_pricing')]
    rows += [log_row('https://acme-software.example/page{}'.format(i), 'angle {}'.format(i))
             for i in range(7)]
    write_log(log, rows)
    standard, _ = check.run(str(report), str(log), 'report', 'standard')
    deep, _ = check.run(str(report), str(log), 'report', 'deep')
    assert any('concentration' in w.lower() for w in standard.warnings)
    assert not any('concentration' in e.lower() for e in standard.errors)
    assert any('concentration' in e.lower() for e in deep.errors)


# ---------------------------------------------------------------------------
# Undated evidence
# ---------------------------------------------------------------------------

def test_a_finding_whose_every_source_is_undated_is_flagged(tmp_path):
    report = tmp_path / 'undated.md'
    report.write_text(open(fixture('valid_report.md'), encoding='utf-8').read(), encoding='utf-8')
    log = tmp_path / 'undated.tsv'
    original = open(fixture('valid_report.tsv'), encoding='utf-8').read()
    stripped = []
    for line in original.splitlines():
        fields = line.split('\t')
        if fields[0] != 'url' and len(fields) > 6:
            fields[6] = ''
        stripped.append('\t'.join(fields))
    log.write_text('\n'.join(stripped) + '\n', encoding='utf-8')
    problems, _ = check.run(str(report), str(log), 'report', 'deep')
    assert any('publication date' in e for e in problems.errors), messages(problems)


def test_one_dated_source_is_enough_to_judge_a_findings_age():
    """The check asks whether age CAN be judged, not whether every source is
    dated. valid_report dates all three, so nothing fires."""
    problems, _ = check.run(fixture('valid_report.md'), fixture('valid_report.tsv'), 'report', 'deep')
    assert not any('publication date' in m for m in problems.errors + problems.warnings)


def test_undated_evidence_does_not_fire_at_quick_level(tmp_path):
    report = tmp_path / 'q.md'
    report.write_text(open(fixture('valid_report.md'), encoding='utf-8').read(), encoding='utf-8')
    log = tmp_path / 'q.tsv'
    write_log(log, [log_row('https://a.example/1', 'one', date='')])
    problems, _ = check.run(str(report), str(log), 'report', 'quick')
    assert problems.errors == []


def test_the_undated_fixture_fails_for_that_reason_and_no_other():
    """A fixture that fails for several reasons proves nothing about any of them."""
    problems, _ = check.run(fixture('undated_evidence.md'), fixture('undated_evidence.tsv'),
                            'report', 'deep')
    assert len(problems.errors) == 1, problems.errors
    assert 'publication date' in problems.errors[0]


def test_the_concentrated_fixture_fails_only_on_concentration():
    problems, _ = check.run(fixture('concentrated.md'), fixture('concentrated.tsv'),
                            'report', 'deep')
    assert problems.errors, 'the concentrated fixture must fail'
    assert all('concentration' in e.lower() for e in problems.errors), problems.errors
    assert any('onevendor.example' in e for e in problems.errors)


def test_a_could_not_answer_report_skips_both_new_checks(tmp_path):
    report = tmp_path / 'cna.md'
    shutil.copy(fixture('could_not_answer.md'), report)
    log = tmp_path / 'cna.tsv'
    write_log(log, [log_row('https://one.example/{}'.format(i), 'a', date='') for i in range(9)])
    problems, summary = check.run(str(report), str(log), 'report', 'deep')
    assert summary['outcome'] == 'could-not-answer'
    assert problems.errors == []
