#!/usr/bin/env python3
"""Tests for source_evaluator.py — the deep-research re-ranker.

Covers the scoring behaviour that determines which sources anchor major claims, plus
the user-extensible domain tiers that let recurring research topics get their trusted
domains registered without editing source.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from source_evaluator import SourceEvaluator, load_user_domains  # noqa: E402

SCRIPT = Path(__file__).parent.parent / 'scripts' / 'source_evaluator.py'

NO_USER_DOMAINS = {'high': set(), 'moderate': set(), 'low': set()}


class TestDomainAuthority(unittest.TestCase):
    def setUp(self):
        self.ev = SourceEvaluator(user_domains=NO_USER_DOMAINS)

    def test_high_authority_domain(self):
        self.assertEqual(self.ev._evaluate_domain_authority('nature.com'), 90.0)

    def test_moderate_authority_domain(self):
        self.assertEqual(self.ev._evaluate_domain_authority('techcrunch.com'), 70.0)

    def test_low_authority_indicator(self):
        self.assertEqual(self.ev._evaluate_domain_authority('someblog.wordpress.com'), 40.0)

    def test_unknown_domain_gets_neutral_skepticism(self):
        self.assertEqual(self.ev._evaluate_domain_authority('obscure-journal.example'), 55.0)

    def test_subdomain_inherits_parent_tier(self):
        """news.nature.com should inherit nature.com's tier, not flatten to 55."""
        self.assertEqual(self.ev._evaluate_domain_authority('news.nature.com'), 90.0)

    def test_subdomain_matching_does_not_overmatch(self):
        """notnature.com must NOT match nature.com."""
        self.assertEqual(self.ev._evaluate_domain_authority('notnature.com'), 55.0)


class TestUserDomainTiers(unittest.TestCase):
    """The mechanism that makes this useful for a specific person's research niche."""

    def test_user_can_promote_unknown_domain(self):
        ev = SourceEvaluator(user_domains={
            'high': {'obscure-journal.example'}, 'moderate': set(), 'low': set(),
        })
        self.assertEqual(ev._evaluate_domain_authority('obscure-journal.example'), 90.0)

    def test_user_can_demote_builtin_domain(self):
        """A user override beats the built-in tier outright."""
        ev = SourceEvaluator(user_domains={
            'high': set(), 'moderate': set(), 'low': {'nature.com'},
        })
        self.assertEqual(ev._evaluate_domain_authority('nature.com'), 40.0)

    def test_user_promotion_applies_to_subdomains(self):
        ev = SourceEvaluator(user_domains={
            'high': {'mylab.example'}, 'moderate': set(), 'low': set(),
        })
        self.assertEqual(ev._evaluate_domain_authority('papers.mylab.example'), 90.0)


class TestUserDomainConfigLoading(unittest.TestCase):
    def test_missing_config_returns_empty_tiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['DEEP_RESEARCH_DOMAINS'] = str(Path(tmp) / 'nonexistent.json')
            try:
                self.assertEqual(load_user_domains(), NO_USER_DOMAINS)
            finally:
                del os.environ['DEEP_RESEARCH_DOMAINS']

    def test_malformed_config_is_ignored_not_fatal(self):
        """A bad dotfile must never take down a research run."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'domains.json'
            p.write_text('{ this is not json')
            os.environ['DEEP_RESEARCH_DOMAINS'] = str(p)
            try:
                self.assertEqual(load_user_domains(), NO_USER_DOMAINS)
            finally:
                del os.environ['DEEP_RESEARCH_DOMAINS']

    def test_valid_config_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'domains.json'
            p.write_text(json.dumps({'high': ['a.example'], 'low': ['b.example']}))
            os.environ['DEEP_RESEARCH_DOMAINS'] = str(p)
            try:
                loaded = load_user_domains()
                self.assertEqual(loaded['high'], {'a.example'})
                self.assertEqual(loaded['low'], {'b.example'})
                self.assertEqual(loaded['moderate'], set())
            finally:
                del os.environ['DEEP_RESEARCH_DOMAINS']


class TestRecency(unittest.TestCase):
    def setUp(self):
        self.ev = SourceEvaluator(user_domains=NO_USER_DOMAINS)

    def test_missing_date_flattens_to_neutral(self):
        """Known limitation: SERP rarely returns dates, so this is the common path."""
        self.assertEqual(self.ev._evaluate_recency(None), 50.0)

    def test_unparseable_date_flattens_to_neutral(self):
        self.assertEqual(self.ev._evaluate_recency('last Tuesday'), 50.0)

    def test_fresh_source_scores_top(self):
        recent = (datetime.now() - timedelta(days=10)).date().isoformat()
        self.assertEqual(self.ev._evaluate_recency(recent), 100.0)

    def test_old_source_scores_low(self):
        old = (datetime.now() - timedelta(days=2000)).date().isoformat()
        self.assertEqual(self.ev._evaluate_recency(old), 30.0)

    def test_backfilled_date_beats_missing_date(self):
        """Why date backfill matters: a fresh source outranks an undated one."""
        fresh = (datetime.now() - timedelta(days=30)).date().isoformat()
        self.assertGreater(self.ev._evaluate_recency(fresh), self.ev._evaluate_recency(None))


class TestOverallScoring(unittest.TestCase):
    def test_high_authority_recent_source_is_high_trust(self):
        ev = SourceEvaluator(user_domains=NO_USER_DOMAINS)
        recent = (datetime.now() - timedelta(days=20)).date().isoformat()
        score = ev.evaluate_source(
            url='https://www.nature.com/articles/x',
            title='Quantum error correction at scale',
            publication_date=recent,
        )
        self.assertEqual(score.recommendation, 'high_trust')
        self.assertGreaterEqual(score.overall_score, 80)

    def test_sensational_blog_is_low_trust(self):
        ev = SourceEvaluator(user_domains=NO_USER_DOMAINS)
        score = ev.evaluate_source(
            url='https://x.wordpress.com/y',
            title="SHOCKING! You won't believe this secret discovery!",
            publication_date='2019-01-01',
        )
        self.assertIn(score.recommendation, ('low_trust', 'verify'))


class TestCLI(unittest.TestCase):
    """The documented 'score each source' step must have a runnable form."""

    def test_batch_scoring_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'sources.jsonl'
            src.write_text(
                json.dumps({'url': 'https://www.nature.com/a', 'title': 'A'}) + '\n'
                + json.dumps({'url': 'https://x.wordpress.com/b', 'title': 'B'}) + '\n'
            )
            result = subprocess.run(
                [sys.executable, str(SCRIPT), 'score', '--jsonl-file', str(src),
                 '--format', 'json'],
                capture_output=True, text=True, env={**os.environ, 'DEEP_RESEARCH_DOMAINS': str(Path(tmp) / 'none.json')},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            scored = json.loads(result.stdout)
            self.assertEqual(len(scored), 2)
            # Output must be ranked: this script IS the re-ranker.
            self.assertGreater(
                scored[0]['credibility']['overall_score'],
                scored[1]['credibility']['overall_score'],
            )
            self.assertEqual(scored[0]['title'], 'A')

    def test_single_url_scoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), 'score', '--url', 'https://arxiv.org/abs/1',
                 '--title', 'A paper', '--format', 'json'],
                capture_output=True, text=True,
                env={**os.environ, 'DEEP_RESEARCH_DOMAINS': str(Path(tmp) / 'none.json')},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            scored = json.loads(result.stdout)
            self.assertEqual(len(scored), 1)
            self.assertEqual(scored[0]['credibility']['domain_authority'], 90.0)

    def test_cli_requires_an_input(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), 'score'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
