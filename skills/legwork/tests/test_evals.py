"""The eval set has to stay well-formed, or it rots into decoration.

These tests do not run the evaluations - that needs a live agent and is not
hermetic. They pin the structure, so a case cannot lose its expectations or its
link back to the failure it reproduces without the build noticing.
"""

import json
import os

import pytest

from conftest import SKILL_ROOT

REPO_ROOT = os.path.dirname(os.path.dirname(SKILL_ROOT))
EVALS_PATH = os.path.join(REPO_ROOT, 'evals', 'evals.json')

with open(EVALS_PATH, encoding='utf-8') as handle:
    SUITE = json.load(handle)

CASES = SUITE['evals']


def test_the_suite_meets_the_documented_floor():
    """Anthropic's authoring checklist puts the floor at three."""
    assert len(CASES) >= 3


def test_ids_are_unique():
    ids = [case['id'] for case in CASES]
    assert len(ids) == len(set(ids))


def test_names_are_unique_and_kebab_case():
    names = [case['name'] for case in CASES]
    assert len(names) == len(set(names))
    for name in names:
        assert name == name.lower()
        assert ' ' not in name


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_every_case_carries_the_required_fields(case):
    for field in ('id', 'name', 'prompt', 'expected_output', 'expectations',
                  'files', 'observed_failure'):
        assert field in case, '{} is missing {}'.format(case.get('name'), field)


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_every_case_records_the_failure_it_reproduces(case):
    """The rule that keeps this set honest: a case exists because something went
    wrong, not because it seemed like a good idea."""
    assert len(case['observed_failure']) > 40


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_expectations_are_observable_and_plural(case):
    assert len(case['expectations']) >= 3
    for expectation in case['expectations']:
        assert expectation.strip()
        assert expectation[0].isupper()


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_the_prompt_is_what_a_user_would_actually_type(case):
    assert case['prompt'].strip()
    assert not case['prompt'].startswith('You are')


def test_the_readme_lists_every_case():
    """A case absent from the README is a case nobody scores."""
    with open(os.path.join(REPO_ROOT, 'evals', 'README.md'), encoding='utf-8') as handle:
        readme = handle.read()
    for case in CASES:
        assert case['name'] in readme, '{} is not described in the README'.format(case['name'])
