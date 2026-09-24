"""brief.py writes the retrieval subagent's brief, so the orchestrator cannot
paraphrase it.

Measured on 2026-09-24: an orchestrator retyped the template and turned the
fetch.py command into "a fetch tool or WebFetch". Its nine subagents made 103
WebFetch calls and 4 fetch.py calls, so the page text of nearly every source
never reached the log. These tests pin that the rendered brief carries the
command with a real path, and that nothing is left for a reader to fill in.
"""

import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from conftest import SKILL_ROOT

import brief

SCRIPT = os.path.join(SKILL_ROOT, 'scripts', 'brief.py')
ANGLE = 'What does Acme charge for its Team plan in the UK?'


def render(*args):
    result = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)
    return result


def test_the_brief_carries_the_fetch_command_with_a_real_path():
    out = render('--angle', ANGLE, '--effort', 'narrow').stdout
    match = re.search(r'python3 (\S+/scripts/fetch\.py) "<url>" --find', out)
    assert match, out
    assert os.path.isabs(match.group(1))
    assert os.path.exists(match.group(1))


def test_the_platforms_command_gets_a_real_path_too():
    out = render('--angle', ANGLE, '--effort', 'narrow').stdout
    match = re.search(r'python3 (\S+/scripts/platforms\.py) search', out)
    assert match and os.path.exists(match.group(1)), out


def test_no_placeholder_survives():
    out = render('--angle', ANGLE, '--effort', 'comparison').stdout
    for marker in brief.PLACEHOLDERS:
        assert marker not in out, marker
    assert '{SKILL_DIR}' not in out and '{n}' not in out


def test_the_angle_appears_verbatim_in_the_question_and_the_return_shape():
    out = render('--angle', ANGLE, '--effort', 'narrow').stdout
    assert out.count(ANGLE) == 2, out


def test_the_date_defaults_to_today_in_utc():
    out = render('--angle', ANGLE, '--effort', 'narrow').stdout
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    assert "Today's date is {}.".format(today) in out


def test_an_explicit_date_is_used():
    out = render('--angle', ANGLE, '--effort', 'narrow', '--date', '2026-09-24').stdout
    assert "Today's date is 2026-09-24." in out


def test_a_malformed_date_is_refused():
    result = render('--angle', ANGLE, '--effort', 'narrow', '--date', '24/09/2026')
    assert result.returncode != 0


@pytest.mark.parametrize('effort, phrase, searches', [
    ('narrow', 'This is one narrow fact', '2 to 4 searches.'),
    ('comparison', 'This is a multi-option comparison', '4 to 8 searches.'),
])
def test_effort_picks_one_sentence_and_a_search_budget(effort, phrase, searches):
    out = render('--angle', ANGLE, '--effort', effort).stdout
    assert phrase in out and searches in out
    other = 'multi-option comparison' if effort == 'narrow' else 'one narrow fact'
    assert other not in out


def test_the_search_budget_can_be_set():
    out = render('--angle', ANGLE, '--effort', 'narrow', '--searches', '1-2').stdout
    assert '1 to 2 searches.' in out


def test_the_return_only_rule_is_still_the_last_line():
    """Models weight the final instruction; the template keeps it last on purpose."""
    out = render('--angle', ANGLE, '--effort', 'narrow').stdout
    assert out.rstrip().splitlines()[-1] == 'first object is discarded.'


def test_the_output_is_the_brief_and_nothing_else():
    out = render('--angle', ANGLE, '--effort', 'narrow').stdout
    assert out.startswith('You have zero prior context.')


def test_a_multi_line_angle_is_collapsed_to_one_line():
    out = render('--angle', 'What does\n  Acme   charge?', '--effort', 'narrow').stdout
    assert out.count('What does Acme charge?') == 2


def test_an_empty_angle_is_refused():
    assert render('--angle', '   ', '--effort', 'narrow').returncode != 0


def test_the_template_still_has_every_placeholder_the_script_fills():
    """If someone edits the template in subagent-brief.md, the script must fail
    loudly rather than print a brief with a hole in it."""
    template = brief.read_template()
    for marker in brief.PLACEHOLDERS:
        assert marker in template, marker


def test_a_template_missing_a_placeholder_is_refused():
    template = brief.read_template().replace('{SKILL_DIR}', '/somewhere')
    with pytest.raises(brief.TemplateChanged):
        brief.fill(template, ANGLE, 'narrow', '2026-09-24', None)
