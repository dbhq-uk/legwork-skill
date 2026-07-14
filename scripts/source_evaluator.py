#!/usr/bin/env python3
"""
Source Credibility Evaluator
Assesses source quality, credibility, and potential biases.

This is the skill's re-ranker: search providers return SERP order, and everything
downstream (Triangulate, Critique, which sources anchor major claims) ranks on the
scores produced here.

CLI:
    # Score a batch of sources (one JSON object per line: url, title, date, author)
    python source_evaluator.py score --jsonl-file sources.jsonl

    # Score a single source
    python source_evaluator.py score --url https://... --title "..." --date 2026-01-15

User-extensible domain tiers:
    Put your recurring research domains in ~/.deep-research/domains.json (or point
    $DEEP_RESEARCH_DOMAINS at another file):

        {"high": ["mytrustedjournal.org"], "moderate": ["someblog.dev"], "low": ["contentfarm.io"]}

    These merge OVER the built-in tiers, so unknown-but-trusted domains in your niche
    stop flattening to the 55/100 default.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urlparse
from datetime import datetime, timedelta

# Where user-defined domain tiers live. Env var wins, then the dotfile.
USER_DOMAINS_ENV = 'DEEP_RESEARCH_DOMAINS'
USER_DOMAINS_PATH = Path.home() / '.deep-research' / 'domains.json'


def load_user_domains() -> Dict[str, set]:
    """Load user domain tier overrides. Returns {'high': set, 'moderate': set, 'low': set}.

    Never raises: a malformed config warns on stderr and is ignored, because a bad
    dotfile must not take down a research run.
    """
    empty = {'high': set(), 'moderate': set(), 'low': set()}

    path_str = os.environ.get(USER_DOMAINS_ENV)
    path = Path(path_str) if path_str else USER_DOMAINS_PATH
    if not path.exists():
        return empty

    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        print(f"warning: ignoring malformed {path}: {e}", file=sys.stderr)
        return empty

    if not isinstance(data, dict):
        print(f"warning: ignoring {path}: expected a JSON object", file=sys.stderr)
        return empty

    out = {}
    for tier in ('high', 'moderate', 'low'):
        vals = data.get(tier, [])
        if not isinstance(vals, list):
            print(f"warning: ignoring '{tier}' in {path}: expected a list", file=sys.stderr)
            vals = []
        out[tier] = {str(d).lower().lstrip('.') for d in vals}
    return out


@dataclass
class CredibilityScore:
    """Represents source credibility assessment"""
    overall_score: float  # 0-100
    domain_authority: float  # 0-100
    recency: float  # 0-100
    expertise: float  # 0-100
    bias_score: float  # 0-100 (higher = more neutral)
    factors: Dict[str, str]
    recommendation: str  # "high_trust", "moderate_trust", "low_trust", "verify"


class SourceEvaluator:
    """Evaluates source credibility and quality"""

    # Domain reputation tiers
    HIGH_AUTHORITY_DOMAINS = {
        # Academic & Research
        'arxiv.org', 'nature.com', 'science.org', 'cell.com', 'nejm.org',
        'thelancet.com', 'springer.com', 'sciencedirect.com', 'plos.org',
        'ieee.org', 'acm.org', 'pubmed.ncbi.nlm.nih.gov',

        # Government & International Organizations
        'nih.gov', 'cdc.gov', 'who.int', 'fda.gov', 'nasa.gov',
        'gov.uk', 'europa.eu', 'un.org',

        # Established Tech Documentation
        'docs.python.org', 'developer.mozilla.org', 'docs.microsoft.com',
        'cloud.google.com', 'aws.amazon.com', 'kubernetes.io',

        # Reputable News (Fact-check verified)
        'reuters.com', 'apnews.com', 'bbc.com', 'economist.com',
        'nature.com/news', 'scientificamerican.com'
    }

    MODERATE_AUTHORITY_DOMAINS = {
        # Tech News & Analysis
        'techcrunch.com', 'theverge.com', 'arstechnica.com', 'wired.com',
        'zdnet.com', 'cnet.com',

        # Industry Publications
        'forbes.com', 'bloomberg.com', 'wsj.com', 'ft.com',

        # Educational
        'wikipedia.org', 'britannica.com', 'khanacademy.org',

        # Tech Blogs (established)
        'medium.com', 'dev.to', 'stackoverflow.com', 'github.com'
    }

    LOW_AUTHORITY_INDICATORS = [
        'blogspot.com', 'wordpress.com', 'wix.com', 'substack.com'
    ]

    def __init__(self, user_domains: Optional[Dict[str, set]] = None):
        """Merge user tier overrides over the built-ins.

        User entries take precedence: a domain listed in the user's 'low' tier is low
        even if the built-ins call it high.
        """
        user = user_domains if user_domains is not None else load_user_domains()
        self.user_high = user.get('high', set())
        self.user_moderate = user.get('moderate', set())
        self.user_low = user.get('low', set())

        self.high_domains = self.HIGH_AUTHORITY_DOMAINS | self.user_high
        self.moderate_domains = self.MODERATE_AUTHORITY_DOMAINS | self.user_moderate

    @staticmethod
    def _domain_in(domain: str, tier: set) -> bool:
        """Exact match, or a subdomain of a tier entry (news.nature.com -> nature.com)."""
        if domain in tier:
            return True
        return any(domain.endswith('.' + entry) for entry in tier)

    def evaluate_source(
        self,
        url: str,
        title: str,
        content: Optional[str] = None,
        publication_date: Optional[str] = None,
        author: Optional[str] = None
    ) -> CredibilityScore:
        """Evaluate source credibility"""

        domain = self._extract_domain(url)

        # Calculate component scores
        domain_score = self._evaluate_domain_authority(domain)
        recency_score = self._evaluate_recency(publication_date)
        expertise_score = self._evaluate_expertise(domain, title, author)
        bias_score = self._evaluate_bias(domain, title, content)

        # Calculate overall score (weighted average)
        overall = (
            domain_score * 0.35 +
            recency_score * 0.20 +
            expertise_score * 0.25 +
            bias_score * 0.20
        )

        # Determine factors
        factors = self._identify_factors(
            domain, domain_score, recency_score, expertise_score, bias_score
        )

        # Generate recommendation
        recommendation = self._generate_recommendation(overall)

        return CredibilityScore(
            overall_score=round(overall, 2),
            domain_authority=round(domain_score, 2),
            recency=round(recency_score, 2),
            expertise=round(expertise_score, 2),
            bias_score=round(bias_score, 2),
            factors=factors,
            recommendation=recommendation
        )

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove www prefix
        domain = domain.replace('www.', '')
        return domain

    def _evaluate_domain_authority(self, domain: str) -> float:
        """Evaluate domain authority (0-100).

        User tiers are checked first so an explicit local override always wins over
        the built-in lists. Matching accepts subdomains (news.nature.com -> nature.com).
        """
        # User overrides win outright.
        if self._domain_in(domain, self.user_low):
            return 40.0
        if self._domain_in(domain, self.user_high):
            return 90.0
        if self._domain_in(domain, self.user_moderate):
            return 70.0

        if self._domain_in(domain, self.high_domains):
            return 90.0
        if self._domain_in(domain, self.moderate_domains):
            return 70.0
        if any(indicator in domain for indicator in self.LOW_AUTHORITY_INDICATORS):
            return 40.0
        # Unknown domain - moderate skepticism
        return 55.0

    def _evaluate_recency(self, publication_date: Optional[str]) -> float:
        """Evaluate information recency (0-100)"""
        if not publication_date:
            return 50.0  # Unknown date

        try:
            pub_date = datetime.fromisoformat(publication_date.replace('Z', '+00:00'))
            age = datetime.now() - pub_date

            # Recency scoring
            if age < timedelta(days=90):  # < 3 months
                return 100.0
            elif age < timedelta(days=365):  # < 1 year
                return 85.0
            elif age < timedelta(days=730):  # < 2 years
                return 70.0
            elif age < timedelta(days=1825):  # < 5 years
                return 50.0
            else:
                return 30.0

        except Exception:
            return 50.0

    def _evaluate_expertise(
        self,
        domain: str,
        title: str,
        author: Optional[str]
    ) -> float:
        """Evaluate source expertise (0-100)"""
        score = 50.0

        # Academic/research domains get high expertise
        if any(d in domain for d in ['arxiv', 'nature', 'science', 'ieee', 'acm']):
            score += 30

        # Government/official sources
        if '.gov' in domain or 'who.int' in domain:
            score += 25

        # Technical documentation
        if 'docs.' in domain or 'documentation' in title.lower():
            score += 20

        # Author credentials (if available)
        if author:
            if any(title in author.lower() for title in ['dr.', 'phd', 'professor']):
                score += 15

        return min(score, 100.0)

    def _evaluate_bias(
        self,
        domain: str,
        title: str,
        content: Optional[str]
    ) -> float:
        """Evaluate potential bias (0-100, higher = more neutral)"""
        score = 70.0  # Start neutral

        # Check for sensationalism in title
        sensational_indicators = [
            '!', 'shocking', 'unbelievable', 'you won\'t believe',
            'secret', 'they don\'t want you to know'
        ]
        title_lower = title.lower()
        if any(indicator in title_lower for indicator in sensational_indicators):
            score -= 20

        # Academic sources are typically less biased
        if any(d in domain for d in ['arxiv', 'nature', 'science', 'ieee']):
            score += 20

        # Check for balance in content (if available)
        if content:
            # Look for balanced language
            balanced_indicators = ['however', 'although', 'on the other hand', 'critics argue']
            if any(indicator in content.lower() for indicator in balanced_indicators):
                score += 10

        return min(max(score, 0), 100.0)

    def _identify_factors(
        self,
        domain: str,
        domain_score: float,
        recency_score: float,
        expertise_score: float,
        bias_score: float
    ) -> Dict[str, str]:
        """Identify key credibility factors"""
        factors = {}

        if domain_score >= 85:
            factors['domain'] = "High authority domain"
        elif domain_score <= 45:
            factors['domain'] = "Low authority domain - verify claims"

        if recency_score >= 85:
            factors['recency'] = "Recent information"
        elif recency_score <= 40:
            factors['recency'] = "Outdated information - verify currency"

        if expertise_score >= 80:
            factors['expertise'] = "Expert source"
        elif expertise_score <= 45:
            factors['expertise'] = "Limited expertise indicators"

        if bias_score >= 80:
            factors['bias'] = "Balanced perspective"
        elif bias_score <= 50:
            factors['bias'] = "Potential bias detected"

        return factors

    def _generate_recommendation(self, overall_score: float) -> str:
        """Generate trust recommendation"""
        if overall_score >= 80:
            return "high_trust"
        elif overall_score >= 60:
            return "moderate_trust"
        elif overall_score >= 40:
            return "low_trust"
        else:
            return "verify"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _score_record(evaluator: SourceEvaluator, rec: dict) -> dict:
    """Score one source record. Accepts the loose shape emitted by bd_search/WebSearch."""
    url = rec.get('url') or rec.get('raw_url') or ''
    title = rec.get('title') or ''
    # `date` is what the search wrappers emit; `publication_date` is the long form.
    pub_date = rec.get('publication_date') or rec.get('date')

    score = evaluator.evaluate_source(
        url=url,
        title=title,
        content=rec.get('content') or rec.get('snippet'),
        publication_date=pub_date,
        author=rec.get('author'),
    )
    out = dict(rec)
    out['credibility'] = asdict(score)
    return out


def cmd_score(args: argparse.Namespace) -> None:
    evaluator = SourceEvaluator()

    if args.jsonl_file:
        records = []
        with open(args.jsonl_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    elif args.url:
        records = [{'url': args.url, 'title': args.title or '', 'date': args.date}]
    else:
        print('error: one of --jsonl-file or --url is required', file=sys.stderr)
        sys.exit(1)

    scored = [_score_record(evaluator, r) for r in records]
    scored.sort(key=lambda r: r['credibility']['overall_score'], reverse=True)

    if args.format == 'jsonl':
        for r in scored:
            print(json.dumps(r, ensure_ascii=False))
    elif args.format == 'json':
        print(json.dumps(scored, indent=2, ensure_ascii=False))
    else:  # table
        print(f"{'SCORE':>6}  {'TRUST':<15} {'DOMAIN':<28} TITLE")
        for r in scored:
            c = r['credibility']
            domain = urlparse(r.get('url') or r.get('raw_url') or '').netloc.replace('www.', '')
            title = (r.get('title') or '')[:50]
            print(f"{c['overall_score']:>6.1f}  {c['recommendation']:<15} {domain:<28} {title}")

    if args.min_score is not None:
        kept = [r for r in scored if r['credibility']['overall_score'] >= args.min_score]
        print(
            f"\n{len(kept)}/{len(scored)} sources at or above min-score {args.min_score}",
            file=sys.stderr,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog='source_evaluator',
        description='Deterministic source credibility scoring (the deep-research re-ranker)',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    p_score = sub.add_parser('score', help='Score one source or a batch of sources')
    p_score.add_argument('--jsonl-file', help='File with one source JSON object per line')
    p_score.add_argument('--url', help='Score a single URL')
    p_score.add_argument('--title', default='', help='Title for the single-URL form')
    p_score.add_argument('--date', default=None, help='ISO publication date (improves recency score)')
    p_score.add_argument('--format', default='table', choices=['table', 'json', 'jsonl'])
    p_score.add_argument('--min-score', type=float, default=None,
                         help='Report how many sources meet this threshold')

    args = parser.parse_args()
    {'score': cmd_score}[args.command](args)


if __name__ == '__main__':
    main()
