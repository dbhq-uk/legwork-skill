#!/usr/bin/env python3
"""
rerank.py - score every passage gathered for an angle, and choose the digest.

Used by gather.py; not a command of its own.

The pool is scored together, not page by page: every passage from every page
opened for an angle, against that angle. Jev scores it when a TypeSafe key is
available; a term-match score in plain Python does otherwise. The digest is
then the top of the pool, with one rule a pure ranking would break: no party
may fill it. Ten passages from one party still count as one independent voice
for corroboration, so a party is capped - except the angle's own subject,
whose pages are its primary evidence - and nothing is hidden: every passage
left out is listed by party, one call away.

Measured on 2026-09-24/25: within a single page, Jev put the passage the agent
went on to quote in its top three 75% of the time, against 26% for a random
pick. Across a pool of pages it had not been measured when this was written;
see evals/runs/2026-09-27-rerank-offline.md.

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import math
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fetch  # noqa: E402

JEV_BATCH = 30
DEFAULT_CAP = 3
DEFAULT_TOP = 40

_WORD = re.compile(r"[a-z0-9]+")


def _words(text):
    return _WORD.findall((text or '').lower())


def term_scores(passages, terms):
    """IDF-weighted share of the terms each passage contains, 0 to 1.

    A term found in every passage says nothing about any of them; a rare one
    says a lot. The free fallback when Jev is not available.
    """
    if not passages:
        return []
    wanted = set()
    for term in terms or ():
        wanted.update(w for w in _words(term) if len(w) > 2)
    if not wanted:
        return [0.0] * len(passages)
    sets = [set(_words(p)) for p in passages]
    df = Counter(w for s in sets for w in s & wanted)
    n = len(passages)
    idf = {w: math.log((n + 1) / (df.get(w, 0) + 0.5)) for w in wanted}
    best = sum(idf.values()) or 1.0
    return [max(0.0, min(1.0, sum(idf[w] for w in s & wanted) / best)) for s in sets]


def jev_scores(passages, question):
    """Jev's relevance of each passage to `question`, 0 to 1, or None.

    None when there is no key or any call fails: reranking must fall back,
    never stop the run.
    """
    key = fetch.typesafe_key()
    if not key or not passages:
        return None
    scores = []
    try:
        for start in range(0, len(passages), JEV_BATCH):
            batch = passages[start:start + JEV_BATCH]
            state = {'question': question, 'passages': {'p{}'.format(i): p for i, p in enumerate(batch)}}
            questions = {'p{}'.format(i): {
                'type': 'score', 'criteria': fetch.JEV_LEVELS,
                'instructions': 'How well does passage `passages.p{}` help answer `question`?'.format(i)}
                for i in range(len(batch))}
            answers = (fetch._jev_request(state, questions, key) or {}).get('answers') or {}
            scores += [fetch._expected_score(answers.get('p{}'.format(i))) for i in range(len(batch))]
    except Exception:  # noqa: BLE001 - an aid, never a reason to stop
        return None
    return scores


def select_digest(items, subject_party=None, cap=DEFAULT_CAP, top=DEFAULT_TOP):
    """(chosen, overflow) from scored items - dicts with 'id', 'party', 'score'.

    - Every party with any score above zero keeps its best passage, even past
      `top`: corroboration is counted on parties, and a party dropped from the
      digest is a party Claude never weighs.
    - Then the best of the rest, up to `top`, with no party other than
      `subject_party` holding more than `cap`.
    - `overflow` lists, by party, the id of every passage not chosen.
    Chosen items come back best first.
    """
    ranked = sorted(items, key=lambda item: item['score'], reverse=True)
    chosen_ids, per_party = set(), Counter()
    for item in ranked:
        if item['score'] > 0 and per_party[item['party']] == 0:
            chosen_ids.add(item['id'])
            per_party[item['party']] += 1
    for item in ranked:
        if len(chosen_ids) >= top:
            break
        if item['id'] in chosen_ids or item['score'] <= 0:
            continue
        if item['party'] != subject_party and per_party[item['party']] >= cap:
            continue
        chosen_ids.add(item['id'])
        per_party[item['party']] += 1
    chosen = [item for item in ranked if item['id'] in chosen_ids]
    overflow = {}
    for item in ranked:
        if item['id'] not in chosen_ids:
            overflow.setdefault(item['party'], []).append(item['id'])
    return chosen, overflow
