#!/usr/bin/env python3
"""
Report Validation Script
Ensures research deliverables meet quality standards before delivery.

Two formats, matching the skill's two deliverable shapes:

  --format report  (default) full 8-section research report; the deep/ultradeep shape
  --format brief   findings memo; the quick/standard shape

Brief drops the scaffolding sections (Executive Summary, Introduction, Methodology
Appendix) but keeps every rigor check: citations, complete bibliography, no
placeholders, no truncation.

Purely local: this script makes no network calls.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict

# Section requirements per format. Brief keeps the substance, drops the ceremony.
REQUIRED_SECTIONS = {
    'report': [
        "Executive Summary",
        "Introduction",
        "Main Analysis",
        "Synthesis",
        "Limitations",
        "Recommendations",
        "Bibliography",
        "Methodology",
    ],
    'brief': [
        "Findings",
        "Limitations",
        "Bibliography",
    ],
}

RECOMMENDED_SECTIONS = {
    'report': ["Counterevidence Register", "Claims-Evidence Table"],
    'brief': ["So What"],
}

# Minimum sensible length per format (words). Below this, warn.
MIN_WORDS = {'report': 500, 'brief': 300}


class ReportValidator:
    """Validates research report quality"""

    def __init__(self, report_path: Path, fmt: str = 'report'):
        self.report_path = report_path
        self.format = fmt
        self.content = self._read_report()
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def _read_report(self) -> str:
        """Read report file"""
        try:
            with open(self.report_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"❌ ERROR: Cannot read report: {e}")
            sys.exit(1)

    def validate(self) -> bool:
        """Run all validation checks"""
        print(f"\n{'='*60}")
        print(f"VALIDATING {self.format.upper()}: {self.report_path.name}")
        print(f"{'='*60}\n")

        checks = [
            ("Required Sections", self._check_required_sections),
            ("Citations", self._check_citations),
            ("Bibliography", self._check_bibliography),
            ("Placeholder Text", self._check_placeholders),
            ("Content Truncation", self._check_content_truncation),
            ("Word Count", self._check_word_count),
            ("Source Count", self._check_source_count),
            ("Broken Links", self._check_broken_references),
        ]

        # The executive-summary length gate only applies to the full report format.
        if self.format == 'report':
            checks.insert(0, ("Executive Summary", self._check_executive_summary))

        for check_name, check_func in checks:
            print(f"⏳ Checking: {check_name}...", end=" ")
            passed = check_func()
            if passed:
                print("✅ PASS")
            else:
                print("❌ FAIL")

        self._print_summary()

        return len(self.errors) == 0

    def _check_executive_summary(self) -> bool:
        """Check executive summary exists and is 200-400 words"""
        pattern = r'## Executive Summary(.*?)(?=##|\Z)'
        match = re.search(pattern, self.content, re.DOTALL | re.IGNORECASE)

        if not match:
            self.errors.append("Missing 'Executive Summary' section")
            return False

        summary = match.group(1).strip()
        word_count = len(summary.split())

        if word_count > 400:
            self.warnings.append(f"Executive summary too long: {word_count} words (should be ≤400)")

        if word_count < 50:
            self.warnings.append(f"Executive summary too short: {word_count} words (should be ≥50)")

        return True

    def _check_required_sections(self) -> bool:
        """Check all required sections for this format are present"""
        required = REQUIRED_SECTIONS[self.format]
        recommended = RECOMMENDED_SECTIONS[self.format]

        missing = []
        for section in required:
            if not re.search(rf'##.*{section}', self.content, re.IGNORECASE):
                missing.append(section)

        if missing:
            self.errors.append(f"Missing sections: {', '.join(missing)}")
            return False

        # Check recommended sections (warnings only)
        missing_recommended = []
        for section in recommended:
            if not re.search(rf'##.*{section}', self.content, re.IGNORECASE):
                missing_recommended.append(section)

        if missing_recommended:
            self.warnings.append(
                f"Missing recommended sections: {', '.join(missing_recommended)}"
            )

        return True

    def _body(self) -> str:
        """Report content EXCLUDING the bibliography.

        Citation checks must look only here: the bibliography is a list of [N] entries,
        so counting it as 'citations' would let a report with zero inline citations pass
        purely on the strength of having a bibliography.
        """
        return re.split(r'##\s*Bibliography', self.content, flags=re.IGNORECASE)[0]

    def _check_citations(self) -> bool:
        """Check citation format and presence in the report BODY"""
        citations = re.findall(r'\[(\d+)\]', self._body())

        if not citations:
            self.errors.append(
                "No citations found in the report body "
                "(a bibliography alone does not count — claims must be cited inline)"
            )
            return False

        unique_citations = set(citations)

        if len(unique_citations) < 10:
            self.warnings.append(f"Only {len(unique_citations)} unique sources cited (recommended: ≥10)")

        # Check for consecutive citation numbers
        citation_nums = sorted([int(c) for c in unique_citations])
        if citation_nums:
            max_citation = max(citation_nums)
            expected = set(range(1, max_citation + 1))
            missing = expected - set(citation_nums)

            if missing:
                self.warnings.append(f"Non-consecutive citation numbers, missing: {sorted(missing)}")

        return True

    def _check_bibliography(self) -> bool:
        """Check bibliography exists, matches citations, and has no truncation placeholders"""
        pattern = r'## Bibliography(.*?)(?=##|\Z)'
        match = re.search(pattern, self.content, re.DOTALL | re.IGNORECASE)

        if not match:
            self.errors.append("Missing 'Bibliography' section")
            return False

        bib_section = match.group(1)

        # CRITICAL: Check for truncation placeholders (2025 CiteGuard enhancement)
        truncation_patterns = [
            (r'\[\d+-\d+\]', 'Citation range (e.g., [8-75])'),
            (r'Additional.*citations', 'Phrase "Additional citations"'),
            (r'would be included', 'Phrase "would be included"'),
            (r'\[\.\.\.continue', 'Pattern "[...continue"'),
            (r'\[Continue with', 'Pattern "[Continue with"'),
            (r'etc\.(?!\w)', 'Standalone "etc."'),
            (r'and so on', 'Phrase "and so on"'),
        ]

        for pattern_re, description in truncation_patterns:
            if re.search(pattern_re, bib_section, re.IGNORECASE):
                self.errors.append(f"⚠️ CRITICAL: Bibliography contains truncation placeholder: {description}")
                self.errors.append(f"   This makes the report UNUSABLE - complete bibliography required")
                return False

        # Count bibliography entries [1], [2], etc.
        bib_entries = re.findall(r'^\[(\d+)\]', bib_section, re.MULTILINE)

        if not bib_entries:
            self.errors.append("Bibliography has no entries")
            return False

        # Check citation number continuity (no gaps)
        bib_nums = sorted([int(n) for n in bib_entries])
        if bib_nums:
            expected = list(range(1, bib_nums[-1] + 1))
            actual = bib_nums
            missing = [n for n in expected if n not in actual]
            if missing:
                self.errors.append(f"Bibliography has gaps in numbering: missing {missing}")
                return False

        # Cross-match against BODY citations only (see _body): comparing against the
        # whole document would include the bibliography's own [N] markers, making the
        # 'unused entries' check vacuous.
        body_citations = set(re.findall(r'\[(\d+)\]', self._body()))
        bib_citations = set(bib_entries)

        # Every citation in the body must have a bibliography entry. A [N] with no
        # entry is, in practice, a fabricated citation.
        missing_in_bib = body_citations - bib_citations
        if missing_in_bib:
            self.errors.append(
                f"Citations missing from bibliography: {sorted(int(n) for n in missing_in_bib)}"
            )
            return False

        # Entries nobody cites: usually a leftover from an edited draft.
        unused = bib_citations - body_citations
        if unused:
            self.warnings.append(
                f"Unused bibliography entries: {sorted(int(n) for n in unused)}"
            )

        return True

    def _check_placeholders(self) -> bool:
        """Check for placeholder text that shouldn't be in final report"""
        placeholders = [
            'TBD', 'TODO', 'FIXME', 'XXX',
            '[citation needed]', '[needs citation]',
            '[placeholder]', '[TODO]', '[TBD]'
        ]

        found_placeholders = []
        for placeholder in placeholders:
            if placeholder in self.content:
                found_placeholders.append(placeholder)

        if found_placeholders:
            self.errors.append(f"Found placeholder text: {', '.join(found_placeholders)}")
            return False

        return True

    def _check_content_truncation(self) -> bool:
        """Check for content truncation patterns (2025 Progressive Assembly enhancement)"""
        truncation_patterns = [
            (r'Content continues', 'Phrase "Content continues"'),
            (r'Due to length', 'Phrase "Due to length"'),
            (r'would continue', 'Phrase "would continue"'),
            (r'\[Sections \d+-\d+', 'Pattern "[Sections X-Y"'),
            (r'Additional sections', 'Phrase "Additional sections"'),
            (r'comprehensive.*word document that continues', 'Pattern "comprehensive...document that continues"'),
        ]

        for pattern_re, description in truncation_patterns:
            if re.search(pattern_re, self.content, re.IGNORECASE):
                self.errors.append(f"⚠️ CRITICAL: Content truncation detected: {description}")
                self.errors.append(f"   Report is INCOMPLETE and UNUSABLE - regenerate with progressive assembly")
                return False

        return True

    def _check_word_count(self) -> bool:
        """Check overall deliverable length"""
        word_count = len(self.content.split())
        floor = MIN_WORDS[self.format]

        if word_count < floor:
            self.warnings.append(
                f"{self.format.capitalize()} is very short: {word_count} words "
                f"(expected at least {floor})"
            )
        # No upper limit: word targets are ceilings, not quotas, and progressive
        # assembly supports long reports.

        return True

    def _check_source_count(self) -> bool:
        """Check minimum source count"""
        pattern = r'## Bibliography(.*?)(?=##|\Z)'
        match = re.search(pattern, self.content, re.DOTALL | re.IGNORECASE)

        if not match:
            return True  # Already caught in bibliography check

        bib_section = match.group(1)
        bib_entries = re.findall(r'^\[(\d+)\]', bib_section, re.MULTILINE)

        source_count = len(set(bib_entries))

        if source_count < 10:
            self.warnings.append(f"Only {source_count} sources (recommended: ≥10)")

        return True

    def _check_broken_references(self) -> bool:
        """Check for broken internal references"""
        # Find all markdown links [text](./path)
        internal_links = re.findall(r'\[.*?\]\((\.\/.*?)\)', self.content)

        broken = []
        for link in internal_links:
            # Remove anchor if present
            link_path = link.split('#')[0]
            full_path = self.report_path.parent / link_path

            if not full_path.exists():
                broken.append(link)

        if broken:
            self.errors.append(f"Broken internal links: {', '.join(broken)}")
            return False

        return True

    def _print_summary(self):
        """Print validation summary"""
        print(f"\n{'='*60}")
        print(f"VALIDATION SUMMARY")
        print(f"{'='*60}\n")

        if self.errors:
            print(f"❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"   • {error}")
            print()

        if self.warnings:
            print(f"⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"   • {warning}")
            print()

        if not self.errors and not self.warnings:
            print("✅ ALL CHECKS PASSED - Report meets quality standards!\n")
        elif not self.errors:
            print("✅ VALIDATION PASSED (with warnings)\n")
        else:
            print("❌ VALIDATION FAILED - Please fix errors before delivery\n")


def main():
    parser = argparse.ArgumentParser(
        description="Validate research report quality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python validate_report.py --report report.md                  # full report format
  python validate_report.py --report memo.md --format brief     # findings-memo format
        """
    )

    parser.add_argument(
        '--report', '-r',
        type=str,
        required=True,
        help='Path to the research deliverable (markdown)'
    )

    parser.add_argument(
        '--format', '-f',
        default='report',
        choices=['report', 'brief'],
        help='Deliverable format. "brief" = findings memo (quick/standard default); '
             '"report" = full 8-section report (deep/ultradeep default)'
    )

    args = parser.parse_args()

    report_path = Path(args.report)

    if not report_path.exists():
        print(f"❌ ERROR: Report file not found: {report_path}")
        sys.exit(1)

    validator = ReportValidator(report_path, fmt=args.format)
    passed = validator.validate()

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
