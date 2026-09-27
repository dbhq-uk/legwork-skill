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

Measured on 2026-09-27 across pools of pages (evals/runs/2026-09-27-rerank-
offline.md): the average of Jev and the term match is the best scorer, and the
term match alone is nearly as good for nothing.

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
JEV_PASSAGE_CHARS = 2000
JEV_POOL = 200
DEFAULT_CAP = 3
DEFAULT_TOP = 24
PARTY_FLOOR = 0.3

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


def _jev_batch(batch, question, key):
    state = {'question': question,
             'passages': {'p{}'.format(i): p[:JEV_PASSAGE_CHARS] for i, p in enumerate(batch)}}
    questions = {'p{}'.format(i): {
        'type': 'score', 'criteria': fetch.JEV_LEVELS,
        'instructions': 'How well does passage `passages.p{}` help answer `question`?'.format(i)}
        for i in range(len(batch))}
    try:
        answers = (fetch._jev_request(state, questions, key) or {}).get('answers') or {}
    except Exception:  # noqa: BLE001 - one refused batch must not cost the rest
        return [None] * len(batch)
    return [fetch._expected_score(answers.get('p{}'.format(i))) if answers.get('p{}'.format(i)) else None
            for i in range(len(batch))]


def jev_scores(passages, question):
    """Jev's relevance of each passage to `question`, 0 to 1, or None.

    None overall when there is no key or every batch failed. A passage in a
    batch that failed scores None on its own, so one refusal costs only its
    own batch: measured on 2026-09-27, a single oversized passage had thrown
    away Jev's ranking for all 2,274 passages in the pool. Text sent is capped
    at JEV_PASSAGE_CHARS, and batches run in parallel.
    """
    key = fetch.typesafe_key()
    if not key or not passages:
        return None
    batches = [passages[start:start + JEV_BATCH] for start in range(0, len(passages), JEV_BATCH)]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda batch: _jev_batch(batch, question, key), batches))
    scores = [score for batch in results for score in batch]
    return None if all(score is None for score in scores) else scores


def pool_scores(passages, terms, question):
    """(scores, scorer) for a pool: the average of Jev and the term match when
    Jev is available, the term match alone otherwise.

    Measured on 2026-09-27 over 31 angles from the 24 Sep runs (median 81
    passages a pool): the passage a run went on to quote was in the top five
    86% of the time with the average, 76% with Jev alone and 74% with terms
    alone, and in the top 20 every time with the average or terms.

    Jev reads only the JEV_POOL passages the term match ranks highest. The
    first live pools ran past 2,000 passages an angle, and scoring them all
    took minutes; the term match's top 20 already held every quoted passage.
    A passage Jev did not read scores as if Jev had said no; one in a batch
    Jev refused keeps its term score.
    """
    terms_only = term_scores(passages, terms)
    order = sorted(range(len(passages)), key=lambda i: terms_only[i], reverse=True)[:JEV_POOL]
    jev_read = jev_scores([passages[i] for i in order], question)
    if jev_read is None:
        return terms_only, 'terms'
    jev = [0.0] * len(passages)
    for i, score in zip(order, jev_read):
        jev[i] = score
    return [(t + j) / 2 if j is not None else t for t, j in zip(terms_only, jev)], 'jev+terms'


def select_digest(items, subject_party=None, cap=DEFAULT_CAP, top=DEFAULT_TOP, floor=PARTY_FLOOR):
    """(chosen, overflow) from scored items - dicts with 'id', 'party', 'score'.

    - Every party whose best passage scores at least `floor` of the pool's best
      keeps that passage, even past `top`: corroboration is counted on
      parties, and a party dropped from the digest is a party Claude never
      weighs. Below the floor it is listed in overflow instead - measured on
      2026-09-27, "any score above zero" put 82 parties' best passages in one
      angle, most of them a stray word match.
    - Then the best of the rest, up to `top`, with no party other than
      `subject_party` holding more than `cap`.
    - `overflow` lists, by party, the id of every passage not chosen.
    Chosen items come back best first.
    """
    ranked = sorted(items, key=lambda item: item['score'], reverse=True)
    chosen_ids, per_party = set(), Counter()
    bar = max(1e-9, (ranked[0]['score'] if ranked else 0) * floor)
    for item in ranked:
        if item['score'] >= bar and per_party[item['party']] == 0:
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
