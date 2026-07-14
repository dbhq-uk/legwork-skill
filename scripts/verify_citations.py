#!/usr/bin/env python3
"""
Citation Verification Script

Catches fabricated citations by checking:
1. DOI resolution (via doi.org)
2. Basic metadata matching (title similarity, year match)
3. URL accessibility verification
4. Hallucination pattern detection (generic titles, suspicious patterns)
5. Flags suspicious entries for manual review

Usage:
    python verify_citations.py --report [path]
    python verify_citations.py --report [path] --offline  # No network: local checks only
    python verify_citations.py --report [path] --strict   # Fail on any unverified

Does NOT require API keys - uses free DOI resolver and heuristics.

Cost policy: network verification (DOI resolution + URL reachability) is the
expensive part. It runs concurrently across a thread pool, results are cached
per-run so retry cycles never re-fetch the same DOI/URL, and `--offline` skips
it entirely. quick/standard research modes should pass --offline; deep and
ultradeep run the full network pass. See reference/quality-gates.md.
"""

from __future__ import annotations

import sys
import argparse
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict, Tuple
from urllib import request, error
from urllib.parse import quote
import json
from datetime import datetime

# Concurrency for the network pass. Modest: we are hitting doi.org and arbitrary
# publisher hosts, and politeness matters more than shaving the last second.
MAX_WORKERS = 8
NETWORK_TIMEOUT = 10


class CitationVerifier:
    """Verify citations in research report"""

    def __init__(self, report_path: Path, strict_mode: bool = False, offline: bool = False):
        self.report_path = report_path
        self.strict_mode = strict_mode
        self.offline = offline
        self.content = self._read_report()
        self.suspicious = []
        self.verified = []
        self.errors = []

        # Per-run caches: a DOI or URL is fetched at most once even across the
        # up-to-3 validation retry cycles in quality-gates.md.
        self._doi_cache: Dict[str, Tuple[bool, Dict]] = {}
        self._url_cache: Dict[str, Tuple[bool, str]] = {}
        self._cache_lock = threading.Lock()

        # Hallucination detection patterns (2025 CiteGuard enhancement)
        self.suspicious_patterns = [
            # Generic academic-sounding but fake patterns
            (r'^(A |An |The )?(Study|Analysis|Review|Survey|Investigation) (of|on|into)',
             "Generic academic title pattern"),
            (r'^(Recent|Current|Modern|Contemporary) (Advances|Developments|Trends) in',
             "Generic 'advances' title pattern"),
            # Too perfect, templated titles
            (r'^[A-Z][a-z]+ [A-Z][a-z]+: A (Comprehensive|Complete|Systematic) (Review|Analysis|Guide)$',
             "Too perfect, templated structure"),
        ]

    def _read_report(self) -> str:
        """Read report file"""
        try:
            with open(self.report_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"L ERROR: Cannot read report: {e}")
            sys.exit(1)

    def extract_bibliography(self) -> List[Dict]:
        """Extract bibliography entries from report"""
        pattern = r'## Bibliography(.*?)(?=##|\Z)'
        match = re.search(pattern, self.content, re.DOTALL | re.IGNORECASE)

        if not match:
            self.errors.append("No Bibliography section found")
            return []

        bib_section = match.group(1)

        # Parse entries: [N] Author (Year). "Title". Venue. URL
        entries = []
        lines = bib_section.strip().split('\n')

        current_entry = None
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if starts with citation number [N]
            match_num = re.match(r'^\[(\d+)\]\s+(.+)$', line)
            if match_num:
                if current_entry:
                    entries.append(current_entry)

                num = match_num.group(1)
                rest = match_num.group(2)

                # Try to parse: Author (Year). "Title". Venue. URL
                year_match = re.search(r'\((\d{4})\)', rest)
                title_match = re.search(r'"([^"]+)"', rest)
                doi_match = re.search(r'doi\.org/(10\.\S+)', rest)
                url_match = re.search(r'https?://[^\s\)]+', rest)

                current_entry = {
                    'num': num,
                    'raw': rest,
                    'year': year_match.group(1) if year_match else None,
                    'title': title_match.group(1) if title_match else None,
                    'doi': doi_match.group(1) if doi_match else None,
                    'url': url_match.group(0) if url_match else None
                }
            elif current_entry:
                # Multi-line entry, append to raw
                current_entry['raw'] += ' ' + line

        if current_entry:
            entries.append(current_entry)

        return entries

    def extract_body_citations(self) -> set:
        """Citation numbers [N] used in the report body (everything before Bibliography)."""
        body = re.split(r'##\s*Bibliography', self.content, flags=re.IGNORECASE)[0]
        return {int(n) for n in re.findall(r'\[(\d+)\]', body)}

    def verify_doi(self, doi: str) -> Tuple[bool, Dict]:
        """
        Verify DOI exists and get metadata. Cached per run.
        Returns (success, metadata_dict)
        """
        if not doi:
            return False, {}

        with self._cache_lock:
            if doi in self._doi_cache:
                return self._doi_cache[doi]

        result = self._fetch_doi(doi)
        with self._cache_lock:
            self._doi_cache[doi] = result
        return result

    def _fetch_doi(self, doi: str) -> Tuple[bool, Dict]:
        try:
            # Use content negotiation to get JSON metadata
            url = f"https://doi.org/{quote(doi)}"
            req = request.Request(url)
            req.add_header('Accept', 'application/vnd.citationstyles.csl+json')

            with request.urlopen(req, timeout=NETWORK_TIMEOUT) as response:
                data = json.loads(response.read().decode('utf-8'))

                return True, {
                    'title': data.get('title', ''),
                    'year': data.get('issued', {}).get('date-parts', [[None]])[0][0],
                    'authors': [
                        f"{a.get('family', '')} {a.get('given', '')}"
                        for a in data.get('author', [])
                    ],
                    'venue': data.get('container-title', '')
                }
        except error.HTTPError as e:
            if e.code == 404:
                return False, {'error': 'DOI not found (404)'}
            return False, {'error': f'HTTP {e.code}'}
        except Exception as e:
            return False, {'error': str(e)}

    def verify_url(self, url: str) -> Tuple[bool, str]:
        """
        Verify URL is accessible (2025 CiteGuard enhancement). Cached per run.
        Returns (accessible, status_message)
        """
        if not url:
            return False, "No URL"

        with self._cache_lock:
            if url in self._url_cache:
                return self._url_cache[url]

        result = self._fetch_url(url)
        with self._cache_lock:
            self._url_cache[url] = result
        return result

    def _fetch_url(self, url: str) -> Tuple[bool, str]:
        try:
            # HEAD request to check accessibility without downloading
            req = request.Request(url, method='HEAD')
            req.add_header('User-Agent', 'Mozilla/5.0 (Research Citation Verifier)')

            with request.urlopen(req, timeout=NETWORK_TIMEOUT) as response:
                if response.status == 200:
                    return True, "URL accessible"
                else:
                    return False, f"HTTP {response.status}"
        except error.HTTPError as e:
            return False, f"HTTP {e.code}"
        except error.URLError as e:
            return False, f"URL error: {e.reason}"
        except Exception as e:
            return False, f"Connection error: {str(e)[:50]}"

    def detect_hallucination_patterns(self, entry: Dict) -> List[str]:
        """
        Detect common LLM hallucination patterns in citations (2025 CiteGuard).
        Returns list of detected issues.
        """
        issues = []
        title = entry.get('title', '')

        if not title:
            return issues

        # Check against suspicious patterns
        for pattern, description in self.suspicious_patterns:
            if re.match(pattern, title, re.IGNORECASE):
                issues.append(f"Suspicious title pattern: {description}")

        # Check for overly generic titles
        generic_words = ['overview', 'introduction', 'guide', 'handbook', 'manual']
        if any(word in title.lower() for word in generic_words) and len(title.split()) < 5:
            issues.append("Very generic short title")

        # Check for placeholder-like titles
        if any(x in title.lower() for x in ['tbd', 'todo', 'placeholder', 'example']):
            issues.append("Placeholder text in title")

        # Check for inconsistent metadata
        if entry.get('year'):
            year = int(entry['year'])
            current_year = datetime.now().year
            # Very recent without DOI or URL is suspicious
            if year >= current_year - 1 and not entry.get('doi') and not entry.get('url'):
                issues.append(f"Recent year ({year}) with no verification method")
            # Future year is definitely wrong
            if year > current_year:
                issues.append(f"Future year: {year} (current: {current_year})")
            # Very old with modern phrasing is suspicious
            if year < 2000 and any(word in title.lower() for word in ['ai', 'llm', 'gpt', 'transformer']):
                issues.append(f"Anachronistic: pre-2000 ({year}) citation mentioning modern AI terms")

        return issues

    def check_title_similarity(self, title1: str, title2: str) -> float:
        """
        Simple title similarity check (word overlap).
        Returns score 0.0-1.0
        """
        if not title1 or not title2:
            return 0.0

        # Normalize: lowercase, remove punctuation, split
        def normalize(s):
            s = s.lower()
            s = re.sub(r'[^\w\s]', ' ', s)
            return set(s.split())

        words1 = normalize(title1)
        words2 = normalize(title2)

        if not words1 or not words2:
            return 0.0

        overlap = len(words1 & words2)
        total = len(words1 | words2)

        return overlap / total if total > 0 else 0.0

    def verify_entry(self, entry: Dict) -> Dict:
        """Verify a single bibliography entry (Enhanced 2025 with CiteGuard).

        Thread-safe: performs no printing, so it can run inside a thread pool.
        In offline mode only local heuristics run - zero network calls.
        """
        result = {
            'num': entry['num'],
            'status': 'unknown',
            'issues': [],
            'metadata': {},
            'verification_methods': []
        }

        # STEP 1: Hallucination detection (CiteGuard 2025) - always local.
        hallucination_issues = self.detect_hallucination_patterns(entry)
        if hallucination_issues:
            result['issues'].extend(hallucination_issues)
            result['status'] = 'suspicious'

        # STEP 2: No verification method at all is suspicious in any mode.
        if not entry['doi'] and not entry['url']:
            result['issues'].append("No DOI or URL - cannot verify")
            result['status'] = 'suspicious'
            return result

        # OFFLINE: stop here. The entry is well-formed (has a DOI or a URL) and
        # cleared the local heuristics; we simply cannot confirm that it resolves.
        if self.offline:
            if result['status'] != 'suspicious':
                result['status'] = 'format_ok'
            result['verification_methods'].append('local-only')
            return result

        # STEP 3: Has DOI?
        if entry['doi']:
            success, metadata = self.verify_doi(entry['doi'])

            if success:
                result['metadata'] = metadata
                result['status'] = 'verified'
                result['verification_methods'].append('DOI')

                # Check title similarity if we have both
                if entry['title'] and metadata.get('title'):
                    similarity = self.check_title_similarity(
                        entry['title'],
                        metadata['title']
                    )

                    if similarity < 0.5:
                        result['issues'].append(
                            f"Title mismatch (similarity: {similarity:.1%})"
                        )
                        result['status'] = 'suspicious'

                # Check year match
                if entry['year'] and metadata.get('year'):
                    if int(entry['year']) != int(metadata['year']):
                        result['issues'].append(
                            f"Year mismatch: report says {entry['year']}, DOI says {metadata['year']}"
                        )
                        result['status'] = 'suspicious'

            else:
                result['status'] = 'unverified'
                result['issues'].append(
                    f"DOI resolution failed: {metadata.get('error', 'unknown')}"
                )

        # STEP 4: Check URL accessibility (if no DOI, or the DOI failed)
        if entry['url'] and result['status'] != 'verified':
            url_ok, url_status = self.verify_url(entry['url'])
            if url_ok:
                result['verification_methods'].append('URL')
                if result['status'] in ['unknown', 'no_doi', 'unverified']:
                    result['status'] = 'url_verified'
            else:
                result['issues'].append(f"URL check failed: {url_status}")

        return result

    def check_citation_coverage(self, entries: List[Dict]) -> List[str]:
        """Local cross-check: every [N] in the body has a bibliography entry, and vice versa."""
        issues = []
        body_nums = self.extract_body_citations()
        bib_nums = {int(e['num']) for e in entries}

        dangling = sorted(body_nums - bib_nums)
        if dangling:
            issues.append(
                "Cited in body but missing from bibliography: "
                + ', '.join(f'[{n}]' for n in dangling)
            )

        orphaned = sorted(bib_nums - body_nums)
        if orphaned:
            issues.append(
                "In bibliography but never cited in body: "
                + ', '.join(f'[{n}]' for n in orphaned)
            )

        return issues

    def verify_all(self):
        """Verify all bibliography entries."""
        mode_label = (
            "OFFLINE (local checks only)" if self.offline
            else f"NETWORK ({MAX_WORKERS} workers)"
        )
        print(f"\n{'='*60}")
        print(f"CITATION VERIFICATION: {self.report_path.name}")
        print(f"Mode: {mode_label}")
        print(f"{'='*60}\n")

        entries = self.extract_bibliography()

        if not entries:
            print("FAIL: No bibliography entries found\n")
            return False

        print(f"Found {len(entries)} citations\n")

        # Local cross-check: free, and catches the most common real defect.
        coverage_issues = self.check_citation_coverage(entries)
        if coverage_issues:
            print("CITATION COVERAGE ISSUES:")
            for issue in coverage_issues:
                print(f"  - {issue}")
            print()

        if self.offline:
            results = [self.verify_entry(e) for e in entries]
        else:
            # Network pass runs concurrently; the caches dedupe repeated DOIs/URLs.
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                results = list(pool.map(self.verify_entry, entries))

        print(f"{'='*60}")
        print("VERIFICATION SUMMARY")
        print(f"{'='*60}\n")

        verified = [r for r in results if r['status'] == 'verified']
        url_verified = [r for r in results if r['status'] == 'url_verified']
        format_ok = [r for r in results if r['status'] == 'format_ok']
        suspicious = [r for r in results if r['status'] == 'suspicious']
        unverified = [r for r in results if r['status'] in ['unverified', 'no_doi', 'unknown']]

        if self.offline:
            print(f'Well-formed (not network-verified): {len(format_ok)}/{len(results)}')
        else:
            print(f'DOI Verified: {len(verified)}/{len(results)}')
            print(f'URL Verified: {len(url_verified)}/{len(results)}')
            print(f'Unverified: {len(unverified)}/{len(results)}')
        print(f'Suspicious: {len(suspicious)}/{len(results)}')
        print()

        if suspicious:
            print('SUSPICIOUS CITATIONS (Manual Review Needed):')
            for r in suspicious:
                print(f"\n  [{r['num']}]")
                for issue in r['issues']:
                    print(f"    - {issue}")
            print()

        if unverified:
            print('UNVERIFIED CITATIONS (Could not check):')
            for r in unverified:
                print(f"  [{r['num']}] {r['issues'][0] if r['issues'] else 'Unknown'}")
            print()

        # Decision. Coverage problems are structural: they fail in strict mode.
        if coverage_issues and self.strict_mode:
            print('STRICT MODE: Failing due to citation coverage issues')
            return False

        if suspicious:
            print('WARNING: Suspicious citations detected')
            if self.strict_mode:
                print('  STRICT MODE: Failing due to suspicious citations')
                return False
            print('  (Continuing in non-strict mode)')

        if self.offline:
            # Nothing was network-checked, so a verified-ratio gate is meaningless.
            print('OFFLINE CITATION CHECK PASSED (formatting + heuristics only)')
            return True

        if self.strict_mode and unverified:
            print('STRICT MODE: Unverified citations found')
            return False

        total_verified = len(verified) + len(url_verified)
        if total_verified / len(results) < 0.5:
            print('WARNING: Less than 50% citations verified')
            return True  # Pass with warning
        print('CITATION VERIFICATION PASSED')
        return True


def main():
    parser = argparse.ArgumentParser(
        description="Verify citations in research report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python verify_citations.py --report report.md

Note: Requires internet connection to check DOIs.
Uses free DOI resolver - no API key needed.
        """
    )

    parser.add_argument(
        '--report', '-r',
        type=str,
        required=True,
        help='Path to research report markdown file'
    )

    parser.add_argument(
        '--strict',
        action='store_true',
        help='Strict mode: fail on any unverified or suspicious citations'
    )

    parser.add_argument(
        '--offline',
        action='store_true',
        help='Skip all network calls (DOI + URL). Local heuristics and citation '
             'coverage checks only. Use for quick/standard research modes.'
    )

    args = parser.parse_args()
    report_path = Path(args.report)

    if not report_path.exists():
        print(f"ERROR: Report file not found: {report_path}")
        sys.exit(1)

    verifier = CitationVerifier(report_path, strict_mode=args.strict, offline=args.offline)
    passed = verifier.verify_all()

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
