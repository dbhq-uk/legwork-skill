#!/usr/bin/env python3
"""
ledger.py - what each round of retrieval found that the rounds before it had not.

Wide enough is measured, not asserted (Dan, 29 Sep 2026): an angle keeps going
until a round finds nothing new, and everything any round found is accounted
for in the report. Graded against answer keys the same day, main on Sonnet 5.5
covered half the core banks main on Sonnet 5 had (6 a run against 12): it
skipped its subagents, stopped at about 15 sources, and nothing told it the
list was unfinished.

What "new" means depends on the angle:

  a list angle   (it returned entities)  a new entity - a bank, a provider, a
                 supplier. A new article about Barclays adds nothing.
  any other      a new independent party - an organisation not heard from on
                 this angle yet.

An angle is SATURATED when its last round added nothing new, OPEN while it is
still finding new things, and CAPPED when it is still finding them at the
round limit for the level (quick 1, standard 3, deep none) - which the report
must say.

The ledger is <tsv stem>.entities.json beside the fetch log. `sources.py
log-returns` writes a round each time it logs a subagent's reply.

CLI:
    ledger.py status --tsv PATH [--level quick|standard|deep]

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import json
import os
import re

ROUND_CAP = {'quick': 1, 'standard': 3, 'deep': None}

_GENERIC_WORDS = frozenset('''a an and the of for in on uk gb group ltd limited plc inc llc co company
bank banks banking building society services service managed hosted cloud database databases platform
'''.split())


def distinctive(name):
    """The word that names an entity in prose: its first word that is not
    generic. "Bank of Ireland UK" -> "ireland", "Lloyds Banking Group" ->
    "lloyds", "AWS RDS for PostgreSQL" -> "aws"."""
    words = re.findall(r"[a-z0-9][a-z0-9&'.-]*", re.sub(r'\([^)]*\)', ' ', (name or '').lower()))
    for word in words:
        word = word.strip(".'")
        if word not in _GENERIC_WORDS and len(word) >= 3:
            return word
    return words[0].strip(".'") if words else ''


def named_in(name, text):
    """Is the entity `name` named anywhere in `text`?"""
    text = (text or '').lower()
    if (name or '').lower().split('(')[0].strip() in text:
        return True
    word = distinctive(name)
    return bool(word) and re.search(r'\b{}\b'.format(re.escape(word)), text) is not None


def path(tsv):
    return os.path.splitext(tsv)[0] + '.entities.json'


def load(tsv):
    try:
        with open(path(tsv), encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def record_round(tsv, angle, entities, parties, out_of_scope=()):
    """Add one round for `angle`: the entities its subagent named, the ones it
    set aside as not what the angle asks about (with reasons), and the parties
    it logged. Returns what was new in this round. Set-aside names never count
    as new: a bank question's tail of e-money firms is not breadth, and counted
    it would keep the angle open for ever."""
    ledger = load(tsv)
    entry = ledger.setdefault(angle, {'rounds': [], 'entities': {}, 'parties': []})
    aside = entry.setdefault('out_of_scope', {})
    for name, reason in out_of_scope or ():
        key = distinctive(name)
        if key and key not in entry['entities']:
            aside.setdefault(key, {'name': ' '.join(str(name).split()), 'reason': reason})
    new_entities = []
    for name in entities or []:
        name = ' '.join(str(name).split())
        key = distinctive(name)
        if key and key not in entry['entities']:
            entry['entities'][key] = name
            aside.pop(key, None)
            new_entities.append(name)
    seen = set(entry['parties'])
    new_parties = sorted({p for p in parties or [] if p and p not in seen})
    entry['parties'] += new_parties
    entry['rounds'].append({'entities': len(entities or []), 'new_entities': new_entities,
                            'new_parties': new_parties})
    with open(path(tsv), 'w', encoding='utf-8') as handle:
        json.dump(ledger, handle, ensure_ascii=False, indent=1)
    return new_entities, new_parties


def status(tsv, level='standard'):
    """[{angle, unit, rounds, new_last, state, entities}] for every angle."""
    cap = ROUND_CAP.get(level, 3)
    out = []
    for angle, entry in load(tsv).items():
        rounds = entry.get('rounds') or []
        is_list = bool(entry.get('entities'))
        last = rounds[-1] if rounds else {}
        new_last = len(last.get('new_entities') if is_list else last.get('new_parties') or [])
        # One round cannot show saturation: everything in it is new.
        if len(rounds) >= 2 and new_last == 0:
            state = 'saturated'
        elif cap is not None and len(rounds) >= cap:
            state = 'capped'
        else:
            state = 'open'
        out.append({'angle': angle, 'unit': 'entities' if is_list else 'parties', 'rounds': len(rounds),
                    'new_last': new_last, 'state': state,
                    'entities': sorted((entry.get('entities') or {}).values())})
    return out


def set_aside(tsv):
    """[(name, reason)] every subagent set aside as out of scope, and no round
    later found in scope."""
    out = {}
    for entry in load(tsv).values():
        for key, item in (entry.get('out_of_scope') or {}).items():
            if key not in (entry.get('entities') or {}):
                out.setdefault(key, (item['name'], item.get('reason') or ''))
    return sorted(out.values())


def all_entities(tsv):
    return sorted({name for entry in load(tsv).values() for name in (entry.get('entities') or {}).values()})


def cmd_status(args):
    rows = status(args.tsv, args.level)
    if not rows:
        print('no rounds recorded yet - log each subagent reply with sources.py log-returns')
        return
    for row in rows:
        print('{:<10} {} round{}, {} new {} last round - {}'.format(
            row['state'], row['rounds'], '' if row['rounds'] == 1 else 's', row['new_last'], row['unit'],
            row['angle']))
    still = [r for r in rows if r['state'] == 'open']
    if still:
        print('\nnext: one more round for each open angle - brief.py --tsv {} --angle "<angle>" passes the '
              'entities already found, so the subagent looks for others'.format(args.tsv))
    aside = set_aside(args.tsv)
    if aside:
        print('\nset aside by subagents as not what the angle asks about - research any that is wrongly here:')
        for name, reason in aside:
            print('  {} - {}'.format(name, reason or 'no reason given'))
    total = all_entities(args.tsv)
    if total:
        print('\n{} entities found in all - every one goes in the report, researched or under '
              '"Found, not researched" with its reason'.format(len(total)))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ledger.py', description=__doc__.split('\n')[1].strip())
    sub = parser.add_subparsers(dest='command', required=True)
    p_status = sub.add_parser('status', help='Saturated, open or capped, per angle')
    p_status.add_argument('--tsv', required=True)
    p_status.add_argument('--level', choices=sorted(ROUND_CAP), default='standard')
    args = parser.parse_args(argv)
    {'status': cmd_status}[args.command](args)


if __name__ == '__main__':
    main()
