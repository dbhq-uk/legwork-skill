import os
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_ROOT, 'scripts'))

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')


def fixture(name):
    return os.path.join(FIXTURES, name)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch, tmp_path_factory):
    """No test may reach a paid or keyed service. With a TypeSafe key on the
    machine (TYPESAFE_API_KEY or ~/.dbhq/legwork/typesafe-api-key), reranking
    would call Jev for real; every test runs with neither, and a test that
    needs a key sets its own."""
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    monkeypatch.setenv('HOME', str(tmp_path_factory.mktemp('home')))
