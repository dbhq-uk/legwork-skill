#!/usr/bin/env python3
"""Tests for verify_citations.py.

IMPORTANT: these tests never touch the network. The offline path is exercised via the
CLI; the network path is exercised by stubbing the fetch methods, which also proves the
per-run cache actually prevents refetching (the property that makes the deep-mode
retry cycles affordable).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from verify_citations import CitationVerifier  # noqa: E402

SCRIPT = Path(__file__).parent.parent / 'scripts' / 'verify_citations.py'
FIXTURES = Path(__file__).parent / 'fixtures'


def run_verify(report: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), '--report', str(report), *flags],
        capture_output=True, text=True,
    )


class TestOfflineMode(unittest.TestCase):
    """--offline is the quick/standard gate: local checks only, zero network."""

    def test_offline_passes_valid_report(self):
        result = run_verify(FIXTURES / 'valid_report.md', '--offline')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('OFFLINE', result.stdout)

    def test_offline_passes_valid_brief(self):
        result = run_verify(FIXTURES / 'valid_brief.md', '--offline')
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_offline_makes_no_network_calls(self):
        """Hard guarantee: if offline ever calls out, these stubs blow up."""
        v = CitationVerifier(FIXTURES / 'valid_report.md', offline=True)

        def explode(*_args, **_kwargs):
            raise AssertionError('offline mode attempted a network call')

        v._fetch_doi = explode
        v._fetch_url = explode
        self.assertTrue(v.verify_all())

    def test_offline_still_flags_entry_with_no_doi_and_no_url(self):
        content = (
            '# T\n\n## Findings\n\nClaim [1].\n\n## Limitations\n\nSome.\n\n'
            '## Bibliography\n\n[1] Nobody (2026). "A Paper With No Locator". Nowhere.\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'r.md'
            p.write_text(content)
            v = CitationVerifier(p, offline=True)
            entries = v.extract_bibliography()
            result = v.verify_entry(entries[0])
            self.assertEqual(result['status'], 'suspicious')
            self.assertTrue(any('No DOI or URL' in i for i in result['issues']))


class TestCitationCoverage(unittest.TestCase):
    """The local cross-check that catches the defect that actually happens."""

    def _verifier(self, tmp: str, content: str) -> CitationVerifier:
        p = Path(tmp) / 'r.md'
        p.write_text(content)
        return CitationVerifier(p, offline=True)

    def test_dangling_body_citation_is_reported(self):
        content = (
            '# T\n\n## Findings\n\nClaim [1]. Another claim [7].\n\n'
            '## Bibliography\n\n[1] A (2026). "T". https://example.com\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            v = self._verifier(tmp, content)
            issues = v.check_citation_coverage(v.extract_bibliography())
            self.assertTrue(any('[7]' in i and 'missing from bibliography' in i for i in issues))

    def test_orphaned_bibliography_entry_is_reported(self):
        content = (
            '# T\n\n## Findings\n\nClaim [1].\n\n'
            '## Bibliography\n\n[1] A (2026). "T". https://example.com\n'
            '[2] B (2026). "U". https://example.org\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            v = self._verifier(tmp, content)
            issues = v.check_citation_coverage(v.extract_bibliography())
            self.assertTrue(any('[2]' in i and 'never cited' in i for i in issues))

    def test_clean_report_has_no_coverage_issues(self):
        v = CitationVerifier(FIXTURES / 'valid_brief.md', offline=True)
        self.assertEqual(v.check_citation_coverage(v.extract_bibliography()), [])

    def test_coverage_issue_fails_in_strict_mode(self):
        content = (
            '# T\n\n## Findings\n\nClaim [1]. Fabricated [9].\n\n'
            '## Bibliography\n\n[1] A (2026). "T". https://example.com\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'r.md'
            p.write_text(content)
            result = run_verify(p, '--offline', '--strict')
            self.assertEqual(result.returncode, 1)


class TestNetworkCaching(unittest.TestCase):
    """The per-run cache is what makes the deep-mode retry cycles affordable."""

    def test_repeated_doi_is_fetched_once(self):
        content = (
            '# T\n\n## Findings\n\nA [1]. B [2].\n\n## Bibliography\n\n'
            '[1] A (2026). "One". https://doi.org/10.1234/same\n'
            '[2] B (2026). "Two". https://doi.org/10.1234/same\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'r.md'
            p.write_text(content)
            v = CitationVerifier(p)

            calls = []

            def fake_fetch(doi):
                calls.append(doi)
                return True, {'title': 'One', 'year': 2026}

            v._fetch_doi = fake_fetch
            v.verify_all()

            # Two entries, same DOI -> exactly one fetch.
            self.assertEqual(len(calls), 1, f'expected 1 fetch, got {len(calls)}: {calls}')

    def test_repeated_url_is_fetched_once(self):
        content = (
            '# T\n\n## Findings\n\nA [1]. B [2].\n\n## Bibliography\n\n'
            '[1] A (2026). "One". https://example.com/same\n'
            '[2] B (2026). "Two". https://example.com/same\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'r.md'
            p.write_text(content)
            v = CitationVerifier(p)

            calls = []

            def fake_fetch(url):
                calls.append(url)
                return True, 'URL accessible'

            v._fetch_url = fake_fetch
            v.verify_all()
            self.assertEqual(len(calls), 1, f'expected 1 fetch, got {len(calls)}: {calls}')


class TestHallucinationHeuristics(unittest.TestCase):
    def _verify_entry(self, raw: str) -> dict:
        content = f'# T\n\n## Findings\n\nClaim [1].\n\n## Bibliography\n\n[1] {raw}\n'
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'r.md'
            p.write_text(content)
            v = CitationVerifier(p, offline=True)
            return v.verify_entry(v.extract_bibliography()[0])

    def test_future_year_is_flagged(self):
        r = self._verify_entry('X (2999). "A Real Title About Things". https://example.com')
        self.assertEqual(r['status'], 'suspicious')
        self.assertTrue(any('Future year' in i for i in r['issues']))

    def test_placeholder_title_is_flagged(self):
        r = self._verify_entry('X (2024). "TODO placeholder title here". https://example.com')
        self.assertEqual(r['status'], 'suspicious')

    def test_well_formed_entry_is_not_flagged(self):
        r = self._verify_entry(
            'Okafor, N. (2025). "Benchmarking pgvector against dedicated engines". '
            'Example Blog. https://example.com/x'
        )
        self.assertEqual(r['status'], 'format_ok')


if __name__ == '__main__':
    unittest.main()
