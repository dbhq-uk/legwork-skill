"""ledger.py - wide enough, measured: rounds until nothing new, and nothing found dropped."""

import json
import os
import shutil

import check
import ledger
import sources
from conftest import fixture


def _reply(entities, urls, angle='which banks have a sandbox?'):
    lines = [json.dumps({'url': u, 'kind': 'vendor_docs', 'angle': angle, 'opened': False, 'via': 'websearch',
                         'status': 'ok', 'quote': '', 'title': 't', 'date': '', 'query': 'q'}) for u in urls]
    lines.append(json.dumps({'entities': entities}))
    lines.append(json.dumps({'gaps': ['none']}))
    return '\n'.join(lines)


def _log(tmp_path, tsv, reply, angle='which banks have a sandbox?'):
    path = tmp_path / 'reply.txt'
    path.write_text(reply, encoding='utf-8')
    try:
        sources.main(['log-returns', '--tsv', tsv, '--returns', str(path), '--angle', angle])
    except SystemExit:
        pass


def test_each_reply_is_a_round_and_saturation_is_counted(tmp_path):
    """Graded 29 Sep 2026: runs that stopped early covered half the core banks."""
    tsv = str(tmp_path / 'run.tsv')
    _log(tmp_path, tsv, _reply(['Barclays', 'HSBC UK'], ['https://a.example/1']))
    assert ledger.status(tsv)[0]['state'] == 'open'  # one round cannot show saturation
    _log(tmp_path, tsv, _reply(['Barclays', 'Monzo'], ['https://b.example/2']))
    assert ledger.status(tsv)[0]['state'] == 'open'  # Monzo was new
    _log(tmp_path, tsv, _reply(['HSBC', 'Monzo Bank'], ['https://c.example/3']))
    row = ledger.status(tsv)[0]
    assert row['state'] == 'saturated' and row['unit'] == 'entities'
    assert row['entities'] == ['Barclays', 'HSBC UK', 'Monzo']


def test_an_angle_still_finding_new_things_at_the_cap_is_capped(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    for names in (['A Bank'], ['B Bank'], ['C Bank']):
        _log(tmp_path, tsv, _reply(names, []))
    assert ledger.status(tsv, 'standard')[0]['state'] == 'capped'
    assert ledger.status(tsv, 'deep')[0]['state'] == 'open'


def test_an_angle_with_no_entities_saturates_on_new_parties(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    _log(tmp_path, tsv, _reply([], ['https://a.example/1']))
    _log(tmp_path, tsv, _reply([], ['https://a.example/2']))
    row = ledger.status(tsv)[0]
    assert row['unit'] == 'parties' and row['state'] == 'saturated'


def test_the_brief_for_a_later_round_lists_what_is_already_found(tmp_path, capsys, monkeypatch):
    import brief
    tsv = str(tmp_path / 'run.tsv')
    _log(tmp_path, tsv, _reply(['Barclays', 'Starling Bank'], []))
    capsys.readouterr()
    monkeypatch.setattr('sys.argv', ['brief.py', '--angle', 'which banks have a sandbox?', '--effort',
                                     'comparison', '--tsv', tsv])
    brief.main()
    out = capsys.readouterr().out
    assert '- Barclays' in out and '- Starling Bank' in out and 'first round' not in out


def test_the_gate_fails_a_standard_run_with_no_rounds(tmp_path):
    report = tmp_path / 'r.md'
    shutil.copyfile(fixture('valid_report.md'), report)
    tsv = tmp_path / 'r.tsv'
    shutil.copyfile(fixture('valid_report.tsv'), tsv)  # copyfile: no ledger comes with it
    problems, _ = check.run(str(report), str(tsv), 'report', 'standard')
    assert any('no retrieval rounds' in e for e in problems.errors)


def test_the_gate_fails_an_entity_found_and_dropped(tmp_path):
    report = tmp_path / 'r.md'
    shutil.copyfile(fixture('valid_report.md'), report)
    tsv = str(tmp_path / 'r.tsv')
    shutil.copyfile(fixture('valid_report.tsv'), tsv)
    for names in (['Zyxwv Bank'], ['Zyxwv Bank']):
        _log(tmp_path, tsv, _reply(names, []))
    problems, _ = check.run(str(report), tsv, 'report', 'standard')
    assert any('Zyxwv' in e for e in problems.errors)
    with open(report, 'a', encoding='utf-8') as handle:
        handle.write('\n## Found, not researched\n\n- Zyxwv Bank - its portal was offline.\n')
    problems, _ = check.run(str(report), tsv, 'report', 'standard')
    assert not any('Zyxwv' in e for e in problems.errors)


def test_the_distinctive_word_merges_names_for_one_entity():
    assert ledger.distinctive('Lloyds Banking Group') == ledger.distinctive('Lloyds Bank') == 'lloyds'
    assert ledger.distinctive('Bank of Ireland UK') == 'ireland'
    assert os.path.basename(ledger.path('/x/run.tsv')) == 'run.entities.json'


def test_an_out_of_scope_entity_is_set_aside_and_never_counted_as_new(tmp_path):
    """Graded 29 Sep 2026: e-money firms in a banks table were seven scope errors."""
    tsv = str(tmp_path / 'run.tsv')
    reply = _reply(['Barclays'], []).replace(
        '{"entities": ["Barclays"]}',
        '{"entities": ["Barclays"], "out_of_scope": [{"name": "Tide", "reason": "e-money firm"}]}')
    _log(tmp_path, tsv, reply)
    reply2 = _reply(['Barclays'], []).replace(
        '{"entities": ["Barclays"]}',
        '{"entities": ["Barclays"], "out_of_scope": [{"name": "Wise", "reason": "e-money firm"}]}')
    _log(tmp_path, tsv, reply2)
    assert ledger.status(tsv)[0]['state'] == 'saturated'
    assert ledger.all_entities(tsv) == ['Barclays']
    assert ledger.set_aside(tsv) == [('Tide', 'e-money firm'), ('Wise', 'e-money firm')]
