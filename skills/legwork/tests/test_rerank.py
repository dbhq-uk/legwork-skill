"""Reranking the whole passage pool for an angle, and choosing the digest.

The digest is what Claude reads instead of the pages, so these pin the two
things it must never do: let one party fill it, and hide what it left out.
"""

import rerank


def test_rare_terms_outrank_common_words():
    passages = [
        'The bank offers a sandbox for developers to test.',
        'Sandbox access requires an eIDAS certificate and a software statement.',
        'The bank is a bank with customers and branches and a website.',
    ]
    scores = rerank.term_scores(passages, ['sandbox eIDAS certificate'])
    assert scores[1] == max(scores)
    assert scores[2] == min(scores)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_term_scores_of_an_empty_pool_are_empty():
    assert rerank.term_scores([], ['anything']) == []


def _item(i, party, score):
    return {'id': 's{}'.format(i), 'party': party, 'score': score}


def test_a_party_is_capped_and_the_rest_are_listed_not_hidden():
    items = [_item(i, 'vendor.example', 0.9 - i * 0.01) for i in range(8)] + [_item(20, 'other.example', 0.2)]
    chosen, overflow = rerank.select_digest(items, subject_party=None, cap=3, top=40)
    assert [c['id'] for c in chosen if c['party'] == 'vendor.example'] == ['s0', 's1', 's2']
    assert overflow['vendor.example'] == ['s3', 's4', 's5', 's6', 's7']


def test_the_subject_is_never_capped():
    items = [_item(i, 'barclays.com', 0.9 - i * 0.01) for i in range(8)]
    chosen, overflow = rerank.select_digest(items, subject_party='barclays.com', cap=3, top=40)
    assert len(chosen) == 8 and not overflow


def test_every_party_with_anything_relevant_keeps_a_passage():
    items = [_item(i, 'big.example', 0.9) for i in range(50)] + [_item(99, 'small.example', 0.05),
                                                                 _item(98, 'nothing.example', 0.0)]
    chosen, overflow = rerank.select_digest(items, subject_party='big.example', cap=3, top=40)
    parties = {c['party'] for c in chosen}
    assert 'small.example' in parties
    assert 'nothing.example' not in parties
    assert 's98' in overflow['nothing.example']


def test_the_digest_stops_at_top_and_lists_what_it_cut():
    items = [_item(i, 'p{}.example'.format(i), 1 - i * 0.01) for i in range(60)]
    chosen, overflow = rerank.select_digest(items, subject_party=None, cap=3, top=40)
    assert len(chosen) == 60  # every party keeps one, even past the top
    items = [_item(i, 'one.example', 1 - i * 0.001) for i in range(60)]
    chosen, overflow = rerank.select_digest(items, subject_party='one.example', cap=3, top=40)
    assert len(chosen) == 40 and len(overflow['one.example']) == 20


def test_chosen_passages_come_back_best_first():
    items = [_item(1, 'a.example', 0.2), _item(2, 'b.example', 0.9), _item(3, 'c.example', 0.5)]
    chosen, _ = rerank.select_digest(items, subject_party=None)
    assert [c['id'] for c in chosen] == ['s2', 's3', 's1']


def test_jev_scores_are_none_without_a_key(monkeypatch):
    monkeypatch.setattr(rerank.fetch, 'typesafe_key', lambda: '')
    assert rerank.jev_scores(['a passage'], 'a question') is None


def test_jev_scores_are_none_when_the_call_fails(monkeypatch):
    monkeypatch.setattr(rerank.fetch, 'typesafe_key', lambda: 'k')

    def boom(*a, **k):
        raise OSError('down')

    monkeypatch.setattr(rerank.fetch, '_jev_request', boom)
    assert rerank.jev_scores(['a passage'], 'a question') is None


def test_jev_scores_follow_the_probabilities_in_batches(monkeypatch):
    monkeypatch.setattr(rerank.fetch, 'typesafe_key', lambda: 'k')
    calls = []

    def fake(state, questions, key):
        calls.append(len(questions))
        return {'answers': {q: {'probabilities': {'3': 1.0} if state['passages'][q].startswith('good') else {'0': 1.0}}
                            for q in questions}}

    monkeypatch.setattr(rerank.fetch, '_jev_request', fake)
    passages = ['good one'] + ['bad'] * 40
    scores = rerank.jev_scores(passages, 'q')
    assert scores[0] == 1.0 and max(scores[1:]) == 0.0
    assert calls == [30, 11]
