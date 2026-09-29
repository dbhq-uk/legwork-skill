import json
import os
import sys

import pytest

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_ROOT, 'scripts'))

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def fixture(name):
    return os.path.join(FIXTURES, name)


@pytest.fixture(autouse=True)
def _copy_ledgers_with_logs(monkeypatch):
    """A fixture's fetch log travels with its round ledger (<stem>.entities.json).

    The gate requires recorded retrieval rounds at standard and deep, and every
    fixture log has a saturated ledger beside it. Tests copy logs into tmp
    folders with shutil.copy; this copies the ledger alongside, so the test
    keeps checking what it was written to check.
    """
    import shutil as _shutil
    real = _shutil.copy

    def copy(src, dst, *args, **kwargs):
        out = real(src, dst, *args, **kwargs)
        src_ledger = os.path.splitext(str(src))[0] + '.entities.json'
        if str(src).endswith('.tsv') and os.path.exists(src_ledger):
            target = str(dst)
            if os.path.isdir(target):
                target = os.path.join(target, os.path.basename(str(src)))
            real(src_ledger, os.path.splitext(target)[0] + '.entities.json')
        return out

    monkeypatch.setattr(_shutil, 'copy', copy)


def saturated_ledger(tsv):
    """Write a saturated round ledger beside a test's fetch log, as a run whose
    retrieval rounds stopped finding anything new would leave."""
    ledger = {'fixture angle': {'rounds': [{'entities': 0, 'new_entities': [], 'new_parties': ['fixture.example']},
                                           {'entities': 0, 'new_entities': [], 'new_parties': []}],
                                'entities': {}, 'parties': ['fixture.example']}}
    with open(os.path.splitext(str(tsv))[0] + '.entities.json', 'w', encoding='utf-8') as handle:
        json.dump(ledger, handle)
