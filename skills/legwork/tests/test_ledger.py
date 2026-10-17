"""ledger.py - wide enough, measured: rounds until nothing new, and nothing found dropped."""

import json
import os
import shutil

import pytest

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


# ---------------------------------------------------------------------------
# Entity sites: an entity's own site, recorded by the subagent that opened it,
# so the gate can ask whether a matrix row cites it. Keyed by the full name,
# never by distinctive(), which merges "Acme Analytics" and "Acme Hosting".
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw, expected', [
    ('Acme', 'acme'),
    ('**Acme**', 'acme'),
    ('__Acme__', 'acme'),
    ('*Acme*', 'acme'),
    ('`Acme`', 'acme'),
    ('[Acme](https://acme.example)', 'acme'),
    ('Acme [3]', 'acme'),
    ('Acme [3][4]', 'acme'),
    ('  Acme   Analytics ', 'acme analytics'),
    ('Acme (UK)', 'acme (uk)'),
    ('snake_case_vendor', 'snake_case_vendor'),
])
def test_full_name_strips_presentation_and_keeps_words(raw, expected):
    assert ledger.full_name(raw) == expected


@pytest.mark.parametrize('site, key', [
    ('acme.example', 'acme.example'),
    ('https://www.Acme.example/pricing', 'acme.example'),
    ('docs.acme.example', 'docs.acme.example'),
    ('github.com/Acme', 'github.com/acme'),
    ('https://pypi.org/project/alpha/', 'pypi.org/project/alpha'),
    ('github.com', ''),
    ('', ''),
    ('not a site', ''),
    ('https://[bad', ''),
    ('not a.site', ''),
    ('bücher.de', 'xn--bcher-kva.de'),
    ('https://www.Bücher.de/preise', 'xn--bcher-kva.de'),
])
def test_site_key(site, key):
    assert ledger.site_key(site) == key


@pytest.mark.parametrize('url, key, belongs', [
    ('https://acme.example/pricing', 'acme.example', True),
    ('https://docs.acme.example/a', 'acme.example', True),
    ('https://www.acme.example/', 'acme.example', True),
    ('https://notacme.example/', 'acme.example', False),
    ('https://hosting.example.com/', 'analytics.example.com', False),
    ('https://github.com/acme/repo', 'github.com/acme', True),
    ('https://github.com/other/repo', 'github.com/acme', False),
    ('https://pypi.org/project/beta/', 'pypi.org/project/alpha', False),
    ('https://pypi.org/project/alpha/1.2/', 'pypi.org/project/alpha', True),
    ('https://pypi.org/project/alpha/1.0', 'pypi.org/project/alpha', True),
    ('https://test.pypi.org/project/alpha', 'pypi.org/project/alpha', False),
    ('https://www.pypi.org/project/alpha', 'pypi.org/project/alpha', True),
    ('https://www.npmjs.com/package/beta', 'npmjs.com/package/alpha', False),
    ('https://acme.example/', '', False),
    ('https://[bad', 'acme.example', False),
    ('https://bücher.de/x', 'xn--bcher-kva.de', True),
    ('https://xn--bcher-kva.de/x', 'xn--bcher-kva.de', True),
])
def test_site_belongs(url, key, belongs):
    assert ledger.site_belongs(url, key) is belongs


def test_record_round_stores_sites_by_full_name(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'q', ['Acme Analytics', 'Acme Hosting'], [],
                        sites=[('Acme Analytics', 'acme-analytics.example'),
                               ('Acme Hosting', 'acme-hosting.example')])
    sites = ledger.entity_sites(tsv)
    assert sites == {'acme analytics': {'acme-analytics.example'}, 'acme hosting': {'acme-hosting.example'}}


def test_a_site_is_stored_once_and_survives_a_later_round(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'q', ['Acme'], [], sites=[('Acme', 'acme.example')])
    ledger.record_round(tsv, 'q', ['Acme'], [], sites=[('Acme', 'https://www.acme.example/x')])
    ledger.record_round(tsv, 'q', ['Acme'], [])
    data = json.load(open(ledger.path(tsv)))
    assert data['q']['sites'] == {'acme': ['acme.example']}


def test_a_site_never_makes_an_entity_new(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'q', ['Acme'], [])
    new, _ = ledger.record_round(tsv, 'q', ['Acme'], [], sites=[('Acme', 'acme.example')])
    assert new == []


def test_sites_combine_across_angles(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'a', ['Acme'], [], sites=[('Acme', 'acme.example')])
    ledger.record_round(tsv, 'b', ['Acme'], [], sites=[('Acme', 'github.com/acme')])
    assert ledger.entity_sites(tsv) == {'acme': {'acme.example', 'github.com/acme'}}


def test_a_ledger_without_sites_still_loads(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    open(ledger.path(tsv), 'w').write(json.dumps(
        {'q': {'rounds': [], 'entities': {'acme': 'Acme'}, 'parties': []}}))
    assert ledger.entity_sites(tsv) == {}
    ledger.record_round(tsv, 'q', ['Acme'], [])  # no sites argument: no 'sites' key written
    assert 'sites' not in json.load(open(ledger.path(tsv)))['q']


def test_a_site_with_no_usable_key_is_not_stored(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'q', ['Acme'], [], sites=[('Acme', 'github.com'), ('Acme', '')])
    assert ledger.entity_sites(tsv) == {}


def test_a_malformed_site_never_interrupts_a_round(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'q', ['Acme'], [], sites=[('Acme', 'https://[bad')])
    assert ledger.entity_sites(tsv) == {}


def test_an_international_site_is_stored_in_its_ascii_form(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'q', ['Bücher'], [], sites=[('Bücher', 'bücher.de')])
    assert ledger.entity_sites(tsv) == {'bücher': {'xn--bcher-kva.de'}}
