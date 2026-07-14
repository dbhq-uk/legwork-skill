#!/usr/bin/env python3
"""Tests for validate_report.py — the always-on structural gate.

Covers both deliverable formats (report / brief) and the defects the validator
exists to catch: missing sections, placeholders, truncation, bibliography gaps.

Purely local: validate_report.py makes no network calls, so neither do these tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / 'scripts' / 'validate_report.py'
FIXTURES = Path(__file__).parent / 'fixtures'


def run_validate(report: Path, fmt: str | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), '--report', str(report)]
    if fmt:
        cmd += ['--format', fmt]
    return subprocess.run(cmd, capture_output=True, text=True)


class TestReportFormat(unittest.TestCase):
    """The full 8-section report format (deep/ultradeep default)."""

    def test_valid_report_passes(self):
        result = run_validate(FIXTURES / 'valid_report.md')
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_valid_report_passes_explicit_format(self):
        result = run_validate(FIXTURES / 'valid_report.md', fmt='report')
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_invalid_report_fails(self):
        result = run_validate(FIXTURES / 'invalid_report.md')
        self.assertEqual(result.returncode, 1)
        self.assertIn('VALIDATION FAILED', result.stdout)

    def test_report_format_is_default(self):
        """No --format flag means report format, so the brief fixture must fail it."""
        result = run_validate(FIXTURES / 'valid_brief.md')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Missing sections', result.stdout)


class TestBriefFormat(unittest.TestCase):
    """The findings-memo format (quick/standard default)."""

    def test_valid_brief_passes(self):
        result = run_validate(FIXTURES / 'valid_brief.md', fmt='brief')
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_brief_does_not_require_executive_summary(self):
        """The whole point of brief: no Executive Summary / Introduction / Methodology."""
        content = (FIXTURES / 'valid_brief.md').read_text()
        self.assertNotIn('## Executive Summary', content)
        self.assertNotIn('## Introduction', content)
        result = run_validate(FIXTURES / 'valid_brief.md', fmt='brief')
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_brief_still_requires_bibliography(self):
        """Brief drops ceremony, never rigor: a missing bibliography is still fatal."""
        content = (FIXTURES / 'valid_brief.md').read_text()
        stripped = content.split('## Bibliography')[0]
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'no_bib.md'
            p.write_text(stripped)
            result = run_validate(p, fmt='brief')
            self.assertEqual(result.returncode, 1)
            self.assertIn('Bibliography', result.stdout)

    def test_brief_still_requires_findings(self):
        content = (FIXTURES / 'valid_brief.md').read_text().replace('## Findings', '## Stuff')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'no_findings.md'
            p.write_text(content)
            result = run_validate(p, fmt='brief')
            self.assertEqual(result.returncode, 1)
            self.assertIn('Findings', result.stdout)

    def test_brief_rejects_placeholders(self):
        content = (FIXTURES / 'valid_brief.md').read_text().replace(
            'At our current corpus size', 'TODO: write this. At our current corpus size'
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'placeholder.md'
            p.write_text(content)
            result = run_validate(p, fmt='brief')
            self.assertEqual(result.returncode, 1)
            self.assertIn('placeholder', result.stdout.lower())


class TestRigorChecks(unittest.TestCase):
    """Checks that must fire in BOTH formats."""

    def _write(self, tmp: str, content: str) -> Path:
        p = Path(tmp) / 'r.md'
        p.write_text(content)
        return p

    def test_bibliography_range_placeholder_is_fatal(self):
        """'[3-9] Additional citations' is the classic unusable-bibliography defect."""
        content = (FIXTURES / 'valid_brief.md').read_text()
        content = content.replace(
            '[9] Postgres Documentation (2026). "Index maintenance and VACUUM". '
            'https://www.postgresql.org/docs/current/routine-vacuuming.html '
            '(Retrieved: 2026-07-14)',
            '[9-10] Additional citations available on request',
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_validate(self._write(tmp, content), fmt='brief')
            self.assertEqual(result.returncode, 1)
            self.assertIn('truncation placeholder', result.stdout.lower())

    def test_content_truncation_is_fatal(self):
        content = (FIXTURES / 'valid_brief.md').read_text().replace(
            '## So What', '## So What\n\nContent continues in the full version.\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_validate(self._write(tmp, content), fmt='brief')
            self.assertEqual(result.returncode, 1)
            self.assertIn('truncation', result.stdout.lower())

    def test_citation_without_bibliography_entry_is_fatal(self):
        """A [99] in the body with no [99] in the bibliography = fabricated citation."""
        content = (FIXTURES / 'valid_brief.md').read_text().replace(
            'within our 100ms budget', 'within our 100ms budget [99]'
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = run_validate(self._write(tmp, content), fmt='brief')
            self.assertEqual(result.returncode, 1)
            self.assertIn('99', result.stdout)

    def test_no_citations_at_all_is_fatal(self):
        content = "# Title\n\n## Findings\n\nSome unsourced prose.\n\n## Limitations\n\nMany.\n\n## Bibliography\n\n[1] x\n"
        with tempfile.TemporaryDirectory() as tmp:
            result = run_validate(self._write(tmp, content), fmt='brief')
            self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
