"""The Stop hook: the gate stops being optional.

Every other check in legwork is only as reliable as the agent's memory at the
end of a long run. These tests pin the three behaviours that decide whether the
hook is an improvement or a liability: it blocks a failing report, it stays out
of the way otherwise, and it never takes the session down with it.
"""

import importlib.util
import json
import os
import subprocess
import sys

import pytest

from conftest import SKILL_ROOT

HOOK = os.path.join(os.path.dirname(os.path.dirname(SKILL_ROOT)), 'hooks', 'gate_on_stop.py')


def load_hook():
    spec = importlib.util.spec_from_file_location('gate_on_stop', HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = load_hook()


FAILING = """# A run that looks finished

## Findings

### Finding 1: Something is true

It is definitely true.

## Limitations

TBD

## Bibliography

[1] Somewhere https://example.com/a
"""

PASSING = open(os.path.join(SKILL_ROOT, 'tests', 'fixtures', 'valid_brief.md'),
               encoding='utf-8').read()


def build_run(tmp_path, name, body, tsv=None):
    folder = tmp_path / 'docs' / 'research' / name
    folder.mkdir(parents=True)
    (folder / (name + '.md')).write_text(body, encoding='utf-8')
    if tsv:
        (folder / (name + '.tsv')).write_text(tsv, encoding='utf-8')
    return folder


def run_hook(cwd, stop_hook_active=False, level='deep'):
    env = dict(os.environ,
               LEGWORK_SKILL_DIR=SKILL_ROOT,
               LEGWORK_DEFAULT_MODE=level)
    env.pop('LEGWORK_OUTPUT', None)
    result = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps({'cwd': str(cwd), 'stop_hook_active': stop_hook_active}),
        capture_output=True, text=True, env=env, timeout=60)
    return result


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------

def test_a_failing_report_blocks_the_end_of_the_turn(tmp_path):
    build_run(tmp_path, 'Broken_Research_20260812', FAILING)
    result = run_hook(tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload['decision'] == 'block'
    assert 'does not pass its own gate' in payload['reason']


def test_the_block_names_what_actually_failed(tmp_path):
    build_run(tmp_path, 'Broken_Research_20260812', FAILING)
    payload = json.loads(run_hook(tmp_path).stdout)
    assert 'placeholder' in payload['reason'].lower() or 'TBD' in payload['reason']


def test_the_block_points_at_the_command_that_fixes_it(tmp_path):
    build_run(tmp_path, 'Broken_Research_20260812', FAILING)
    payload = json.loads(run_hook(tmp_path).stdout)
    assert 'finish.py' in payload['reason']


# ---------------------------------------------------------------------------
# Staying out of the way
# ---------------------------------------------------------------------------

def test_a_passing_brief_is_silent(tmp_path):
    """A brief must be gated as a brief. Checking it against the report section
    list would fail every quick run for sections a brief never has, and a hook
    that cries wolf is a hook that gets removed."""
    tsv = open(os.path.join(SKILL_ROOT, 'tests', 'fixtures', 'valid_brief.tsv'),
               encoding='utf-8').read()
    build_run(tmp_path, 'Good_Research_20260812', PASSING, tsv=tsv)
    result = run_hook(tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == ''


def test_the_format_is_inferred_from_the_document():
    assert hook.infer_format('# T\n\n## Executive Summary\n') == 'report'
    assert hook.infer_format('# T\n\n## Findings\n') == 'brief'


# ---------------------------------------------------------------------------
# The level a run claims is the level it is held to
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('level', ['quick', 'standard', 'deep'])
def test_the_level_comes_from_the_receipt_line(level):
    head = '# T\n\n*{} - 4 angles, 9 sources, 3 fetched directly*\n'.format(level)
    assert hook.infer_level(head) == level


def test_a_report_with_no_receipt_falls_back_to_the_default():
    assert hook.infer_level('# T\n\n## Findings\n') == 'standard'


def test_a_run_claiming_deep_is_not_checked_as_standard(tmp_path):
    """The hook used to read the level from an environment default, so every
    report was gated at standard - where the entire evidence and independence
    layer is warnings. A run that announces deep must be held to deep."""
    body = FAILING.replace('# A run that looks finished',
                           '# A run that looks finished\n\n*deep - 3 angles, 4 sources*')
    build_run(tmp_path, 'Deep_Research_20260812', body)
    payload = json.loads(run_hook(tmp_path, level='quick').stdout)
    assert payload['decision'] == 'block'


def test_a_repo_with_no_research_folder_is_silent(tmp_path):
    result = run_hook(tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == ''


def test_a_document_that_is_not_a_report_is_ignored(tmp_path):
    """Supporting documents live in the run folder too, and were never meant to
    be gated as reports."""
    folder = tmp_path / 'docs' / 'research' / 'Some_Research_20260812'
    folder.mkdir(parents=True)
    (folder / 'supporting-notes.md').write_text(
        '# Notes\n\n## Background\n\nJust notes.\n', encoding='utf-8')
    result = run_hook(tmp_path)
    assert result.stdout.strip() == ''


def test_an_old_report_is_not_this_session_s_work(tmp_path):
    folder = build_run(tmp_path, 'Ancient_Research_20250101', FAILING)
    old = folder / 'Ancient_Research_20250101.md'
    stale = os.path.getmtime(old) - (hook.RECENT_SECONDS + 3600)
    os.utime(old, (stale, stale))
    assert run_hook(tmp_path).stdout.strip() == ''


# ---------------------------------------------------------------------------
# Never take the session down
# ---------------------------------------------------------------------------

def test_a_second_pass_does_not_block_again(tmp_path):
    """Blocking twice would loop the agent against a gate it may not be able to
    satisfy, which is worse than shipping one bad report."""
    build_run(tmp_path, 'Broken_Research_20260812', FAILING)
    result = run_hook(tmp_path, stop_hook_active=True)
    assert result.returncode == 0
    assert result.stdout.strip() == ''


def test_malformed_input_exits_quietly(tmp_path):
    result = subprocess.run([sys.executable, HOOK], input='not json',
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert result.stdout.strip() == ''


def test_a_missing_gate_never_blocks(tmp_path):
    """If check.py cannot be found the hook has no verdict, and no verdict must
    mean no block. The skill directory here exists but holds no scripts, which
    is what a half-finished install looks like."""
    build_run(tmp_path, 'Broken_Research_20260812', FAILING)
    empty_skill = tmp_path / 'empty-skill'
    empty_skill.mkdir()
    env = dict(os.environ, LEGWORK_SKILL_DIR=str(empty_skill))
    env.pop('LEGWORK_OUTPUT', None)
    result = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps({'cwd': str(tmp_path), 'stop_hook_active': False}),
        capture_output=True, text=True, env=env, timeout=60)
    assert result.returncode == 0
    assert result.stdout.strip() == ''
