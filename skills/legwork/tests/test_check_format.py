"""The gate infers the document's format instead of assuming a report.

Found by measurement, not by reading. In the eval run on 2026-08-13 the agent
gated a brief with the default flags, was told it was missing four sections a
brief never has, and only then passed --format brief and passed clean.

A gate whose default verdict is wrong on a whole format is worse than no gate:
it costs a cycle every time, and it teaches the reader that the gate is
something to argue with rather than something to fix.
"""

import subprocess
import sys

import check
from conftest import fixture


def run_gate(name, *extra):
    return subprocess.run(
        [sys.executable, check.__file__, '--report', fixture(name), '--level', 'deep', *extra],
        capture_output=True, text=True, timeout=60)


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def test_an_executive_summary_makes_it_a_report():
    assert check.infer_format('# T\n\n## Executive Summary\n\nx') == 'report'


def test_anything_else_is_a_brief():
    assert check.infer_format('# T\n\n## Findings\n\nx') == 'brief'


# ---------------------------------------------------------------------------
# The trap that was measured
# ---------------------------------------------------------------------------

def test_a_valid_brief_passes_with_no_format_flag():
    result = run_gate('valid_brief.md')
    assert result.returncode == 0, result.stdout
    assert 'brief format' in result.stdout


def test_a_valid_report_passes_with_no_format_flag():
    result = run_gate('valid_report.md')
    assert result.returncode == 0, result.stdout
    assert 'report format' in result.stdout


def test_the_brief_is_not_asked_for_report_only_sections():
    """The specific spurious failure: Executive Summary, Introduction, Synthesis
    and Recommendations are report sections, and a brief has none of them."""
    result = run_gate('valid_brief.md')
    for section in ('Executive Summary', 'Introduction', 'Synthesis', 'Recommendations'):
        assert 'missing section: {}'.format(section) not in result.stdout


# ---------------------------------------------------------------------------
# An explicit flag still wins
# ---------------------------------------------------------------------------

def test_an_explicit_format_overrides_inference():
    """Forcing report format on a brief must still fail, or the override is a
    lie and nobody can gate a half-written report as the report it will be."""
    result = run_gate('valid_brief.md', '--format', 'report')
    assert result.returncode != 0
    assert 'missing section: Executive Summary' in result.stdout
