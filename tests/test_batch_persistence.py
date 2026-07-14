#!/usr/bin/env python3
"""Tests for the batch persistence paths.

`register-sources` and `add-batch` exist so a retrieval batch costs ONE process spawn
and ONE dedup index build, instead of one per record. These tests pin both the
correctness (dedup, identity stability) and the batching property itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CM = Path(__file__).parent.parent / 'scripts' / 'citation_manager.py'
ES = Path(__file__).parent.parent / 'scripts' / 'evidence_store.py'


def run(script: Path, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f'{script.name} failed: {result.stderr}')
    return json.loads(result.stdout)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


class TestRegisterSourcesBatch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        run(CM, 'init-run', '--out-dir', str(self.dir), '--query', 'q', '--mode', 'standard')

    def tearDown(self):
        self._tmp.cleanup()

    def _batch_file(self, records: list[dict]) -> Path:
        p = self.dir / 'batch.jsonl'
        p.write_text('\n'.join(json.dumps(r) for r in records) + '\n')
        return p

    def test_registers_many_sources_in_one_call(self):
        batch = self._batch_file([
            {'raw_url': 'https://a.example/1', 'title': 'A'},
            {'raw_url': 'https://b.example/2', 'title': 'B'},
            {'raw_url': 'https://c.example/3', 'title': 'C'},
        ])
        out = run(CM, 'register-sources', '--jsonl-file', str(batch), '--dir', str(self.dir))
        self.assertEqual(out['registered'], 3)
        self.assertEqual(out['duplicates'], 0)
        self.assertEqual(len(read_jsonl(self.dir / 'sources.jsonl')), 3)

    def test_dedupes_within_the_batch(self):
        batch = self._batch_file([
            {'raw_url': 'https://a.example/1', 'title': 'A'},
            {'raw_url': 'https://a.example/1', 'title': 'A again'},
        ])
        out = run(CM, 'register-sources', '--jsonl-file', str(batch), '--dir', str(self.dir))
        self.assertEqual(out['registered'], 1)
        self.assertEqual(out['duplicates'], 1)
        self.assertEqual(len(read_jsonl(self.dir / 'sources.jsonl')), 1)

    def test_dedupes_against_already_registered_sources(self):
        run(CM, 'register-source', '--json', json.dumps(
            {'raw_url': 'https://a.example/1', 'title': 'A'}), '--dir', str(self.dir))
        batch = self._batch_file([
            {'raw_url': 'https://a.example/1', 'title': 'A'},
            {'raw_url': 'https://new.example/2', 'title': 'New'},
        ])
        out = run(CM, 'register-sources', '--jsonl-file', str(batch), '--dir', str(self.dir))
        self.assertEqual(out['registered'], 1)
        self.assertEqual(out['duplicates'], 1)

    def test_batch_ids_match_single_registration_ids(self):
        """Identity must be independent of the path used to register."""
        single_dir = Path(tempfile.mkdtemp())
        run(CM, 'init-run', '--out-dir', str(single_dir), '--query', 'q', '--mode', 'standard')
        rec = {'raw_url': 'https://doi.org/10.1234/abc', 'title': 'A'}

        single = run(CM, 'register-source', '--json', json.dumps(rec), '--dir', str(single_dir))
        batch = self._batch_file([rec])
        batched = run(CM, 'register-sources', '--jsonl-file', str(batch), '--dir', str(self.dir))

        self.assertEqual(single['source_id'], batched['sources'][0]['source_id'])

    def test_bad_record_is_reported_not_fatal(self):
        batch = self._batch_file([
            {'raw_url': 'https://a.example/1', 'title': 'A'},
            {'title': 'no url at all'},
        ])
        out = run(CM, 'register-sources', '--jsonl-file', str(batch), '--dir', str(self.dir))
        self.assertEqual(out['registered'], 1)
        self.assertEqual(out['errors'], 1)

    def test_json_array_form(self):
        out = run(CM, 'register-sources', '--json', json.dumps([
            {'raw_url': 'https://a.example/1', 'title': 'A'},
            {'raw_url': 'https://b.example/2', 'title': 'B'},
        ]), '--dir', str(self.dir))
        self.assertEqual(out['registered'], 2)


class TestEvidenceAddBatch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        run(CM, 'init-run', '--out-dir', str(self.dir), '--query', 'q', '--mode', 'standard')
        self.sid = run(CM, 'register-source', '--json', json.dumps(
            {'raw_url': 'https://a.example/1', 'title': 'A'}), '--dir', str(self.dir))['source_id']

    def tearDown(self):
        self._tmp.cleanup()

    def _batch_file(self, records: list[dict]) -> Path:
        p = self.dir / 'ev.jsonl'
        p.write_text('\n'.join(json.dumps(r) for r in records) + '\n')
        return p

    def test_adds_many_spans_in_one_call(self):
        batch = self._batch_file([
            {'source_id': self.sid, 'quote': 'first span', 'locator': 'p1'},
            {'source_id': self.sid, 'quote': 'second span', 'locator': 'p2'},
            {'source_id': self.sid, 'quote': 'third span', 'locator': 'p3'},
        ])
        out = run(ES, 'add-batch', '--jsonl-file', str(batch), '--dir', str(self.dir))
        self.assertEqual(out['added'], 3)
        self.assertEqual(len(read_jsonl(self.dir / 'evidence.jsonl')), 3)

    def test_dedupes_identical_spans(self):
        batch = self._batch_file([
            {'source_id': self.sid, 'quote': 'same span', 'locator': 'p1'},
            {'source_id': self.sid, 'quote': 'same span', 'locator': 'p1'},
        ])
        out = run(ES, 'add-batch', '--jsonl-file', str(batch), '--dir', str(self.dir))
        self.assertEqual(out['added'], 1)
        self.assertEqual(out['duplicates'], 1)

    def test_batch_ids_match_single_add_ids(self):
        rec = {'source_id': self.sid, 'quote': 'a quote', 'locator': 'p5'}
        single = run(ES, 'add', '--json', json.dumps(rec), '--dir', str(self.dir))

        other = Path(tempfile.mkdtemp())
        run(CM, 'init-run', '--out-dir', str(other), '--query', 'q', '--mode', 'standard')
        p = other / 'ev.jsonl'
        p.write_text(json.dumps(rec) + '\n')
        batched = run(ES, 'add-batch', '--jsonl-file', str(p), '--dir', str(other))

        self.assertEqual(single['evidence_id'], batched['evidence'][0]['evidence_id'])

    def test_invalid_evidence_type_falls_back(self):
        batch = self._batch_file([
            {'source_id': self.sid, 'quote': 'q', 'evidence_type': 'nonsense'},
        ])
        run(ES, 'add-batch', '--jsonl-file', str(batch), '--dir', str(self.dir))
        rows = read_jsonl(self.dir / 'evidence.jsonl')
        self.assertEqual(rows[0]['evidence_type'], 'direct_quote')

    def test_missing_quote_is_reported_not_fatal(self):
        batch = self._batch_file([
            {'source_id': self.sid, 'quote': 'good'},
            {'source_id': self.sid},
        ])
        out = run(ES, 'add-batch', '--jsonl-file', str(batch), '--dir', str(self.dir))
        self.assertEqual(out['added'], 1)
        self.assertEqual(out['errors'], 1)


class TestRunManifest(unittest.TestCase):
    def test_manifest_records_websearch_primary_brightdata_fallback(self):
        """The provider posture: free built-ins first, paid Bright Data as fallback."""
        with tempfile.TemporaryDirectory() as tmp:
            run(CM, 'init-run', '--out-dir', tmp, '--query', 'q', '--mode', 'standard')
            manifest = json.loads((Path(tmp) / 'run_manifest.json').read_text())
            self.assertEqual(manifest['provider_config']['primary'], 'websearch')
            self.assertEqual(manifest['provider_config']['fallback'], 'brightdata')


if __name__ == '__main__':
    unittest.main()
