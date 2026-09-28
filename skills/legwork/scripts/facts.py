#!/usr/bin/env python3
"""
facts.py - every fact in the answer, the passage it rests on, and the standard
of proof its kind needs.

A finding is several facts. Corroboration counted per finding let a wrong fact
ride along with right ones: graded against answer keys on 2026-09-27, the
scripted runs got more facts wrong than main, and nearly every wrong one came
from a directory, aggregator or review standing in for the entity's own page.

Two kinds, two standards (tested offline on 102 graded facts, 28 Sep 2026 -
counting supports and contradictions for every fact blocked 54 of 57 right
ones, because an entity's own requirement has one first-hand source and the
web contradicts almost everything with stale copies):

  own    what an entity itself offers, charges or requires. Its own site is
         the authority: the fact must quote a page on the entity's own site.
  world  anything else - a count, a market claim, what people report. It needs
         two independent sources: different parties, and not the same sentence
         carried by both (a mirror is one source however many sites carry it).

And one contradiction check a script can do reliably: a price in an own fact
that no passage on the entity's own site shows, when that site's passages
about the same thing show other prices. Claude looks at those, and only
those, and says whether the value is current, superseded or contested.

Files: <tsv stem>.facts.json, beside the fetch log. Quotes are checked against
the saved page text through <tsv stem>.ids.json, and recorded on the log rows
as `sources.py quote` records them.

CLI:
    facts.py add   --tsv PATH --file NEW.json   add or replace facts, check them
    facts.py check --tsv PATH                   print what fails, nothing else

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sources  # noqa: E402
from independence import SIMILARITY_THRESHOLD, hybrid_similarity, party_of  # noqa: E402

KINDS = ('own', 'world')
STATUSES = ('current', 'superseded', 'contested')
PRICE_TOLERANCE = 0.1
CANDIDATES_SHOWN = 2

_GENERIC_WORDS = frozenset('''a an and the of for in on uk gb group ltd limited plc inc llc co company
bank banks building society services service managed hosted cloud database databases platform
'''.split())
_AMOUNT = re.compile(r'([£$€])\s?(\d[\d,]*(?:\.\d+)?)')


def distinctive(name):
    """The word that names an entity in prose: its first word that is not
    generic. "Bank of Ireland UK" -> "ireland", "AWS RDS for PostgreSQL" -> "aws"."""
    words = re.findall(r"[a-z0-9][a-z0-9&'.-]*", re.sub(r'\([^)]*\)', ' ', (name or '').lower()))
    for word in words:
        if word not in _GENERIC_WORDS and len(word) >= 3:
            return word
    return words[0] if words else ''


def names(entity, other):
    """Does `other` name the same entity as `entity`?"""
    entity, other = (entity or '').lower(), (other or '').lower()
    if not entity or not other:
        return False
    if entity in other or other in entity:
        return True
    word = distinctive(entity)
    return bool(word) and re.search(r'\b{}\b'.format(re.escape(word)), other) is not None


def as_party(site):
    site = (site or '').strip()
    return party_of(site if '://' in site else 'https://' + site.lstrip('/'))


def _load(path, default):
    try:
        with open(path, encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def paths(tsv):
    stem = os.path.splitext(tsv)[0]
    return stem + '.facts.json', stem + '.ids.json'


def subject_sites(run_dir):
    """{subject: {party, ...}} from every plan in the run folder."""
    found = {}
    for path in sorted(glob.glob(os.path.join(run_dir, 'plan-*.json'))):
        for angle in _load(path, {}).get('angles') or []:
            if angle.get('subject') and angle.get('sites'):
                found.setdefault(angle['subject'], set()).update(as_party(s) for s in angle['sites'])
    return found


def own_parties(fact, sites_by_subject):
    parties = {as_party(site) for site in fact.get('sites') or []}
    for subject, own in sites_by_subject.items():
        if names(subject, fact.get('entity')):
            parties |= own
    return parties


def _amounts(text):
    found = []
    for symbol, digits in _AMOUNT.findall(text or ''):
        try:
            found.append((symbol, float(digits.replace(',', ''))))
        except ValueError:
            continue
    return found


def _topic_words(fact):
    entity_words = set(re.findall(r'[a-z0-9]+', (fact.get('entity') or '').lower()))
    return {w for w in re.findall(r'[a-z]+', (fact.get('claim') or '').lower())
            if len(w) > 3 and w not in entity_words and w not in _GENERIC_WORDS}


def price_candidates(fact, ids, own):
    """Own-site passages about the same thing that show prices, none of them
    the fact's. Empty when the fact carries no price, or its site agrees."""
    claimed = _amounts(fact.get('claim'))
    if not claimed or not own:
        return []
    topic = _topic_words(fact)
    agreeing, differing = False, []
    for passage_id, entry in ids.items():
        if entry.get('party') not in own:
            continue
        text = entry.get('text') or ''
        shown = _amounts(text)
        if not shown or not topic & set(re.findall(r'[a-z]+', text.lower())):
            continue
        same_currency = [v for s, v in shown if any(s == cs for cs, _ in claimed)]
        if not same_currency:
            continue
        if any(abs(v - cv) <= PRICE_TOLERANCE * max(cv, 0.01) for cs, cv in claimed for v in same_currency):
            agreeing = True
            break
        differing.append(passage_id)
    return [] if agreeing else differing[:CANDIDATES_SHOWN]


def independent_groups(sources_):
    """Sources that could have disagreed: one group per party, and two parties
    carrying the same sentence are one group - a mirror, a syndicated copy or a
    blog repeating another's line."""
    groups = []
    for source in sources_:
        for group in groups:
            if source['party'] in {s['party'] for s in group} or any(
                    hybrid_similarity(source['quote'], other['quote']) >= SIMILARITY_THRESHOLD for other in group):
                group.append(source)
                break
        else:
            groups.append([source])
    return groups


def judge(fact, ids, sites_by_subject):
    """(errors, notes) for one fact."""
    label = '{}: "{}"'.format(fact.get('entity') or '?', (fact.get('claim') or '')[:80])
    errors = []
    kind = fact.get('kind')
    if kind not in KINDS:
        return ['{} - kind must be "own" or "world"'.format(label)], []
    checked = []
    for source in fact.get('sources') or []:
        entry = ids.get(source.get('id') or '')
        if not entry:
            errors.append('{} - no passage {} in this run'.format(label, source.get('id')))
            continue
        page = ''
        try:
            with open(entry.get('text_file') or '', encoding='utf-8', errors='replace') as handle:
                page = handle.read()
        except OSError:
            pass
        if not sources.quote_appears_in(source.get('quote') or '', page or entry.get('text') or ''):
            errors.append('{} - the quote from {} is not on its page; take the sentence again'.format(
                label, source.get('id')))
            continue
        checked.append({'id': source['id'], 'url': entry.get('url'), 'party': entry.get('party'),
                        'quote': source['quote']})
    if not checked:
        errors.append('{} - no source with a quote on its page'.format(label))
        return errors, []
    own = own_parties(fact, sites_by_subject)
    notes = []
    if kind == 'own':
        if not own:
            errors.append('{} - an own fact needs the entity\'s site: add "sites" to the fact, or research it '
                          'as a round-2 subject'.format(label))
        elif not any(s['party'] in own for s in checked):
            errors.append('{} - an own fact must quote the entity\'s own site ({}); a third party found it, '
                          'its own page settles it'.format(label, ', '.join(sorted(own))))
        differing = price_candidates(fact, ids, own)
        if differing and fact.get('status') not in STATUSES:
            errors.append('{} - its own site shows other prices and not this one ({}): read them and set '
                          '"status" to current, superseded or contested'.format(label, ', '.join(differing)))
    else:
        groups = independent_groups(checked)
        if len(groups) < 2:
            errors.append('{} - a world fact needs two independent sources; these are one ({})'.format(
                label, ', '.join(s['id'] for s in checked)))
    if fact.get('status') in ('superseded', 'contested'):
        notes.append('{} - {}'.format(label, fact['status']))
    return errors, notes


def check_facts(tsv):
    """(errors, notes, facts) for a run; ([], [], []) when it keeps no facts."""
    facts_path, ids_path = paths(tsv)
    facts = _load(facts_path, [])
    if not facts:
        return [], [], []
    ids = _load(ids_path, {})
    sites_by_subject = subject_sites(os.path.dirname(os.path.abspath(tsv)))
    errors, notes = [], []
    for fact in facts:
        fact_errors, fact_notes = judge(fact, ids, sites_by_subject)
        errors += fact_errors
        notes += fact_notes
    return errors, notes, facts


def cmd_add(args):
    new = _load(args.file, None)
    if not isinstance(new, list):
        print('error: {} must hold a JSON list of facts'.format(args.file), file=sys.stderr)
        sys.exit(2)
    facts_path, ids_path = paths(args.tsv)
    facts = _load(facts_path, [])
    key = lambda f: ((f.get('entity') or '').lower(), (f.get('claim') or '').lower())  # noqa: E731
    replaced = {key(f) for f in new}
    facts = [f for f in facts if key(f) not in replaced] + new
    with open(facts_path, 'w', encoding='utf-8') as handle:
        json.dump(facts, handle, ensure_ascii=False, indent=1)
    # Record each quote on its log row too, so the gate's source-level checks
    # see what the facts rest on.
    ids = _load(ids_path, {})
    for fact in new:
        for source in fact.get('sources') or []:
            entry = ids.get(source.get('id') or '')
            if not entry:
                continue
            page = None
            if entry.get('text_file') and os.path.exists(entry['text_file']):
                with open(entry['text_file'], encoding='utf-8', errors='replace') as handle:
                    page = handle.read()
            try:
                sources.set_quote(args.tsv, entry['url'], source.get('quote') or '', page)
            except sources.LogError:
                pass
    cmd_check(args, total=len(facts))


def cmd_check(args, total=None):
    errors, notes, facts = check_facts(args.tsv)
    for line in errors:
        print('fails  ' + line)
    for line in notes:
        print('note   ' + line)
    print('{} facts, {} failing'.format(total if total is not None else len(facts), len(errors)))
    if errors:
        sys.exit(1)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='facts.py', description=__doc__.split('\n')[1].strip())
    sub = parser.add_subparsers(dest='command', required=True)
    p_add = sub.add_parser('add', help='Add or replace facts from a JSON list, then check them all')
    p_add.add_argument('--tsv', required=True)
    p_add.add_argument('--file', required=True)
    p_check = sub.add_parser('check', help='Print every fact that fails its standard')
    p_check.add_argument('--tsv', required=True)
    args = parser.parse_args(argv)
    {'add': cmd_add, 'check': cmd_check}[args.command](args)


if __name__ == '__main__':
    main()
