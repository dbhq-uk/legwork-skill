# Wide Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give legwork's retrieval subagents one command, `search.py`, that asks an angle 6 to 10 ways across Bright Data Google and Exa Answer in parallel and returns ranked leads, while subagents still open and read the pages; and add a gate check that a comparison-table row about an entity cites a page opened on that entity's own site.

**Architecture:** `search.py` is a standalone standard-library script that fans each wording out to `bd_search.py` as a killable subprocess and the angle to Exa over HTTPS, merges by canonical URL, ranks by reciprocal rank fusion (averaged with Jev when available), writes a per-call search record beside the run, and prints compact text. It writes nothing to the run's `.tsv`. Separately, subagents may return an entity's own site; `sources.py` and `ledger.py` store it, and `check.py` fails a matrix row that cites no opened page on it.

**Tech Stack:** Python 3.9+, standard library only; pytest for tests (hermetic: network and subprocess patched).

**Spec:** `docs/superpowers/specs/2026-10-17-wide-search-design.md` (in this repository). Read it before starting any task; this plan implements it section by section.

**Working copy:** `~/dbhq-uk/legwork-skill-wide-search`, branch `feat/wide-search-design`. All paths below are relative to that directory. Run tests from `skills/legwork`.

## Global Constraints

- Standard library only. No `requirements.txt`, no third-party import. CI fails any import outside the standard library and the skill's own scripts.
- Python floor 3.9. Every new script starts with `from __future__ import annotations`.
- Tests are hermetic: no network, ever. Patch `subprocess.run`, `subprocess.Popen`, `os.killpg` and `urlopen`. A test that needs a socket is a defect.
- British English in prose and messages. Plain hyphens only: no em dashes, no en dashes (CI fails them).
- `party_of` in `independence.py` is not changed by any task.
- No task writes search leads into the run's `.tsv`.
- The subagent brief's last line stays `first object is discarded.`
- Each rule is stated once (`AGENTS.md`): the wording rule lives only in `SKILL.md` between `<!-- wordings-rule -->` and `<!-- /wordings-rule -->`.
- Commit after every task with a conventional-commit message (`feat:`, `fix:`, `test:`, `docs:`), ending with `Co-Authored-By: Claude <noreply@anthropic.com>`.
- Before each commit run the full suite: `cd skills/legwork && python3 -m pytest tests/ -q`. It must be green.

## Review Focus

Inputs the spec implies but does not spell out, most likely to bite first. Each has a test in the task named.

1. **A wording with quotes, `site:` or non-ASCII** (`"per user per month" acme`, `£30 pricing`) must reach `bd_search.py` as one unchanged argv element (Task 5).
2. **Exa returning a citation with no title, a missing `text`, or the same URL twice** must merge cleanly with no crash (Task 6).
3. **A matrix entity cell carrying a citation marker** (`Acme [3]`) must still match a recorded "Acme" (Task 3).
4. **`--tsv` pointing at a run folder whose `.searches` directory does not exist yet** must create it; two calls on the same angle in the same second must not overwrite each other (Task 6).
5. **`--more` on a record with no leads, or past its end,** must print a plain message and exit 0, never a traceback (Task 6).

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `skills/legwork/scripts/bd_search.py` | Drop `yandex`; Bing defaults to `gb`/`en` | 1 |
| `skills/legwork/scripts/fetch.py` | `_jev_request` takes an optional `timeout` | 2 |
| `skills/legwork/scripts/ledger.py` | `full_name`, `site_key`, `site_belongs`, `entity_sites`; `record_round(..., sites=())` | 3 |
| `skills/legwork/scripts/sources.py` | Object entities in `parse_entities`; new `parse_entity_sites`; `log-returns` passes sites | 3 |
| `skills/legwork/scripts/check.py` | `check_rows_on_own_site`; `check_matrix_section(..., tsv_path=None)` | 4 |
| `skills/legwork/tests/fixtures/own_site_missing.*` | Must-fail fixture for the own-site check | 4 |
| `skills/legwork/scripts/search.py` | New: fan-out, providers, deadline (Task 5); merge, rank, record, output, `--more`, CLI (Task 6) | 5, 6 |
| `skills/legwork/SKILL.md` | The marked wording rule, ladder, free-rungs exception, scripts table | 7 |
| `skills/legwork/reference/subagent-brief.md` | "How to search" with `{WORDINGS_RULE}`; `serp`; entity sites | 7 |
| `skills/legwork/scripts/brief.py` | `--wordings`, new defaults, `{WORDINGS_RULE}`, `{TSV}` | 7 |
| `skills/legwork/reference/methodology.md`, `AGENTS.md`, `README.md`, `SECURITY.md`, `skills/legwork/setup.sh`, `.github/workflows/validate.yml` | Docs, setup and CI | 4, 8 |
| `evals/runs/2026-10-1x-wide-search-live-check.md` | Live check record | 9 |

Task order matters: 3 before 4 (check.py uses ledger functions); 2 and 5 before 6 (search.py uses the Jev timeout and its own Task 5 functions); 5 and 6 before 7 (the brief names `search.py`). Tasks 1, 2 and 3 are independent of each other.

---

### Task 1: `bd_search.py` fixes - drop Yandex, give Bing a country

**Files:**
- Modify: `skills/legwork/scripts/bd_search.py` (`run_serp`, about lines 165-190; `main`, the `--engine` argument about line 435)
- Test: `skills/legwork/tests/test_bd_search.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `bd_search.py --engine` accepts only `google` and `bing`. A Bing search with no `--country` sends `--country gb`; with no `--language` sends `--language en`. Google is unchanged.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_bd_search.py`)

```python
# ---------------------------------------------------------------------------
# Engine fixes, 17 Oct 2026: Yandex never returned JSON through the CLI, and
# Bing without a country came back in a Spanish locale.
# ---------------------------------------------------------------------------

def test_yandex_is_refused(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['bd_search.py', 'q', '-m', 'general', '--engine', 'yandex'])
    with pytest.raises(SystemExit) as exc:
        bd_search.main()
    assert exc.value.code == 2  # argparse rejects an invalid choice


def test_bing_with_no_country_gets_gb_and_en(monkeypatch, capsys):
    monkeypatch.delenv('BD_COUNTRY', raising=False)
    monkeypatch.delenv('BD_LANGUAGE', raising=False)
    recorder = _Recorder(SERP_BODY)
    run(monkeypatch, capsys, ['acme pricing', '-m', 'general', '--engine', 'bing'], recorder)
    cmd = recorder.calls[0]
    assert cmd[cmd.index('--country') + 1] == 'gb'
    assert cmd[cmd.index('--language') + 1] == 'en'


def test_bing_keeps_a_country_it_was_given(monkeypatch, capsys):
    recorder = _Recorder(SERP_BODY)
    run(monkeypatch, capsys, ['acme pricing', '-m', 'general', '--engine', 'bing',
                              '--country', 'us', '--language', 'fr'], recorder)
    cmd = recorder.calls[0]
    assert cmd[cmd.index('--country') + 1] == 'us'
    assert cmd[cmd.index('--language') + 1] == 'fr'


def test_google_with_no_country_sends_none(monkeypatch, capsys):
    monkeypatch.delenv('BD_COUNTRY', raising=False)
    monkeypatch.delenv('BD_LANGUAGE', raising=False)
    recorder = _Recorder(SERP_BODY)
    run(monkeypatch, capsys, ['acme pricing', '-m', 'general', '--engine', 'google'], recorder)
    assert '--country' not in recorder.calls[0]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd skills/legwork && python3 -m pytest tests/test_bd_search.py -q -k "yandex or bing or google_with_no_country"`
Expected: `test_yandex_is_refused` and `test_bing_with_no_country_gets_gb_and_en` FAIL; the other two pass already.

- [ ] **Step 3: Implement**

In `main()`, change the engine choices:

```python
    p.add_argument("--engine", default=None, choices=["google", "bing"],
                   help="a second engine is the reason to pay for SERP at all")
```

In `run_serp(args)`, replace the `--language` and `--country` lines with:

```python
    # Bing without a country answered in a Spanish locale on 16 Oct 2026, so a
    # Bing search always says where it is asking from. Google is left alone.
    language = args.language or ("en" if args.engine == "bing" else None)
    country = args.country or ("gb" if args.engine == "bing" else None)
    if language:
        cmd.extend(["--language", language])
    if args.page:
        cmd.extend(["--page", str(args.page)])
    if args.device:
        cmd.extend(["--device", args.device])
    if country:
        cmd.extend(["--country", country])
```

(Delete the old `if args.language:` and `if args.country:` blocks; keep `--page` and `--device` in the order shown.)

Search the file's module docstring and the SKILL.md ladder for `yandex`; there is no other mention to remove in this task (`grep -rn yandex skills/` should print nothing but tests afterwards).

- [ ] **Step 4: Run the tests**

Run: `cd skills/legwork && python3 -m pytest tests/test_bd_search.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/legwork/scripts/bd_search.py skills/legwork/tests/test_bd_search.py
git commit -m "fix(bd_search): drop yandex, which never returned JSON; Bing asks from gb/en by default

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `fetch._jev_request` takes an optional timeout

**Files:**
- Modify: `skills/legwork/scripts/fetch.py` (`_jev_request`, about line 240)
- Test: `skills/legwork/tests/test_fetch.py`

**Interfaces:**
- Produces: `fetch._jev_request(state, questions, key, timeout=60) -> dict`. Existing callers pass three arguments and keep the 60-second default.

- [ ] **Step 1: Write the failing test** (append to `tests/test_fetch.py`)

```python
def test_jev_request_passes_its_timeout_to_urlopen(monkeypatch):
    seen = {}

    class Response:
        def read(self):
            return b'{"answers": {}}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        seen['timeout'] = timeout
        return Response()

    monkeypatch.setattr(fetch, 'urlopen', fake_urlopen)
    fetch._jev_request({}, {}, 'key', timeout=7.5)
    assert seen['timeout'] == 7.5
    fetch._jev_request({}, {}, 'key')
    assert seen['timeout'] == 60
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd skills/legwork && python3 -m pytest tests/test_fetch.py -q -k jev_request_passes`
Expected: FAIL with `TypeError: _jev_request() got an unexpected keyword argument 'timeout'`.

- [ ] **Step 3: Implement**

```python
def _jev_request(state, questions, key, timeout=60):
    body = json.dumps({'state': state, 'model': JEV_MODEL, 'questions': questions}).encode('utf-8')
    request = Request(JEV_API, data=body, headers={'Authorization': 'Bearer ' + key,
                                                   'Content-Type': 'application/json'})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - a fixed https endpoint
        return json.loads(response.read().decode('utf-8'))
```

- [ ] **Step 4: Run the tests**

Run: `cd skills/legwork && python3 -m pytest tests/test_fetch.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/legwork/scripts/fetch.py skills/legwork/tests/test_fetch.py
git commit -m "feat(fetch): _jev_request takes an optional timeout, default unchanged

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Entity sites in `ledger.py` and `sources.py`

**Files:**
- Modify: `skills/legwork/scripts/ledger.py` (new functions after `named_in`; `record_round`)
- Modify: `skills/legwork/scripts/sources.py` (`parse_entities` about line 828; new `parse_entity_sites` after it; `log-returns` loop about lines 930-945)
- Test: `skills/legwork/tests/test_ledger.py`, `skills/legwork/tests/test_sources.py`

**Interfaces:**
- Produces, in `ledger.py`:
  - `full_name(name: str) -> str` - Markdown presentation and citation markers removed, lowercased, whitespace collapsed; words and parentheses kept.
  - `site_key(site: str) -> str` - the host, lowercased, without `www.`; for a host in `independence.PATH_TENANT_HOSTS`, host plus the whole path; `''` when nothing usable (including a path-tenant host with no path).
  - `site_belongs(url: str, key: str) -> bool` - URL's host equals the key's host or is a subdomain of it, and, for a key with a path, the URL's path segments start with the key's.
  - `entity_sites(tsv: str) -> dict[str, set[str]]` - full name to site keys, combined across angles.
  - `record_round(tsv, angle, entities, parties, out_of_scope=(), sites=())` - `sites` is an iterable of `(name, site)` pairs.
- Produces, in `sources.py`:
  - `parse_entities(text) -> list[tuple[str, str]]` - unchanged shape; an entity may now be a string or `{"name": ..., "site": ...}`.
  - `parse_entity_sites(text) -> list[tuple[str, str, str]]` - `(angle, name, site)` for object entities with a non-empty site.

- [ ] **Step 1: Write the failing ledger tests** (append to `tests/test_ledger.py`; add `import json` at the top if it is not already imported)

```python
# ---------------------------------------------------------------------------
# Entity sites: an entity's own site, recorded by the subagent that opened it,
# so the gate can ask whether a matrix row cites it. Keyed by the full name,
# never by distinctive(), which merges "Acme Analytics" and "Acme Hosting".
# ---------------------------------------------------------------------------

import pytest


@pytest.mark.parametrize('raw, expected', [
    ('Acme', 'acme'),
    ('**Acme**', 'acme'),
    ('__Acme__', 'acme'),
    ('*Acme*', 'acme'),
    ('`Acme`', 'acme'),
    ('[Acme](https://acme.example)', 'acme'),
    ('Acme [3]', 'acme'),
    ('Acme [3][4]', 'acme'),
    ('  Acme   Analytics ', 'acme analytics'),
    ('Acme (UK)', 'acme (uk)'),
    ('snake_case_vendor', 'snake_case_vendor'),
])
def test_full_name_strips_presentation_and_keeps_words(raw, expected):
    assert ledger.full_name(raw) == expected


@pytest.mark.parametrize('site, key', [
    ('acme.example', 'acme.example'),
    ('https://www.Acme.example/pricing', 'acme.example'),
    ('docs.acme.example', 'docs.acme.example'),
    ('github.com/Acme', 'github.com/acme'),
    ('https://pypi.org/project/alpha/', 'pypi.org/project/alpha'),
    ('github.com', ''),
    ('', ''),
    ('not a site', ''),
])
def test_site_key(site, key):
    assert ledger.site_key(site) == key


@pytest.mark.parametrize('url, key, belongs', [
    ('https://acme.example/pricing', 'acme.example', True),
    ('https://docs.acme.example/a', 'acme.example', True),
    ('https://www.acme.example/', 'acme.example', True),
    ('https://notacme.example/', 'acme.example', False),
    ('https://hosting.example.com/', 'analytics.example.com', False),
    ('https://github.com/acme/repo', 'github.com/acme', True),
    ('https://github.com/other/repo', 'github.com/acme', False),
    ('https://pypi.org/project/beta/', 'pypi.org/project/alpha', False),
    ('https://pypi.org/project/alpha/1.2/', 'pypi.org/project/alpha', True),
    ('https://www.npmjs.com/package/beta', 'npmjs.com/package/alpha', False),
    ('https://acme.example/', '', False),
])
def test_site_belongs(url, key, belongs):
    assert ledger.site_belongs(url, key) is belongs


def test_record_round_stores_sites_by_full_name(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'q', ['Acme Analytics', 'Acme Hosting'], [],
                        sites=[('Acme Analytics', 'acme-analytics.example'),
                               ('Acme Hosting', 'acme-hosting.example')])
    sites = ledger.entity_sites(tsv)
    assert sites == {'acme analytics': {'acme-analytics.example'}, 'acme hosting': {'acme-hosting.example'}}


def test_a_site_is_stored_once_and_survives_a_later_round(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'q', ['Acme'], [], sites=[('Acme', 'acme.example')])
    ledger.record_round(tsv, 'q', ['Acme'], [], sites=[('Acme', 'https://www.acme.example/x')])
    ledger.record_round(tsv, 'q', ['Acme'], [])
    data = json.load(open(ledger.path(tsv)))
    assert data['q']['sites'] == {'acme': ['acme.example']}


def test_a_site_never_makes_an_entity_new(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'q', ['Acme'], [])
    new, _ = ledger.record_round(tsv, 'q', ['Acme'], [], sites=[('Acme', 'acme.example')])
    assert new == []


def test_sites_combine_across_angles(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'a', ['Acme'], [], sites=[('Acme', 'acme.example')])
    ledger.record_round(tsv, 'b', ['Acme'], [], sites=[('Acme', 'github.com/acme')])
    assert ledger.entity_sites(tsv) == {'acme': {'acme.example', 'github.com/acme'}}


def test_a_ledger_without_sites_still_loads(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    open(ledger.path(tsv), 'w').write(json.dumps(
        {'q': {'rounds': [], 'entities': {'acme': 'Acme'}, 'parties': []}}))
    assert ledger.entity_sites(tsv) == {}
    ledger.record_round(tsv, 'q', ['Acme'], [])  # no sites argument: no 'sites' key written
    assert 'sites' not in json.load(open(ledger.path(tsv)))['q']


def test_a_site_with_no_usable_key_is_not_stored(tmp_path):
    tsv = str(tmp_path / 'run.tsv')
    ledger.record_round(tsv, 'q', ['Acme'], [], sites=[('Acme', 'github.com'), ('Acme', '')])
    assert ledger.entity_sites(tsv) == {}
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd skills/legwork && python3 -m pytest tests/test_ledger.py -q`
Expected: the new tests FAIL with `AttributeError: module 'ledger' has no attribute 'full_name'` (and similar).

- [ ] **Step 3: Implement in `ledger.py`**

Add near the top, with the other imports (keep `from __future__ import annotations` first):

```python
from urllib.parse import urlparse
```

Add after `named_in`:

```python
_MD_LINK = re.compile(r'\[([^\]]*)\]\([^)]*\)')
_CITATION = re.compile(r'\[\d+\]')
_EMPHASIS = re.compile(r'(?<![\w])[*_]+|[*_]+(?![\w])')


def full_name(name):
    """An entity's whole name, as the own-site check compares it: Markdown
    presentation and citation markers removed, lowercased, whitespace collapsed.
    Words and parentheses are kept, so "Acme (UK)" and "Acme (US)" stay apart -
    unlike distinctive(), which would call both of them "acme"."""
    text = _MD_LINK.sub(r'\1', name or '')
    text = _CITATION.sub(' ', text).replace('`', '')
    text = _EMPHASIS.sub('', text)
    return ' '.join(text.lower().split())


def _host_and_path(raw):
    raw = (raw or '').strip()
    if not raw:
        return '', []
    if '://' not in raw:
        raw = 'https://' + raw.lstrip('/')
    parsed = urlparse(raw)
    host = (parsed.hostname or '').lower().strip('.')
    if host.startswith('www.'):
        host = host[4:]
    if '.' not in host:
        return '', []
    return host, [part for part in (parsed.path or '').lower().split('/') if part]


def site_key(site):
    """What an entity's own site is recorded as. Not party_of: party_of reduces
    analytics.example.com and hosting.example.com to one party, which is right
    for counting independent voices and wrong for "is this its own site", and it
    keeps one path segment on code hosts and registries, so every PyPI project
    would be pypi.org/project. On those hosts the whole path is kept."""
    from independence import PATH_TENANT_HOSTS, registrable_domain

    host, path = _host_and_path(site)
    if not host:
        return ''
    if registrable_domain(host) in PATH_TENANT_HOSTS:
        return host + '/' + '/'.join(path) if path else ''
    return host


def site_belongs(url, key):
    """Is the page at `url` on the site recorded as `key`? Its host is the site's
    host or a subdomain of it, and where the key has a path, the page's path
    starts with every segment of it."""
    if not key:
        return False
    site_host, _, site_path = key.partition('/')
    host, path = _host_and_path(url)
    if not host or not (host == site_host or host.endswith('.' + site_host)):
        return False
    want = [part for part in site_path.split('/') if part]
    return path[:len(want)] == want


def entity_sites(tsv):
    """{full name: {site key}} across every angle in the run's ledger."""
    out = {}
    for entry in load(tsv).values():
        for name, keys in (entry.get('sites') or {}).items():
            out.setdefault(name, set()).update(keys)
    return out
```

Change `record_round`'s signature and add the site handling just before `with open(path(tsv), 'w', ...)`:

```python
def record_round(tsv, angle, entities, parties, out_of_scope=(), sites=()):
```

```python
    for name, site in sites or ():
        full, key = full_name(name), site_key(site)
        if full and key:
            known = entry.setdefault('sites', {}).setdefault(full, [])
            if key not in known:
                known.append(key)
```

Update the docstring's first sentence to mention "and the own sites it recorded for them".

- [ ] **Step 4: Run the ledger tests**

Run: `cd skills/legwork && python3 -m pytest tests/test_ledger.py -q`
Expected: all PASS.

- [ ] **Step 5: Write the failing sources tests** (append to `tests/test_sources.py`, after the existing log-returns tests)

```python
def test_object_entities_parse_to_the_same_pairs_as_strings():
    reply = ('{"angle": "q", "entities": ["Contoso", {"name": "Acme", "site": "acme.example"}, '
             '{"name": "Globex"}, {"site": "orphan.example"}, ""]}')
    assert sources.parse_entities(reply) == [('q', 'Contoso'), ('q', 'Acme'), ('q', 'Globex')]


def test_parse_entity_sites_returns_only_object_entities_with_a_site():
    reply = ('{"angle": "q", "entities": ["Contoso", {"name": "Acme", "site": "acme.example"}, '
             '{"name": "Globex", "site": ""}]}')
    assert sources.parse_entity_sites(reply) == [('q', 'Acme', 'acme.example')]


def test_log_returns_records_entity_sites_in_the_ledger(tmp_path, capsys):
    import ledger
    tsv = str(tmp_path / 'run.tsv')
    reply = '\n'.join([
        json.dumps({'url': 'https://acme.example/pricing', 'angle': 'q', 'via': 'direct', 'status': 'ok'}),
        json.dumps({'entities': [{'name': 'Acme', 'site': 'acme.example'}, 'Contoso']}),
        json.dumps({'gaps': ['none']}),
    ])
    sources.main_with_args(['log-returns', '--tsv', tsv, '--returns', _returns(tmp_path, reply), '--angle', 'q'])
    assert ledger.entity_sites(tsv) == {'acme': {'acme.example'}}
    assert sorted(ledger.all_entities(tsv)) == ['Acme', 'Contoso']


def test_log_returns_logs_a_search_py_lead_as_serp(tmp_path, capsys):
    tsv = str(tmp_path / 'run.tsv')
    reply = json.dumps({'url': 'https://c.example/x', 'angle': 'q', 'via': 'serp', 'opened': False,
                        'quote': 'A snippet.'})
    sources.main_with_args(['log-returns', '--tsv', tsv, '--returns', _returns(tmp_path, reply)])
    assert sources.read_rows(tsv)[0]['via'] == 'serp'
```

- [ ] **Step 6: Run them to see them fail**

Run: `cd skills/legwork && python3 -m pytest tests/test_sources.py -q -k "entit or serp"`
Expected: the first three FAIL (`parse_entities` returns a stringified dict; `parse_entity_sites` does not exist). The `serp` test already passes: it pins existing behaviour.

- [ ] **Step 7: Implement in `sources.py`**

Replace the line inside `parse_entities` that builds `found`:

```python
        for item in (value if isinstance(value, list) else [value]):
            if isinstance(item, dict) and isinstance(item.get('entities'), list):
                angle = (item.get('angle') or '').strip()
                for entry in item['entities']:
                    name = entry.get('name') if isinstance(entry, dict) else entry
                    name = str(name or '').strip()
                    if name:
                        found.append((angle, name))
```

Add after `parse_entities`:

```python
def parse_entity_sites(text):
    """(angle or '', name, site) for every entity a reply gave as an object with
    its own site, {"name": "Acme", "site": "acme.example"}. Strings carry no
    site. Kept apart from parse_entities so its callers keep their pairs."""
    decoder = json.JSONDecoder()
    found, at = [], 0
    text = text or ''
    while True:
        start = text.find('{', at)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError:
            at = start + 1
            continue
        at = end
        for item in (value if isinstance(value, list) else [value]):
            if isinstance(item, dict) and isinstance(item.get('entities'), list):
                angle = (item.get('angle') or '').strip()
                for entry in item['entities']:
                    if isinstance(entry, dict):
                        name = str(entry.get('name') or '').strip()
                        site = str(entry.get('site') or '').strip()
                        if name and site:
                            found.append((angle, name, site))
    return found
```

In the `log-returns` loop, after `set_aside = parse_out_of_scope(text)`, add:

```python
    entity_sites = parse_entity_sites(text)
```

and change the `record_round` call inside `for angle in sorted(...)` to:

```python
        sites = [(n, s) for a, n, s in entity_sites if (a or default) == angle]
        new_entities, new_parties = ledger.record_round(args.tsv, angle, names, parties_by_angle.get(angle, ()),
                                                        out_of_scope=aside, sites=sites)
```

- [ ] **Step 8: Run the whole suite**

Run: `cd skills/legwork && python3 -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add skills/legwork/scripts/ledger.py skills/legwork/scripts/sources.py skills/legwork/tests/test_ledger.py skills/legwork/tests/test_sources.py
git commit -m "feat(ledger): subagents can record an entity's own site, keyed by its full name

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: The own-site gate check, its must-fail fixture and CI

**Files:**
- Modify: `skills/legwork/scripts/check.py` (`check_matrix_section` about line 542; `run()` about line 711; new `check_rows_on_own_site` after `check_matrix_section`)
- Create: `skills/legwork/tests/fixtures/own_site_missing.md`, `own_site_missing.tsv`, `own_site_missing.entities.json`
- Test: `skills/legwork/tests/test_check_matrix_index.py`, `skills/legwork/tests/test_check.py`
- Modify: `.github/workflows/validate.yml` (the `expect_fail` list), `AGENTS.md` (the must-fail fixture table and the validating commands)

**Interfaces:**
- Consumes (Task 3): `ledger.full_name`, `ledger.site_belongs`, `ledger.entity_sites`.
- Produces: `check_matrix_section(content, problems, entries=None, rows=None, tsv_path=None)`; `check_rows_on_own_site(parsed, entries, rows, tsv_path, problems)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_check_matrix_index.py`; `import json` at the top if missing)

```python
# ---------------------------------------------------------------------------
# An entity's own site settles it. Graded on 2026-09-27, wide runs got facts
# wrong where an aggregator or review stood in for the entity's own page; this
# check is the rebuild, for main, of that branch's fix (b8a90a4).
# ---------------------------------------------------------------------------

def with_sites(log, sites):
    """Record own sites in the ledger beside `log`, as log-returns would."""
    path = os.path.splitext(log)[0] + '.entities.json'
    data = json.load(open(path, encoding='utf-8'))
    first = next(iter(data.values()))
    first['sites'] = {name: list(keys) for name, keys in sites.items()}
    json.dump(data, open(path, 'w', encoding='utf-8'))


def own_site_errors(problems, entity):
    return [e for e in problems.errors if e.startswith(entity + ':') and 'own site' in e]


def test_a_row_citing_no_page_on_its_own_site_fails(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    with_sites(log, {'acme': ['acme.example']})  # Acme cites acme-software.example and contoso
    problems, _ = check.run(report, log, 'report', 'standard')
    assert own_site_errors(problems, 'Acme'), messages_of(problems)


def test_a_row_citing_an_opened_page_on_a_subdomain_of_its_site_passes(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    with_sites(log, {'contoso': ['contoso.example']})  # Contoso cites learn.contoso.example, opened
    problems, _ = check.run(report, log, 'report', 'standard')
    assert not own_site_errors(problems, 'Contoso'), problems.errors


def test_an_own_site_page_seen_only_in_search_does_not_count(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    contoso_seen_only_in_search(log)
    with_sites(log, {'contoso': ['contoso.example']})
    problems, _ = check.run(report, log, 'report', 'standard')
    assert own_site_errors(problems, 'Contoso'), messages_of(problems)


def test_a_row_of_unknowns_is_not_checked(tmp_path):
    matrix = COMPLETE_MATRIX.replace('| Acme | 30 USD/seat [1] | No [2] |', '| Acme | [unknown] | [unknown] |')
    report, log = report_with(tmp_path, matrix)
    with_sites(log, {'acme': ['acme.example']})
    problems, _ = check.run(report, log, 'report', 'standard')
    assert not own_site_errors(problems, 'Acme'), problems.errors


def test_a_partly_unknown_row_is_still_checked(tmp_path):
    matrix = COMPLETE_MATRIX.replace('| Acme | 30 USD/seat [1] | No [2] |', '| Acme | 30 USD/seat [1] | [unknown] |')
    report, log = report_with(tmp_path, matrix)
    with_sites(log, {'acme': ['acme.example']})
    problems, _ = check.run(report, log, 'report', 'standard')
    assert own_site_errors(problems, 'Acme'), messages_of(problems)


def test_another_entitys_site_does_not_satisfy_the_row(tmp_path):
    matrix = COMPLETE_MATRIX.replace('| Acme |', '| Acme Analytics |')
    report, log = report_with(tmp_path, matrix)
    # Acme Analytics' own site is analytics.example.com; its row cites only Acme Software and Contoso
    with_sites(log, {'acme analytics': ['analytics.example.com'], 'acme': ['acme-software.example']})
    problems, _ = check.run(report, log, 'report', 'standard')
    assert own_site_errors(problems, 'Acme Analytics'), messages_of(problems)


def test_a_formatted_entity_cell_is_still_matched(tmp_path):
    for label in ('**Acme**', '[Acme](https://acme.example)', 'Acme [1]'):
        matrix = COMPLETE_MATRIX.replace('| Acme |', '| {} |'.format(label))
        report, log = report_with(tmp_path, matrix, name='r{}.md'.format(len(label)))
        with_sites(log, {'acme': ['acme.example']})
        problems, _ = check.run(report, log, 'report', 'standard')
        assert [e for e in problems.errors if 'own site' in e], (label, messages_of(problems))


def test_an_entity_with_no_recorded_site_is_not_checked(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    problems, _ = check.run(report, log, 'report', 'standard')
    assert not [e for e in problems.errors if 'own site' in e], problems.errors


def test_quick_does_not_run_the_own_site_check(tmp_path):
    report, log = report_with(tmp_path, COMPLETE_MATRIX)
    with_sites(log, {'acme': ['acme.example']})
    problems, _ = check.run(report, log, 'report', 'quick')
    assert not [e for e in problems.errors if 'own site' in e], problems.errors


def test_the_own_site_check_changes_nothing_without_a_tsv_path():
    import matrix
    parsed = matrix.parse_matrix(COMPLETE_MATRIX)
    problems = check.Problems('standard')
    check.check_rows_on_own_site(parsed, {}, [], None, problems)
    assert problems.errors == []
```

Append to `tests/test_check.py`:

```python
def test_the_own_site_fixture_fails_for_that_reason_only():
    """A MUST-fail fixture is evidence about one check only if it fails for one reason."""
    problems, _ = run('own_site_missing.md', level='deep')
    assert len(problems.errors) == 1, problems.errors
    assert 'own site' in problems.errors[0]
```

(`run` in `test_check.py` is the existing helper that gates a fixture with its own `.tsv`; read its definition near the top of the file and use it as the other fixture tests do.)

- [ ] **Step 2: Run them to see them fail**

Run: `cd skills/legwork && python3 -m pytest tests/test_check_matrix_index.py -q -k "own_site or unknown or formatted or another_entitys or recorded_site or quick_does_not"`
Expected: the failing-row tests FAIL (no own-site error is raised yet); `check_rows_on_own_site` does not exist.

- [ ] **Step 3: Implement in `check.py`**

Change the signature:

```python
def check_matrix_section(content, problems, entries=None, rows=None, tsv_path=None):
```

At the end of the standard and deep block, after the existing `for row in parsed['rows']:` loop that raises "every citation in this row is a search result...", add:

```python
    check_rows_on_own_site(parsed, entries, rows, tsv_path, problems)
```

Add after `check_matrix_section`:

```python
def check_rows_on_own_site(parsed, entries, rows, tsv_path, problems):
    """A matrix row about an entity cites a page opened on that entity's own site.

    Graded against answer keys on 2026-09-27, wide runs covered more of the right
    entities than main and got more of them wrong: a pre-built supplier sold as
    flat-pack, a bank's sandbox as open when its own page limits it, a free tier
    out of date. Each came from an aggregator or a review. Those find entities;
    only an entity's own page settles what it offers and what it costs. Rebuilt
    from b8a90a4 for main: the sites come from what subagents recorded in the
    run's ledger, not from plan files.
    """
    if not tsv_path:
        return
    sites = ledger.entity_sites(tsv_path)
    if not sites or not parsed:
        return
    opened = opened_urls(rows or [])
    for row in parsed['rows']:
        keys = sites.get(ledger.full_name(row['entity']))
        if not keys:
            continue
        values = [value.strip().lower() for value in row['cells'].values()]
        if values and all(value == '[unknown]' for value in values):
            continue
        cited = sorted({int(n) for n in re.findall(r'\[(\d+)\]', ' '.join(row['cells'].values()))})
        urls = [entries[n]['url'] for n in cited if n in (entries or {}) and entries[n]['url']]
        if not urls:
            continue
        if any(canonicalize(url) in opened and any(ledger.site_belongs(url, key) for key in keys) for url in urls):
            continue
        problems.structural(
            '{}: no citation in this row is a page you opened on its own site ({}) - an aggregator or a '
            'review found it, but only its own page settles what it offers and costs. Cite a page you '
            'opened on its own site, or mark the cells [unknown]'.format(row['entity'], ', '.join(sorted(keys))))
```

In `run()`, change the call:

```python
    check_matrix_section(content, problems, entries, rows, tsv_path=tsv_path)
```

- [ ] **Step 4: Run the matrix tests**

Run: `cd skills/legwork && python3 -m pytest tests/test_check_matrix_index.py -q`
Expected: all PASS.

- [ ] **Step 5: Create the must-fail fixture**

```bash
cd skills/legwork/tests/fixtures
cp valid_report.tsv own_site_missing.tsv
python3 - <<'EOF'
import json
report = open('valid_report.md', encoding='utf-8').read()
matrix = """## Comparison matrix

| Vendor | Price | Native triage |
|---|---|---|
| Acme | 30 USD/seat [1] | No [2] |
| Contoso | [unknown] | Yes [2] |

"""
open('own_site_missing.md', 'w', encoding='utf-8').write(report.replace('## Findings', matrix + '## Findings', 1))
ledger = json.load(open('valid_report.entities.json', encoding='utf-8'))
next(iter(ledger.values()))['sites'] = {'acme': ['acme.example']}
json.dump(ledger, open('own_site_missing.entities.json', 'w', encoding='utf-8'), indent=1)
EOF
```

The story the fixture tells: the subagent recorded Acme's own site as `acme.example`, and the report's Acme row cites only a reseller (`acme-software.example`) and Contoso.

- [ ] **Step 6: Run the fixture test and prove it fails the gate from the command line**

Run: `cd skills/legwork && python3 -m pytest tests/test_check.py -q -k own_site && python3 scripts/check.py --report tests/fixtures/own_site_missing.md --level deep; echo "exit $?"`
Expected: the test PASSES; `check.py` prints one error naming Acme's own site and exits non-zero.

- [ ] **Step 7: Register the fixture in CI and AGENTS.md**

In `.github/workflows/validate.yml`, add after the `snippet_only.md` line in the `expect_fail` list:

```yaml
          expect_fail tests/fixtures/own_site_missing.md   "a matrix row citing no opened page on its entity's own site"
```

In `AGENTS.md`, add to the "Validating a change" command block, after the `concentrated.md` line:

```bash
python3 scripts/check.py --report tests/fixtures/own_site_missing.md --level deep    # MUST fail
```

and add a row to the must-fail fixture table:

```markdown
| `own_site_missing.md` | a matrix row about an entity that cites no page opened on its own site |
```

- [ ] **Step 8: Run the whole suite**

Run: `cd skills/legwork && python3 -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add skills/legwork/scripts/check.py skills/legwork/tests/ .github/workflows/validate.yml AGENTS.md
git commit -m "feat(check): a matrix row about an entity must cite a page opened on its own site

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: `search.py` part 1 - providers, failures and the deadline

**Files:**
- Create: `skills/legwork/scripts/search.py`
- Create: `skills/legwork/tests/test_search.py`

**Interfaces:**
- Consumes (Task 2): `fetch._jev_request(..., timeout=)` (used in Task 6).
- Produces, all module-level in `search.py`:
  - Constants: `BD_SEARCH`, `EXA_API`, `EXA_KEY_FILE`, `USER_AGENT`, `ZERO_RESULTS = 'SERP returned zero organic results'`, `EXIT_NO_PROVIDER = 4`, `MAX_WORKERS = 10`, `GOOGLE_TIMEOUT = 60`, `EXA_TIMEOUT = 30`, `RESERVE = 3.0`, `RETRY_MIN = 15.0`, `JEV_MIN = 20.0`, `JEV_MARGIN = 5.0`, `SNIPPET_KEEP = 600`, `_GROUPS` (bool).
  - `exa_key() -> str`
  - `bright_data_installed() -> bool`
  - `class Clock(limit)` with `.elapsed()` and `.remaining()` (seconds before the network phase must stop: `limit - RESERVE - elapsed`, reading `RESERVE` at call time).
  - `provider_result(provider, query, wording=None, status='ok', reason='', seconds=0.0, results=None, **extra) -> dict` with keys `provider, wording, query, ok, status, reason, seconds, results` plus extras (`answer`, `cost` for Exa).
  - `run_process(cmd, timeout) -> (returncode | None, stdout, stderr, timed_out)`; `kill_all()`.
  - `search_bd(engine, wording, number, opts, clock) -> dict` (`opts` has `country`, `language`).
  - `search_exa(angle, key, clock) -> dict` (extras `answer: str`, `cost: float | None`).
  - `run_jobs(jobs, clock, workers=MAX_WORKERS) -> list[dict]`, where each job is `(label, fn, placeholder)` and results come back in job order.
  - A result row is `{'url', 'title', 'snippet', 'rank', 'date'}`.

- [ ] **Step 1: Write the failing tests** (`tests/test_search.py`)

```python
"""search.py: one angle asked many ways across Bright Data and Exa.

Hermetic. subprocess.Popen, os.killpg and urlopen are replaced, so no CLI runs,
no request is billed and no socket opens. What these pin is the mapping from
wordings to calls, the failure table in the spec (section D) and the deadline
contract: no provider can hold the command open past its limit.
"""

import json
import subprocess
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

import search


def serp(wording, n=3):
    """Three distinct results per wording, the same every run."""
    slug = '-'.join(''.join(c if c.isalnum() else ' ' for c in wording.lower()).split()) or 'w'
    return json.dumps({'results': [
        {'rank': i + 1, 'title': '{} result {}'.format(wording, i + 1),
         'url': 'https://site{}.example/{}'.format(i + 1, slug),
         'snippet': 'About {}'.format(wording), 'date': ''} for i in range(n)]})


class FakePopen:
    """Stands in for subprocess.Popen. FakePopen.script maps a wording to
    (returncode, stdout, stderr) or to 'hang', which blocks until the process
    is killed. Unscripted wordings return three results."""
    script = {}
    instances = []

    def __init__(self, cmd, **kwargs):
        self.cmd, self.kwargs = cmd, kwargs
        self.pid = 4000 + len(FakePopen.instances)
        self.killed = threading.Event()
        self.returncode = None
        FakePopen.instances.append(self)
        self.outcome = FakePopen.script.get(cmd[2], (0, serp(cmd[2]), ''))

    def communicate(self, timeout=None):
        if self.outcome == 'hang':
            if not self.killed.wait(timeout):
                raise subprocess.TimeoutExpired(self.cmd, timeout)
            self.returncode = -9
            return '', ''
        self.returncode, out, err = self.outcome
        return out, err

    def kill(self):
        self.killed.set()


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode('utf-8')

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


EXA_PAYLOAD = {'requestId': 'r1', 'answer': 'Acme charges 30 dollars.',
               'costDollars': {'total': 0.005},
               'citations': [{'url': 'https://acme.example/pricing', 'title': 'Acme pricing',
                              'text': 'Team   plan:\n30 USD', 'publishedDate': '2026-07-01T00:00:00Z'}]}


@pytest.fixture
def env(monkeypatch, tmp_path):
    FakePopen.script, FakePopen.instances = {}, []
    killed, exa_calls = [], []
    release = threading.Event()

    def fake_killpg(pid, sig):
        killed.append(pid)
        for proc in FakePopen.instances:
            if proc.pid == pid:
                proc.killed.set()

    def no_network(*args, **kwargs):
        raise AssertionError('unexpected network call')

    monkeypatch.setattr(search.subprocess, 'Popen', FakePopen)
    monkeypatch.setattr(search.os, 'killpg', fake_killpg, raising=False)
    monkeypatch.setattr(search, '_GROUPS', True)
    monkeypatch.setattr(search.shutil, 'which', lambda name: '/usr/bin/brightdata')
    monkeypatch.setattr(search, 'exa_key', lambda: '')
    monkeypatch.setattr(search, 'urlopen', no_network)
    monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: '')
    yield SimpleNamespace(tmp=tmp_path, killed=killed, exa_calls=exa_calls, release=release, monkeypatch=monkeypatch)
    release.set()  # free any thread a test left blocked


def clock(limit=150):
    return search.Clock(limit)


# --- fan-out mapping -------------------------------------------------------

def test_a_wording_becomes_one_bd_search_call_with_engine_country_and_language(env):
    result = search.search_bd('google', 'acme pricing', 1, {'country': 'gb', 'language': 'en'}, clock())
    cmd = FakePopen.instances[0].cmd
    assert cmd[1] == search.BD_SEARCH and cmd[2] == 'acme pricing'
    for flag, value in (('-m', 'general'), ('--engine', 'google'), ('-c', '10'),
                        ('--country', 'gb'), ('--language', 'en')):
        assert cmd[cmd.index(flag) + 1] == value
    assert result['ok'] and result['provider'] == 'google' and result['wording'] == 1
    assert [r['rank'] for r in result['results']] == [1, 2, 3]


def test_a_wording_with_quotes_and_symbols_reaches_bd_search_as_one_argument(env):
    wording = '"per user per month" site:acme.example £30'
    search.search_bd('google', wording, 1, {}, clock())
    assert FakePopen.instances[0].cmd[2] == wording


def test_the_subprocess_starts_its_own_process_group(env):
    search.search_bd('google', 'q', 1, {}, clock())
    assert FakePopen.instances[0].kwargs.get('start_new_session') is True


def test_exa_is_asked_once_with_the_key_a_user_agent_and_text(env):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen['url'], seen['timeout'] = request.full_url, timeout
        seen['headers'] = {k.lower(): v for k, v in request.header_items()}
        seen['body'] = json.loads(request.data.decode('utf-8'))
        return FakeResponse(EXA_PAYLOAD)

    env.monkeypatch.setattr(search, 'urlopen', fake_urlopen)
    result = search.search_exa('what does acme charge', 'k123', clock())
    assert seen['url'] == search.EXA_API
    assert seen['headers']['x-api-key'] == 'k123' and seen['headers']['user-agent'] == search.USER_AGENT
    assert seen['body'] == {'query': 'what does acme charge', 'text': True}
    assert seen['timeout'] <= search.EXA_TIMEOUT
    assert result['ok'] and result['answer'] == 'Acme charges 30 dollars.' and result['cost'] == 0.005
    row = result['results'][0]
    assert row == {'url': 'https://acme.example/pricing', 'title': 'Acme pricing',
                   'snippet': 'Team plan: 30 USD', 'rank': 1, 'date': '2026-07-01'}


def test_the_exa_key_comes_from_the_environment_then_the_file(monkeypatch, tmp_path):
    monkeypatch.setenv('EXA_API_KEY', ' env-key ')
    assert search.exa_key() == 'env-key'
    monkeypatch.delenv('EXA_API_KEY')
    monkeypatch.setattr(search, 'EXA_KEY_FILE', str(tmp_path / 'exa-api-key'))
    assert search.exa_key() == ''
    (tmp_path / 'exa-api-key').write_text('file-key\n')
    assert search.exa_key() == 'file-key'


# --- the failure table -----------------------------------------------------

def test_exit_2_from_bd_search_is_a_refusal_and_is_not_retried(env):
    FakePopen.script['q'] = (2, '', json.dumps({'provider': 'brightdata', 'error': 'quota exceeded'}))
    result = search.search_bd('google', 'q', 1, {}, clock())
    assert result['status'] == 'refused' and 'quota exceeded' in result['reason']
    assert len(FakePopen.instances) == 1


def test_another_failure_is_retried_once_then_recorded(env):
    FakePopen.script['q'] = (1, '', json.dumps({'provider': 'brightdata', 'error': 'boom'}))
    result = search.search_bd('google', 'q', 1, {}, clock())
    assert result['status'] == 'failed' and 'boom' in result['reason']
    assert len(FakePopen.instances) == 2


def test_stdout_that_is_not_json_is_a_failure(env):
    FakePopen.script['q'] = (0, 'not json', '')
    assert search.search_bd('google', 'q', 1, {}, clock())['status'] == 'failed'


def test_bd_searchs_zero_results_message_is_a_success_with_no_results(env):
    FakePopen.script['q'] = (1, '', json.dumps({'provider': 'brightdata', 'error': search.ZERO_RESULTS}))
    result = search.search_bd('google', 'q', 1, {}, clock())
    assert result['ok'] and result['results'] == [] and len(FakePopen.instances) == 1


def test_a_retry_waits_for_enough_time(env):
    env.monkeypatch.setattr(search, 'RETRY_MIN', 10_000)
    FakePopen.script['q'] = (1, '', '{"error": "boom"}')
    search.search_bd('google', 'q', 1, {}, clock())
    assert len(FakePopen.instances) == 1


def test_exa_http_error_is_recorded_with_its_status_and_body(env):
    def refuse(request, timeout=None):
        raise HTTPError(search.EXA_API, 402, 'Payment Required', {}, _Body(b'{"error": "out of credits"}'))

    env.monkeypatch.setattr(search, 'urlopen', refuse)
    result = search.search_exa('q', 'k', clock())
    assert result['status'] == 'failed' and result['reason'].startswith('HTTP 402') and 'out of credits' in result['reason']


class _Body:
    def __init__(self, data):
        self.data = data

    def read(self, *args):
        return self.data

    def close(self):
        pass


def test_exa_with_no_citations_is_a_success_with_no_results(env):
    env.monkeypatch.setattr(search, 'urlopen', lambda r, timeout=None: FakeResponse({'answer': 'x', 'citations': []}))
    result = search.search_exa('q', 'k', clock())
    assert result['ok'] and result['results'] == []


def test_exa_returning_something_that_is_not_an_object_is_a_failure(env):
    env.monkeypatch.setattr(search, 'urlopen', lambda r, timeout=None: FakeResponse(['a list']))
    assert search.search_exa('q', 'k', clock())['status'] == 'failed'


# --- the deadline contract -------------------------------------------------

def test_a_bd_search_that_never_returns_is_killed_with_its_group(env):
    env.monkeypatch.setattr(search, 'RESERVE', 0.2)
    FakePopen.script['q'] = 'hang'
    jobs = [('g1', lambda: search.search_bd('google', 'q', 1, {}, c), search.provider_result('google', 'q', 1, 'deadline'))]
    c = search.Clock(1.0)
    started = time.monotonic()
    results = search.run_jobs(jobs, c)
    assert time.monotonic() - started < 1.5
    assert results[0]['status'] in ('timeout', 'deadline')
    assert FakePopen.instances[0].pid in env.killed


def test_an_exa_call_that_never_returns_cannot_hold_the_call_open(env):
    env.monkeypatch.setattr(search, 'RESERVE', 0.2)

    def hang(request, timeout=None):
        env.release.wait()
        return FakeResponse(EXA_PAYLOAD)

    env.monkeypatch.setattr(search, 'urlopen', hang)
    c = search.Clock(1.0)
    jobs = [('exa', lambda: search.search_exa('q', 'k', c), search.provider_result('exa', 'q', status='deadline'))]
    started = time.monotonic()
    results = search.run_jobs(jobs, c)
    assert time.monotonic() - started < 1.5
    assert results[0]['status'] == 'deadline'


def test_run_jobs_returns_results_in_job_order_and_turns_exceptions_into_failures(env):
    def boom():
        raise RuntimeError('worker blew up')

    jobs = [('a', lambda: search.provider_result('google', 'a', 1), {}),
            ('b', boom, search.provider_result('google', 'b', 2, 'deadline')),
            ('c', lambda: search.provider_result('google', 'c', 3), {})]
    results = search.run_jobs(jobs, clock())
    assert [r['query'] for r in results] == ['a', 'b', 'c']
    assert results[1]['status'] == 'failed' and 'worker blew up' in results[1]['reason']


def test_where_killpg_does_not_exist_the_process_alone_is_killed(env):
    env.monkeypatch.setattr(search, '_GROUPS', False)
    env.monkeypatch.setattr(search, 'RESERVE', 0.2)
    FakePopen.script['q'] = 'hang'
    search.search_bd('google', 'q', 1, {}, search.Clock(1.0))
    proc = FakePopen.instances[0]
    assert 'start_new_session' not in proc.kwargs and proc.killed.is_set()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd skills/legwork && python3 -m pytest tests/test_search.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'search'`.

- [ ] **Step 3: Implement part 1 of `search.py`**

Create `skills/legwork/scripts/search.py` with exactly this content (Task 6 appends to it):

```python
#!/usr/bin/env python3
"""
search.py - ask one angle many ways, across Google and Exa, in one call.

    search.py --angle "what does the incumbent charge" \\
      --wording "..." --wording "..." [--wording ...]    # 1 to 12; 6 to 10 expected
      [--tsv RUN.tsv | --out-dir DIR] [--country gb] [--language en]
      [--engine google|bing|both] [--no-exa] [--show 40] [--time-limit 150]
    search.py --more RECORD.json [--from 41] [--show 40]

Every wording goes to Bright Data (through bd_search.py) in parallel, and the
angle goes to Exa Answer once. Results are merged by canonical URL, ranked by
reciprocal rank fusion (averaged with Jev's relevance score when a key is set),
and printed as compact leads. Nothing is filtered: every lead is in the search
record, and --more prints the next slice of it.

Leads are search results, not opened pages. Nothing here writes to the run's
.tsv: a subagent returns a lead it relied on with "via": "serp", and opens a
page with fetch.py before quoting it.

Every provider is optional. A missing key, an exhausted credit or a refusal
skips that provider and says so. Exit 4 means no provider answered at all, and
the caller searches with WebSearch instead.

Exit codes: 0 when at least one provider call succeeded, even with no results;
4 when none did; 2 on bad arguments.

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fetch  # noqa: E402
from independence import canonicalize  # noqa: E402

BD_SEARCH = os.path.join(HERE, 'bd_search.py')
EXA_API = 'https://api.exa.ai/answer'
EXA_KEY_FILE = os.path.join('~', '.dbhq', 'legwork', 'exa-api-key')
# Cloudflare in front of Exa refused Python's default User-Agent with 403 on
# 16 Oct 2026, so every request names itself.
USER_AGENT = 'legwork-search/1.0 (+https://github.com/dbhq-uk/legwork-skill)'
# bd_search.py reports an empty SERP as an error with exit 1. Subagents calling
# it directly rely on that to fall down the ladder, so it stays; here it is a
# success with no results.
ZERO_RESULTS = 'SERP returned zero organic results'
EXIT_NO_PROVIDER = 4

MAX_WORKERS = 10
GOOGLE_TIMEOUT = 60   # Bright Data Google: a median of 13-17s, up to 90 (16 Oct 2026)
EXA_TIMEOUT = 30
RESERVE = 3.0         # seconds kept back at the end for ranking, writing and printing
RETRY_MIN = 15.0      # a retry starts only with at least this much time left
JEV_MIN = 20.0        # Jev runs only with at least this much time left
JEV_MARGIN = 5.0
SNIPPET_KEEP = 600

# Killing a process group takes the Bright Data CLI that bd_search.py starts
# with it. Where there are no process groups (Windows), the process alone is
# killed and its child may outlive it.
_GROUPS = hasattr(os, 'killpg')
_PROCS = set()
_PROCS_LOCK = threading.Lock()


def exa_key():
    """EXA_API_KEY from the environment, else ~/.dbhq/legwork/exa-api-key."""
    key = os.environ.get('EXA_API_KEY', '').strip()
    if key:
        return key
    try:
        with open(os.path.expanduser(EXA_KEY_FILE), encoding='utf-8') as handle:
            return handle.read().strip()
    except OSError:
        return ''


def bright_data_installed():
    return bool(shutil.which('brightdata') or shutil.which('bdata'))


class Clock:
    """Seconds left before the network phase must stop: the limit minus RESERVE."""

    def __init__(self, limit):
        self.start = time.monotonic()
        self.limit = float(limit)

    def elapsed(self):
        return time.monotonic() - self.start

    def remaining(self):
        return self.limit - RESERVE - self.elapsed()


def provider_result(provider, query, wording=None, status='ok', reason='', seconds=0.0, results=None, **extra):
    out = {'provider': provider, 'wording': wording, 'query': query, 'ok': status == 'ok',
           'status': status, 'reason': reason, 'seconds': round(float(seconds), 1), 'results': results or []}
    out.update(extra)
    return out


def _kill(proc):
    try:
        if _GROUPS:
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        pass


def kill_all():
    """Kill every bd_search.py still running, with its process group."""
    with _PROCS_LOCK:
        procs = list(_PROCS)
    for proc in procs:
        _kill(proc)


def run_process(cmd, timeout):
    """(returncode or None, stdout, stderr, timed_out). On timeout the process
    is killed with its whole group."""
    kwargs = {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'text': True}
    if _GROUPS:
        kwargs['start_new_session'] = True
    proc = subprocess.Popen(cmd, **kwargs)
    with _PROCS_LOCK:
        _PROCS.add(proc)
    try:
        out, err = proc.communicate(timeout=max(0.1, timeout))
        return proc.returncode, out or '', err or '', False
    except subprocess.TimeoutExpired:
        _kill(proc)
        try:
            out, err = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            out, err = '', ''
        return None, out or '', err or '', True
    finally:
        with _PROCS_LOCK:
            _PROCS.discard(proc)


def _reason(stderr):
    text = (stderr or '').strip()
    try:
        text = json.loads(text.splitlines()[-1]).get('error') or text
    except (ValueError, IndexError, AttributeError):
        pass
    return ' '.join(str(text).split())[:120]


def search_bd(engine, wording, number, opts, clock):
    """One wording on one Bright Data engine. A failure is retried once, if the
    deadline allows; a refusal (exit 2, auth or quota) is not."""
    cmd = [sys.executable, BD_SEARCH, wording, '-m', 'general', '--engine', engine, '-c', '10']
    if opts.get('country'):
        cmd += ['--country', opts['country']]
    if opts.get('language'):
        cmd += ['--language', opts['language']]
    started = time.monotonic()
    attempt = 0
    while True:
        attempt += 1
        left = clock.remaining()
        if left <= 0:
            return provider_result(engine, wording, number, 'deadline', 'no time left', time.monotonic() - started)
        wait = min(GOOGLE_TIMEOUT, left)
        code, out, err, timed_out = run_process(cmd, wait)
        if timed_out:
            status, reason = 'timeout', 'no answer in {:.0f}s'.format(wait)
        elif code == 0:
            try:
                rows = json.loads(out).get('results') or []
            except (ValueError, AttributeError):
                status, reason = 'failed', 'stdout was not JSON'
            else:
                results = [{'url': row['url'], 'title': row.get('title') or '', 'snippet': row.get('snippet') or '',
                            'rank': int(row.get('rank') or index + 1), 'date': row.get('date') or ''}
                           for index, row in enumerate(rows) if isinstance(row, dict) and row.get('url')]
                return provider_result(engine, wording, number, 'ok', '' if results else 'zero results',
                                       time.monotonic() - started, results)
        elif ZERO_RESULTS in (err or ''):
            return provider_result(engine, wording, number, 'ok', 'zero results', time.monotonic() - started, [])
        elif code == 2:
            return provider_result(engine, wording, number, 'refused', _reason(err), time.monotonic() - started)
        else:
            status, reason = 'failed', _reason(err) or 'exit {}'.format(code)
        if attempt >= 2 or clock.remaining() < RETRY_MIN:
            return provider_result(engine, wording, number, status, reason, time.monotonic() - started)


def search_exa(angle, key, clock):
    """The angle to Exa Answer once. Its citations become results in the order
    Exa gave them; its written answer is kept apart, unverified."""
    started = time.monotonic()
    left = clock.remaining()
    if left <= 0:
        return provider_result('exa', angle, status='deadline', reason='no time left')
    request = Request(EXA_API, data=json.dumps({'query': angle, 'text': True}).encode('utf-8'),
                      headers={'x-api-key': key, 'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
    try:
        with urlopen(request, timeout=max(1.0, min(EXA_TIMEOUT, left))) as response:  # noqa: S310 - fixed endpoint
            payload = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', 'replace')
        except Exception:  # noqa: BLE001 - the status code is enough without a body
            body = ''
        return provider_result('exa', angle, status='failed', seconds=time.monotonic() - started,
                               reason='HTTP {}: {}'.format(exc.code, ' '.join(body.split())[:120]).strip())
    except Exception as exc:  # noqa: BLE001 - any failure skips Exa, never the call
        return provider_result('exa', angle, status='failed', seconds=time.monotonic() - started,
                               reason=' '.join(str(exc).split())[:120] or type(exc).__name__)
    if not isinstance(payload, dict):
        return provider_result('exa', angle, status='failed', seconds=time.monotonic() - started,
                               reason='response was not a JSON object')
    results = []
    for index, cite in enumerate(payload.get('citations') or []):
        if isinstance(cite, dict) and cite.get('url'):
            results.append({'url': cite['url'], 'title': cite.get('title') or '',
                            'snippet': ' '.join(str(cite.get('text') or '').split())[:SNIPPET_KEEP],
                            'rank': index + 1, 'date': str(cite.get('publishedDate') or '')[:10]})
    cost = payload.get('costDollars')
    cost = cost.get('total') if isinstance(cost, dict) else None
    return provider_result('exa', angle, status='ok', reason='' if results else 'zero results',
                           seconds=time.monotonic() - started, results=results,
                           answer=str(payload.get('answer') or ''), cost=cost)


def run_jobs(jobs, clock, workers=MAX_WORKERS):
    """Run (label, fn, placeholder) jobs on daemon threads and return their
    results in job order. Python cannot kill a thread, so the main thread never
    joins one: it waits on a queue until the clock runs out, then kills every
    subprocess still running and returns each unfinished job's placeholder,
    marked 'deadline'. A worker that raises becomes a failed result."""
    tasks, done = queue.Queue(), queue.Queue()
    for index, job in enumerate(jobs):
        tasks.put((index, job))

    def worker():
        while True:
            try:
                index, (_label, fn, placeholder) = tasks.get_nowait()
            except queue.Empty:
                return
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - one job never stops the others
                result = dict(placeholder or {}, ok=False, status='failed',
                              reason=' '.join(str(exc).split())[:120] or type(exc).__name__)
            done.put((index, result))

    for _ in range(min(workers, len(jobs))):
        threading.Thread(target=worker, daemon=True).start()
    results = {}
    while len(results) < len(jobs):
        left = clock.remaining()
        if left <= 0:
            break
        try:
            index, result = done.get(timeout=min(left, 0.25))
        except queue.Empty:
            continue
        results[index] = result
    if len(results) < len(jobs):
        kill_all()
        while True:  # queued work never starts
            try:
                tasks.get_nowait()
            except queue.Empty:
                break
    return [results.get(index) or dict(jobs[index][2] or {}, ok=False, status='deadline',
                                       reason='not finished by the time limit')
            for index in range(len(jobs))]
```

- [ ] **Step 4: Run the tests**

Run: `cd skills/legwork && python3 -m pytest tests/test_search.py -q`
Expected: all PASS, in a few seconds.

- [ ] **Step 5: Lint the way CI does, then commit**

Run: `cd skills/legwork && python3 -m ruff check --select E9,F scripts/search.py tests/test_search.py 2>/dev/null || python3 -m pyflakes scripts/search.py 2>/dev/null; python3 -m pytest tests/ -q`
Expected: no lint errors reported (if neither linter is installed, skip the lint and rely on CI); full suite PASS.

```bash
git add skills/legwork/scripts/search.py skills/legwork/tests/test_search.py
git commit -m "feat(search): fan an angle's wordings out to Bright Data and Exa, every provider optional, with a hard deadline

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: `search.py` part 2 - merge, rank, record, output, `--more` and the CLI

**Files:**
- Modify: `skills/legwork/scripts/search.py` (append)
- Test: `skills/legwork/tests/test_search.py` (append)

**Interfaces:**
- Consumes (Task 5): everything in its Produces list. (Task 2): `fetch._jev_request(state, questions, key, timeout=)`, plus existing `fetch.typesafe_key`, `fetch.JEV_LEVELS`, `fetch.JEV_BATCH`, `fetch._expected_score`.
- Produces:
  - `list_label(result) -> str` (`g3`, `b3`, `exa`)
  - `merge(results) -> list[dict]`, a lead being `{'url', 'title', 'snippet', 'date', 'ranks': {label: rank}}`
  - `rrf(lead) -> float` (`RRF_K = 60`)
  - `jev_scores(angle, leads, clock) -> (list[float] | None, status: str)`, status one of `on`, `off`, `skipped (time)`, `failed (...)`
  - `rank(leads, jev=None) -> list[dict]`, adding `rrf`, `jev`, `score`
  - `record_path(angle, tsv=None, out_dir=None, now=None) -> str`
  - `lead_lines(leads, start, show) -> list[str]`
  - `main(argv=None) -> int`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_search.py`)

```python
# --- merge and rank --------------------------------------------------------

def ok(provider, wording, rows):
    return search.provider_result(provider, 'q', wording, 'ok', results=[
        {'url': url, 'title': title, 'snippet': snippet, 'rank': rank, 'date': ''}
        for rank, (url, title, snippet) in enumerate(rows, 1)])


def test_two_urls_that_canonicalise_alike_merge_and_keep_every_list():
    leads = search.merge([
        ok('google', 1, [('https://www.acme.example/pricing/', 'Acme', 'short')]),
        ok('google', 2, [('https://acme.example/pricing', '', 'a much longer snippet')]),
        ok('exa', None, [('https://acme.example/pricing?utm_source=x', 'Acme pricing', '')]),
    ])
    assert len(leads) == 1
    lead = leads[0]
    assert set(lead['ranks']) == {'g1', 'g2', 'exa'}
    assert lead['snippet'] == 'a much longer snippet' and lead['title'] == 'Acme'


def test_failed_results_contribute_nothing():
    failed = search.provider_result('google', 'q', 1, 'failed', results=[
        {'url': 'https://x.example', 'title': '', 'snippet': '', 'rank': 1, 'date': ''}])
    assert search.merge([failed]) == []


def test_exa_citations_with_no_title_or_text_and_repeats_merge_cleanly():
    leads = search.merge([ok('exa', None, [('https://a.example/1', '', ''), ('https://a.example/1', '', 'x')])])
    assert len(leads) == 1 and leads[0]['ranks'] == {'exa': 1} and leads[0]['snippet'] == 'x'


def test_bing_and_google_are_separate_lists_with_separate_labels():
    leads = search.merge([ok('google', 3, [('https://a.example', 't', 's')]),
                          ok('bing', 3, [('https://a.example', 't', 's')])])
    assert set(leads[0]['ranks']) == {'g3', 'b3'}


def test_a_lead_found_by_three_lists_ranks_above_one_found_once():
    leads = search.merge([
        ok('google', 1, [('https://once.example', 't', 's'), ('https://thrice.example', 't', 's')]),
        ok('google', 2, [('https://thrice.example', 't', 's')]),
        ok('exa', None, [('https://thrice.example', 't', 's')]),
    ])
    ranked = search.rank(leads)
    assert ranked[0]['url'] == 'https://thrice.example'
    assert ranked[0]['score'] == 1.0 and ranked[0]['jev'] is None


def test_jev_scores_average_in_with_scaled_rrf():
    leads = search.merge([ok('google', 1, [('https://a.example', 't', 's'), ('https://b.example', 't', 's')])])
    ranked = search.rank(leads, jev=[0.0, 1.0])  # a ranks first by RRF; Jev prefers b
    by_url = {lead['url']: lead for lead in ranked}
    assert by_url['https://a.example']['score'] == 0.5
    assert by_url['https://b.example']['score'] > 0.5
    assert ranked[0]['url'] == 'https://b.example'


def test_jev_is_off_without_a_key(env):
    assert search.jev_scores('q', [{'title': 't', 'snippet': 's'}], clock()) == (None, 'off')


def test_jev_scores_every_lead_when_it_answers(env):
    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'k')

    def fake(state, questions, key, timeout=60):
        return {'answers': {name: {'probabilities': {'3': 1.0}} for name in questions}}

    env.monkeypatch.setattr(search.fetch, '_jev_request', fake)
    leads = [{'title': 't{}'.format(i), 'snippet': 's'} for i in range(45)]  # two batches
    scores, status = search.jev_scores('q', leads, clock())
    assert status == 'on' and scores == [1.0] * 45


def test_one_failed_jev_batch_discards_every_jev_score(env):
    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'k')
    calls = []

    def fake(state, questions, key, timeout=60):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('jev down')
        return {'answers': {name: {'probabilities': {'3': 1.0}} for name in questions}}

    env.monkeypatch.setattr(search.fetch, '_jev_request', fake)
    scores, status = search.jev_scores('q', [{'title': str(i), 'snippet': ''} for i in range(45)], clock())
    assert scores is None and status.startswith('failed')


def test_jev_is_skipped_when_time_is_short(env):
    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'k')
    env.monkeypatch.setattr(search, 'JEV_MIN', 10_000)
    assert search.jev_scores('q', [{'title': 't', 'snippet': 's'}], clock()) == (None, 'skipped (time)')


def test_a_jev_batch_that_never_returns_cannot_hold_the_call_open(env):
    env.monkeypatch.setattr(search.fetch, 'typesafe_key', lambda: 'k')
    env.monkeypatch.setattr(search, 'JEV_MIN', 0.1)
    env.monkeypatch.setattr(search, 'RESERVE', 0.2)
    env.monkeypatch.setattr(search.fetch, '_jev_request', lambda *a, **k: env.release.wait())
    started = time.monotonic()
    scores, status = search.jev_scores('q', [{'title': 't', 'snippet': 's'}], search.Clock(1.0))
    assert time.monotonic() - started < 1.5
    assert scores is None and status == 'skipped (time)'


# --- the record ------------------------------------------------------------

def test_the_record_sits_beside_the_tsv_and_its_folder_is_created(env):
    tsv = str(env.tmp / 'run' / 'Run_20261017.tsv')
    path = search.record_path('What does Acme charge?', tsv=tsv,
                              now=datetime_utc(2026, 10, 17, 10, 15, 0))
    assert path == str(env.tmp / 'run' / 'Run_20261017.searches' / '20261017T101500Z-what-does-acme-charge.json')


def datetime_utc(*args):
    from datetime import datetime, timezone
    return datetime(*args, tzinfo=timezone.utc)


def test_without_a_tsv_the_record_goes_to_out_dir_or_tmp():
    assert search.record_path('a', out_dir='/x', now=datetime_utc(2026, 1, 1)).startswith('/x/')
    assert search.record_path('a', now=datetime_utc(2026, 1, 1)).startswith('/tmp/legwork/searches/')


def search_main(env, *argv):
    return search.main(list(argv))


def test_two_calls_in_one_second_do_not_overwrite_each_other(env, capsys):
    tsv = str(env.tmp / 'run.tsv')
    for _ in range(2):
        assert search_main(env, '--angle', 'a', '--wording', 'w1', '--tsv', tsv) == 0
    files = list((env.tmp / 'run.searches').iterdir())
    assert len(files) == 2


def test_the_record_holds_wordings_failures_leads_and_the_answer(env, capsys):
    env.monkeypatch.setattr(search, 'exa_key', lambda: 'k')
    env.monkeypatch.setattr(search, 'urlopen', lambda r, timeout=None: FakeResponse(EXA_PAYLOAD))
    FakePopen.script['w2'] = (2, '', '{"error": "quota"}')
    tsv = str(env.tmp / 'run.tsv')
    assert search_main(env, '--angle', 'what does acme charge', '--wording', 'w1', '--wording', 'w2', '--tsv', tsv) == 0
    record = json.load(open(next((env.tmp / 'run.searches').iterdir())))
    assert record['angle'] == 'what does acme charge' and record['wordings'] == ['w1', 'w2']
    assert {p['status'] for p in record['providers']} == {'ok', 'refused'}
    assert record['exa_answer'] == 'Acme charges 30 dollars.' and record['exa_cost'] == 0.005
    assert record['jev'] == 'off' and len(record['leads']) == 4
    assert not os.path.exists(tsv)  # search.py writes nothing to the run's .tsv


# --- output ----------------------------------------------------------------

def test_output_has_a_status_line_capped_leads_a_more_line_and_the_answer_last(env, capsys):
    env.monkeypatch.setattr(search, 'exa_key', lambda: 'k')
    env.monkeypatch.setattr(search, 'urlopen', lambda r, timeout=None: FakeResponse(
        dict(EXA_PAYLOAD, answer='A' * 2000)))
    wordings = ['w{}'.format(i) for i in range(1, 7)]
    args = ['--angle', 'q', '--show', '5', '--tsv', str(env.tmp / 'run.tsv')]
    for wording in wordings:
        args += ['--wording', wording]
    assert search_main(env, *args) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].startswith('search: 6 wordings · google 6/6 ok · exa ok · jev: off · 19 leads (top 5 shown)')
    assert ' 5. ' in out and ' 6. ' not in out
    assert '+14 more: search.py --more ' in out and '--from 6' in out
    heading = "Exa's written answer - UNVERIFIED, NOT A SOURCE. Open the cited pages before using anything in it:"
    assert heading in out
    answer = out.split(heading, 1)[1].strip()
    assert len(answer) <= 1500 and out.rstrip().endswith(answer)


def test_a_lead_line_shows_title_url_snippet_and_its_lists(env):
    lead = {'url': 'https://acme.example/pricing', 'title': 'T' * 150, 'snippet': 'S\n' * 200,
            'ranks': {'exa': 2, 'b2': 1, 'g5': 3, 'g1': 1}}
    lines = search.lead_lines([lead], 1, 40)
    assert lines[0] == ' 1. ' + 'T' * 100
    assert lines[1] == '    https://acme.example/pricing'
    assert lines[2].endswith('[g1 g5 b2 exa]') and '\n' not in lines[2]
    assert len(lines[2].split('"')[1]) <= 163  # 160 characters and an ellipsis


def test_no_bright_data_and_no_exa_key_exits_4_and_says_use_websearch(env, capsys):
    env.monkeypatch.setattr(search.shutil, 'which', lambda name: None)
    assert search_main(env, '--angle', 'q', '--wording', 'w1', '--out-dir', str(env.tmp)) == search.EXIT_NO_PROVIDER
    out = capsys.readouterr().out
    assert 'google: not installed' in out and 'exa: no key' in out
    assert 'search: no search provider available - use WebSearch' in out


def test_every_call_refused_also_exits_4(env, capsys):
    FakePopen.script['w1'] = (2, '', '{"error": "quota"}')
    assert search_main(env, '--angle', 'q', '--wording', 'w1', '--out-dir', str(env.tmp)) == 4


def test_zero_results_from_a_working_provider_is_exit_0(env, capsys):
    FakePopen.script['w1'] = (1, '', json.dumps({'error': search.ZERO_RESULTS}))
    assert search_main(env, '--angle', 'q', '--wording', 'w1', '--out-dir', str(env.tmp)) == 0
    assert '0 leads' in capsys.readouterr().out


def test_no_exa_flag_sends_nothing_to_exa(env, capsys):
    env.monkeypatch.setattr(search, 'exa_key', lambda: 'k')  # urlopen still raises if called
    assert search_main(env, '--angle', 'q', '--wording', 'w1', '--no-exa', '--out-dir', str(env.tmp)) == 0
    assert 'exa: off' in capsys.readouterr().out


def test_engine_both_sends_each_wording_to_google_and_bing(env, capsys):
    search_main(env, '--angle', 'q', '--wording', 'w1', '--engine', 'both', '--out-dir', str(env.tmp))
    engines = sorted(p.cmd[p.cmd.index('--engine') + 1] for p in FakePopen.instances)
    assert engines == ['bing', 'google']


@pytest.mark.parametrize('argv', [
    ['--wording', 'w1'],                                        # no angle
    ['--angle', 'q'],                                           # no wording
    ['--angle', 'q'] + ['--wording', 'w'] * 13,                 # too many
    ['--angle', 'q', '--wording', 'w1', '--show', '0'],
    ['--angle', 'q', '--wording', 'w1', '--engine', 'yandex'],
])
def test_bad_arguments_exit_2(env, argv):
    with pytest.raises(SystemExit) as exc:
        search.main(argv)
    assert exc.value.code == 2


# --- --more ------------------------------------------------------------------

def test_more_prints_the_next_slice_with_no_network(env, capsys):
    tsv = str(env.tmp / 'run.tsv')
    args = ['--angle', 'q', '--show', '3', '--tsv', tsv]
    for wording in ('w1', 'w2'):
        args += ['--wording', wording]
    search_main(env, *args)
    capsys.readouterr()
    record = str(next((env.tmp / 'run.searches').iterdir()))
    before = len(FakePopen.instances)
    assert search.main(['--more', record, '--from', '4', '--show', '2']) == 0
    out = capsys.readouterr().out
    assert out.startswith('search: leads 4 to 5 of 6 from ')
    assert ' 4. ' in out and ' 5. ' in out and ' 6. ' not in out
    assert '+1 more: search.py --more ' in out and '--from 6' in out
    assert len(FakePopen.instances) == before


def test_more_past_the_end_or_on_an_empty_record_says_so(env, capsys):
    path = env.tmp / 'empty.json'
    path.write_text(json.dumps({'leads': []}))
    assert search.main(['--more', str(path)]) == 0
    assert capsys.readouterr().out.strip() == 'search: no leads from 41; the record has 0'


def test_more_on_a_missing_record_exits_2(env, capsys):
    assert search.main(['--more', str(env.tmp / 'nope.json')]) == 2
```

Also add `import os` to the imports at the top of `tests/test_search.py`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd skills/legwork && python3 -m pytest tests/test_search.py -q`
Expected: the new tests FAIL with `AttributeError: module 'search' has no attribute 'merge'` (and similar); the Task 5 tests still pass.

- [ ] **Step 3: Implement part 2** (append to `skills/legwork/scripts/search.py`)

```python
# ---------------------------------------------------------------------------
# Merge, rank, record and print
# ---------------------------------------------------------------------------

RRF_K = 60
SHOW_TITLE = 100
SHOW_SNIPPET = 160
SHOW_ANSWER = 1500
ANSWER_HEADING = ("Exa's written answer - UNVERIFIED, NOT A SOURCE. "
                  "Open the cited pages before using anything in it:")
_LETTER = {'google': 'g', 'bing': 'b'}


def list_label(result):
    """One ranked list per provider per wording: g3 and b3 are two lists."""
    if result['provider'] == 'exa':
        return 'exa'
    return '{}{}'.format(_LETTER.get(result['provider'], result['provider'][:1]), result['wording'])


def merge(results):
    """Leads keyed on the canonical URL. Each keeps every list that found it with
    its best rank there, the longest snippet and the first title."""
    leads = {}
    for result in results:
        if not result.get('ok'):
            continue
        label = list_label(result)
        for row in result.get('results') or []:
            key = canonicalize(row.get('url') or '')
            if not key:
                continue
            lead = leads.get(key)
            if lead is None:
                lead = leads[key] = {'url': row['url'], 'title': row.get('title') or '',
                                     'snippet': row.get('snippet') or '', 'date': row.get('date') or '', 'ranks': {}}
            if len(row.get('snippet') or '') > len(lead['snippet']):
                lead['snippet'] = row['snippet']
            if not lead['title'] and row.get('title'):
                lead['title'] = row['title']
            if not lead['date'] and row.get('date'):
                lead['date'] = row['date']
            rank = int(row.get('rank') or 1)
            lead['ranks'][label] = min(rank, lead['ranks'].get(label, rank))
    return list(leads.values())


def rrf(lead):
    return sum(1.0 / (RRF_K + rank) for rank in lead['ranks'].values())


def jev_scores(angle, leads, clock):
    """(scores or None, status). All or nothing: if any batch fails or runs out
    of time, no lead is Jev-scored, so no lead is ranked on a different basis
    from another. Ranking only - nothing is ever dropped on Jev's say."""
    if not leads:
        return None, 'off'
    key = fetch.typesafe_key()
    if not key:
        return None, 'off'
    if clock.remaining() < JEV_MIN:
        return None, 'skipped (time)'
    texts = ['{}\n{}'.format(lead.get('title') or '', lead.get('snippet') or '') for lead in leads]
    batches = [texts[i:i + fetch.JEV_BATCH] for i in range(0, len(texts), fetch.JEV_BATCH)]
    timeout = max(1.0, clock.remaining() - JEV_MARGIN)
    out, errors = [None] * len(batches), []

    def work(number, batch):
        state = {'question': angle, 'passages': {'p{}'.format(i): text for i, text in enumerate(batch)}}
        questions = {'p{}'.format(i): {
            'type': 'score', 'criteria': fetch.JEV_LEVELS,
            'instructions': 'How well does search result `passages.p{}` help answer `question`?'.format(i)}
            for i in range(len(batch))}
        try:
            answers = (fetch._jev_request(state, questions, key, timeout=timeout) or {}).get('answers') or {}
            out[number] = [fetch._expected_score(answers.get('p{}'.format(i))) for i in range(len(batch))]
        except Exception as exc:  # noqa: BLE001 - a ranking aid never fails the search
            errors.append(' '.join(str(exc).split())[:80] or type(exc).__name__)

    threads = [threading.Thread(target=work, args=(n, b), daemon=True) for n, b in enumerate(batches)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(max(0.0, clock.remaining()))
    if errors:
        return None, 'failed ({})'.format(errors[0])
    if any(scores is None for scores in out):
        return None, 'skipped (time)'
    return [score for scores in out for score in scores], 'on'


def rank(leads, jev=None):
    """RRF scaled to the top lead, averaged with Jev's score when there is one
    (the mean of a lexical and a Jev score ranked best offline on 27 Sep 2026)."""
    raw = [rrf(lead) for lead in leads]
    top = max(raw) if raw else 0.0
    for index, lead in enumerate(leads):
        scaled = raw[index] / top if top else 0.0
        lead['rrf'] = round(raw[index], 6)
        lead['jev'] = None if jev is None else round(jev[index], 3)
        lead['score'] = round(scaled if jev is None else (scaled + jev[index]) / 2, 6)
    return sorted(leads, key=lambda lead: (-lead['score'], lead['url']))


def _slug(text, limit=60):
    return '-'.join(re.findall(r'[a-z0-9]+', (text or '').lower()))[:limit].strip('-') or 'angle'


def record_path(angle, tsv=None, out_dir=None, now=None):
    if tsv:
        folder = os.path.splitext(tsv)[0] + '.searches'
    else:
        folder = out_dir or os.path.join('/tmp', 'legwork', 'searches')
    stamp = (now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%SZ')
    return os.path.join(folder, '{}-{}.json'.format(stamp, _slug(angle)))


def _write_record(path, record):
    """Write the record, never over an earlier one from the same second."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    base, ext = os.path.splitext(path)
    candidate, n = path, 1
    while os.path.exists(candidate):
        n += 1
        candidate = '{}-{}{}'.format(base, n, ext)
    with open(candidate, 'w', encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1)
    return candidate


def _label_order(label):
    if label == 'exa':
        return (2, 0)
    number = int(label[1:]) if label[1:].isdigit() else 0
    return (0 if label[0] == 'g' else 1, number)


def lead_lines(leads, start, show):
    lines = []
    for number, lead in enumerate(leads[start - 1:start - 1 + show], start):
        title = ' '.join((lead.get('title') or lead['url']).split())[:SHOW_TITLE]
        snippet = ' '.join((lead.get('snippet') or '').split())
        if len(snippet) > SHOW_SNIPPET:
            snippet = snippet[:SHOW_SNIPPET] + '...'
        labels = ' '.join(sorted(lead.get('ranks') or {}, key=_label_order))
        lines.append('{:>2}. {}'.format(number, title))
        lines.append('    {}'.format(lead['url']))
        lines.append('    "{}"   [{}]'.format(snippet, labels) if snippet else '    [{}]'.format(labels))
    return lines


def _more_line(path, remaining, start):
    return '+{} more: search.py --more {} --from {}'.format(remaining, path, start)


def _provider_status(results):
    parts = []
    for provider in ('google', 'bing'):
        mine = [r for r in results if r['provider'] == provider]
        if not mine:
            continue
        skipped = [r for r in mine if r['status'] == 'skipped']
        if skipped:
            parts.append('{}: {}'.format(provider, skipped[0]['reason']))
            continue
        text = '{} {}/{} ok'.format(provider, sum(r['ok'] for r in mine), len(mine))
        bad = {}
        for r in mine:
            if not r['ok']:
                bad[r['status']] = bad.get(r['status'], 0) + 1
        if bad:
            text += ' ({})'.format(', '.join('{} {}'.format(count, status) for status, count in sorted(bad.items())))
        parts.append(text)
    exa = next((r for r in results if r['provider'] == 'exa'), None)
    if exa is not None:
        if exa['ok']:
            parts.append('exa ok')
        elif exa['status'] == 'skipped':
            parts.append('exa: {}'.format(exa['reason']))
        else:
            parts.append('exa: {} ({})'.format(exa['status'], exa['reason']))
    return parts


def cmd_search(angle, wordings, args):
    clock = Clock(args.time_limit)
    engines = {'google': ['google'], 'bing': ['bing'], 'both': ['google', 'bing']}[args.engine]
    opts = {'country': args.country, 'language': args.language}
    jobs, skipped = [], []
    if bright_data_installed():
        for engine in engines:
            for number, wording in enumerate(wordings, 1):
                jobs.append(('{}{}'.format(_LETTER[engine], number),
                             (lambda e=engine, w=wording, n=number: search_bd(e, w, n, opts, clock)),
                             provider_result(engine, wording, number, 'deadline')))
    else:
        skipped += [provider_result(engine, '', None, 'skipped', 'not installed') for engine in engines]
    if args.no_exa:
        skipped.append(provider_result('exa', angle, status='skipped', reason='off'))
    else:
        key = exa_key()
        if key:
            jobs.append(('exa', lambda: search_exa(angle, key, clock), provider_result('exa', angle, status='deadline')))
        else:
            skipped.append(provider_result('exa', angle, status='skipped', reason='no key'))

    results = run_jobs(jobs, clock) + skipped
    leads = merge(results)
    jev, jev_status = jev_scores(angle, leads, clock)
    leads = rank(leads, jev)
    exa = next((r for r in results if r['provider'] == 'exa'), {})
    answer = ' '.join(str(exa.get('answer') or '').split())

    path = _write_record(record_path(angle, args.tsv, args.out_dir), {
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'), 'angle': angle, 'wordings': wordings,
        'engine': args.engine, 'country': args.country, 'language': args.language,
        'providers': results, 'jev': jev_status, 'leads': leads,
        'exa_answer': exa.get('answer') or '', 'exa_cost': exa.get('cost'),
        'seconds': round(clock.elapsed(), 1)})

    shown = min(args.show, len(leads))
    count = '{} lead{}'.format(len(leads), '' if len(leads) == 1 else 's')
    if len(leads) > shown:
        count += ' (top {} shown)'.format(shown)
    status = ['search: {} wording{}'.format(len(wordings), '' if len(wordings) == 1 else 's')]
    status += _provider_status(results)
    status += ['jev on' if jev_status == 'on' else 'jev: {}'.format(jev_status), count,
               '{:.0f}s'.format(clock.elapsed())]
    lines = [' · '.join(status)]
    lines += lead_lines(leads, 1, shown)
    if len(leads) > shown:
        lines.append(_more_line(path, len(leads) - shown, shown + 1))
    if not any(r['ok'] for r in results):
        lines.append('search: no search provider available - use WebSearch')
    if answer:
        lines += ['', ANSWER_HEADING, '    ' + answer[:SHOW_ANSWER]]
    print('\n'.join(lines))
    return 0 if any(r['ok'] for r in results) else EXIT_NO_PROVIDER


def cmd_more(path, start, show):
    try:
        with open(path, encoding='utf-8') as handle:
            record = json.load(handle)
    except (OSError, ValueError) as exc:
        print('search: cannot read {}: {}'.format(path, exc), file=sys.stderr)
        return 2
    leads = record.get('leads') or []
    if start > len(leads):
        print('search: no leads from {}; the record has {}'.format(start, len(leads)))
        return 0
    end = min(len(leads), start - 1 + show)
    lines = ['search: leads {} to {} of {} from {}'.format(start, end, len(leads), path)]
    lines += lead_lines(leads, start, show)
    if end < len(leads):
        lines.append(_more_line(path, len(leads) - end, end + 1))
    print('\n'.join(lines))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='search.py', description=__doc__.split('\n')[1].strip())
    parser.add_argument('--angle', help='the angle, verbatim from Frame; this is what Exa is asked')
    parser.add_argument('--wording', action='append', default=[], help='repeatable; 1 to 12, 6 to 10 expected')
    parser.add_argument('--tsv', help="the run's fetch log; the search record goes beside it")
    parser.add_argument('--out-dir', dest='out_dir', help='where the search record goes when there is no --tsv')
    parser.add_argument('--country', default='gb')
    parser.add_argument('--language', default='en')
    parser.add_argument('--engine', choices=['google', 'bing', 'both'], default='google')
    parser.add_argument('--no-exa', dest='no_exa', action='store_true')
    parser.add_argument('--show', type=int, default=40, help='leads to print; the rest are in the record')
    parser.add_argument('--time-limit', dest='time_limit', type=float, default=150.0,
                        help='seconds for every network call together (default 150)')
    parser.add_argument('--more', help='print further leads from a saved search record; no network')
    parser.add_argument('--from', dest='start', type=int, default=41, help='with --more, the first lead to print')
    args = parser.parse_args(argv)
    if args.show < 1:
        parser.error('--show must be at least 1')
    if args.more:
        return cmd_more(args.more, max(1, args.start), args.show)
    angle = ' '.join((args.angle or '').split())
    wordings = [' '.join(w.split()) for w in args.wording if w.strip()]
    if not angle:
        parser.error('--angle is required')
    if not 1 <= len(wordings) <= 12:
        parser.error('give 1 to 12 --wording values')
    return cmd_search(angle, wordings, args)


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `cd skills/legwork && python3 -m pytest tests/test_search.py -q`
Expected: all PASS. If `test_output_has_a_status_line...` fails on the lead count, print `out` and check the arithmetic: six wordings each return three distinct URLs (18) plus Exa's one (19).

- [ ] **Step 5: Run the whole suite and the stdlib-import check, then commit**

Run: `cd skills/legwork && python3 -m pytest tests/ -q && cd ../.. && python3 - <<'PY'
import ast, pathlib, sys
STDLIB = set(sys.stdlib_module_names)
LOCAL = {p.stem for p in pathlib.Path("skills/legwork/scripts").glob("*.py")}
tree = ast.parse(pathlib.Path("skills/legwork/scripts/search.py").read_text())
bad = [n.names[0].name if isinstance(n, ast.Import) else n.module for n in ast.walk(tree)
       if isinstance(n, (ast.Import, ast.ImportFrom)) and n.module != "__future__"
       and (n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0] not in STDLIB | LOCAL]
print("non-stdlib imports:", bad); sys.exit(1 if bad else 0)
PY`
Expected: suite PASS; `non-stdlib imports: []`.

```bash
git add skills/legwork/scripts/search.py skills/legwork/tests/test_search.py
git commit -m "feat(search): merge, rank (RRF, Jev averaged in), search record, compact output and --more

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: The wording rule, the brief and `brief.py`

**Files:**
- Modify: `skills/legwork/SKILL.md` (step 3 Gather: the "Search with at least three query variants" paragraph, the ladder table, the "Subagents use the free rungs only" bullet; the Scripts table)
- Modify: `skills/legwork/reference/subagent-brief.md` (the fenced template)
- Modify: `skills/legwork/scripts/brief.py`
- Test: `skills/legwork/tests/test_brief.py`

**Interfaces:**
- Consumes (Tasks 5-6): the `search.py` command line.
- Produces: `brief.fill(template, angle, effort, date, wordings, known=(), rule=None, tsv=None)`; `brief.read_wordings_rule(path=SKILL_FILE) -> str`; markers `{WORDINGS_RULE}`, `{TSV}`; `DEFAULT_WORDINGS = {'narrow': (6, 8), 'comparison': (8, 10)}`; CLI flag `--wordings N-M` (`--searches` removed).

- [ ] **Step 1: Update the tests first** (edit `tests/test_brief.py`)

Replace the parametrised effort test and the budget test:

```python
@pytest.mark.parametrize('effort, phrase, wordings', [
    ('narrow', 'This is one narrow fact', '6 to 8 wordings.'),
    ('comparison', 'This is a multi-option comparison', '8 to 10 wordings.'),
])
def test_effort_picks_one_sentence_and_a_wordings_budget(effort, phrase, wordings):
    out = render('--angle', ANGLE, '--effort', effort).stdout
    assert phrase in out and wordings in out
    other = 'multi-option comparison' if effort == 'narrow' else 'one narrow fact'
    assert other not in out


def test_the_wordings_budget_can_be_set():
    out = render('--angle', ANGLE, '--effort', 'narrow', '--wordings', '4-5').stdout
    assert '4 to 5 wordings.' in out


def test_the_old_searches_flag_is_refused():
    assert render('--angle', ANGLE, '--effort', 'narrow', '--searches', '1-2').returncode != 0
```

Add:

```python
def test_the_brief_carries_the_wording_rule_from_skill_md():
    rule = brief.read_wordings_rule()
    assert 'Ask the angle 6 to 10 ways' in rule
    out = render('--angle', ANGLE, '--effort', 'narrow').stdout
    assert rule in out


def test_the_brief_carries_the_search_command_with_a_real_path_and_the_tsv(tmp_path):
    tsv = str(tmp_path / 'Run_20261017.tsv')
    out = render('--angle', ANGLE, '--effort', 'narrow', '--tsv', tsv).stdout
    match = re.search(r'python3 (\S+/scripts/search\.py) --angle', out)
    assert match and os.path.exists(match.group(1)), out
    assert '--tsv "{}"'.format(tsv) in out


def test_without_a_tsv_the_search_command_names_a_placeholder_log():
    out = render('--angle', ANGLE, '--effort', 'narrow').stdout
    assert '--tsv "RUN.tsv"' in out


def test_the_return_shape_offers_serp_and_entity_sites():
    out = render('--angle', ANGLE, '--effort', 'narrow').stdout
    assert '"serp"' in out and '{"name": "Acme", "site": "acme.example"}' in out


def test_a_skill_md_without_the_rule_markers_is_refused(tmp_path):
    fake = tmp_path / 'SKILL.md'
    fake.write_text('no markers here', encoding='utf-8')
    with pytest.raises(brief.TemplateChanged):
        brief.read_wordings_rule(str(fake))
```

Change the last line of `test_a_template_missing_a_placeholder_is_refused` to pass the new arguments explicitly:

```python
        brief.fill(template, ANGLE, 'narrow', '2026-09-24', None, rule='rule text')
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd skills/legwork && python3 -m pytest tests/test_brief.py -q`
Expected: the new and changed tests FAIL.

- [ ] **Step 3: Write the marked rule into `SKILL.md`**

Replace this paragraph in step 3 (Gather):

```markdown
**Search with at least three query variants per angle:** a plain one; a targeted one
(`site:` the primary party, an exact phrase, or `filetype:pdf`); and a negative
one built from the falsifier. Year-pin queries about prices, releases,
regulation and news, and nothing else.
```

with:

```markdown
<!-- wordings-rule -->
**Ask the angle 6 to 10 ways, then search them all at once.** Write the
wordings as different people would put the same question: a plain one; one
aimed at the primary party's own site (`site:`, an exact phrase, or
`filetype:pdf`); a buyer's; a practitioner's; a critic's; and a negative one
built from the falsifier. Year-pin only prices, releases, regulation and news.
Name no organisation, product or site that did not come from "Already found" or
an earlier round's sources, so a `site:` wording waits until a round has named
the party.

Run every wording through `search.py` in one call, then search two or three of
them with WebSearch as well, because WebSearch finds pages Bright Data does
not. If the first 40 leads do not answer the angle, read the next ones with
`search.py --more`. Exa's written answer is printed last and is not a source:
open a cited page before using anything in it. If `search.py` exits 4, no
search provider is available: search every wording with WebSearch instead.
<!-- /wordings-rule -->
```

Replace the ladder table with:

```markdown
| Rung | Call | When |
|---|---|---|
| 1 | `search.py --angle "..." --wording "..." [...] --tsv "$OUT/$BASE.tsv"` | Always, as the wording rule above says |
| 2 | `WebSearch` | As the wording rule above says |
| 3 | `platforms.py search --on X --query "..."` | The answer is a record a platform holds: a thread, a package, a repository, a dated news item, a changelog. Free, and returns the record rather than a page about it. `platforms.py list` shows the ten |
| 4 | `bd_search.py "<query>" -m general --engine bing --country XX --language yy` | Thin (fewer than two independent parties) after the wordings, or the question is geo-specific |
| 5 | `bd_search.py -m discover --intent "..."` | Two engines still thin. Still thin after this is a finding: say what was searched |
```

Read the paragraph just below the table ("A search result is a lead, not a page you read..."). Add one sentence to it, after the sentence about `--via websearch`: `A lead from search.py is logged with --via serp.` Make sure no sentence elsewhere in step 3 still says "three variants"; change any that does to "the wordings".

Replace the bullet:

```markdown
- **Subagents use the free rungs only.** A page one returns as blocked is yours
  to take up the paid rungs, if the finding needs it.
```

with:

```markdown
- **Subagents use the free rungs only, and `search.py`.** `search.py` makes paid
  search calls and is theirs to run; paid page retrieval (scrape, render,
  pipelines, Reddit) is not. A page one returns as blocked is yours to take up
  the paid rungs, if the finding needs it.
```

Add a row to the Scripts table, after the `fetch.py` row:

```markdown
| `search.py --angle "..." --wording "..." [...] [--tsv PATH] \| --more RECORD` | One angle asked many ways across Google and Exa in one call; leads ranked, never filtered, every one reachable with `--more` |
```

In the step 3 paragraph that tells you to write each brief with `brief.py`, pass `--tsv "$OUT/$BASE.tsv"` in the example command so the brief's `search.py` command names the run's log:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/brief.py --angle "what does the incumbent charge" \
  --effort narrow --date "$TODAY" --tsv "$OUT/$BASE.tsv"
```

- [ ] **Step 4: Update the template in `reference/subagent-brief.md`**

Inside the fenced block under "## The brief", insert a new section immediately before `## How to work`:

```
## How to search

{WORDINGS_RULE}

The command, with your wordings:

`python3 {SKILL_DIR}/scripts/search.py --angle "{the angle above, unchanged}" --wording "<wording 1>" --wording "<wording 2>" --tsv "{TSV}"`

and, for the next leads, the `--more` line it prints, such as
`python3 {SKILL_DIR}/scripts/search.py --more "<record path>" --from 41`.
```

Replace step 1 of "How to work" (the whole "Run at least three query variants..." item) with:

```
1. Search as above. Read the results before opening anything.
```

In "What to return", change the `via` list and the transport sentence:

```
 "via": "direct | webfetch | websearch | serp | api", "status": "ok | blocked",
```

```
A page that refused you is returned too, as its own object with
`"opened": false` and `"status": "blocked"`, even when you then found a copy
elsewhere. Use `"via": "direct"` for fetch.py, `"webfetch"` for WebFetch,
`"serp"` for a search.py lead you did not open, `"websearch"` for a WebSearch
result you did not open, and `"api"` for a platforms.py record.
```

After the `entities` example object, add:

```
An entity whose own site you opened a page on may be written as an object:
{"name": "Acme", "site": "acme.example"}. The site is the entity's own domain,
never an aggregator's, a directory's or a review site's.
```

Change the effort line `{n} to {m} searches.` to `{n} to {m} wordings.` Leave the Rules section and the last line untouched. Outside the fenced block, change any prose that says "three query variants" to "the wordings".

- [ ] **Step 5: Update `brief.py`**

At the top-of-file usage in the docstring, change `[--searches N-M]` to `[--wordings N-M] [--tsv PATH]`.

Replace the constants and `fill`:

```python
SKILL_FILE = os.path.join(SKILL_DIR, 'SKILL.md')
RULE_START = '<!-- wordings-rule -->'
RULE_END = '<!-- /wordings-rule -->'

DATE = '{YYYY-MM-DD}'
ANGLE = '{the single sub-question this agent is answering, verbatim from Frame}'
RETURN_ANGLE = '{the angle above, unchanged}'
BUDGET = '{n} to {m} wordings.'
SKILL = '{SKILL_DIR}'
EFFORT = ('{"This is one narrow fact - stop once you have it, from two\n'
          'independent sources." | "This is a multi-option comparison - spread the effort\n'
          'across the options rather than going deep on the first one."}')

KNOWN = '{what earlier rounds on this angle found}'
WORDINGS_RULE = '{WORDINGS_RULE}'
TSV = '{TSV}'

PLACEHOLDERS = (DATE, ANGLE, RETURN_ANGLE, BUDGET, SKILL, EFFORT, KNOWN, WORDINGS_RULE, TSV)
```

```python
DEFAULT_WORDINGS = {'narrow': (6, 8), 'comparison': (8, 10)}
```

(Delete `DEFAULT_SEARCHES`.)

```python
def read_wordings_rule(path=SKILL_FILE):
    """The wording rule, from between its markers in SKILL.md. It lives there
    once; the brief carries a copy, so the orchestrator and the subagent read
    the same words and there is one place to change them."""
    with open(path, encoding='utf-8') as handle:
        text = handle.read()
    start, end = text.find(RULE_START), text.find(RULE_END)
    if start < 0 or end < start:
        raise TemplateChanged('no {} ... {} block in {}'.format(RULE_START, RULE_END, path))
    return text[start + len(RULE_START):end].strip()


def fill(template, angle, effort, date, wordings, known=(), rule=None, tsv=None):
    missing = [marker for marker in PLACEHOLDERS if marker not in template]
    if missing:
        raise TemplateChanged(
            'the template in subagent-brief.md no longer has {} - update brief.py to match '
            'rather than hand-writing the brief'.format(', '.join(repr(m) for m in missing)))
    low, high = wordings or DEFAULT_WORDINGS[effort]
    out = template.replace(EFFORT, EFFORT_TEXT[effort])
    out = out.replace(BUDGET, '{} to {} wordings.'.format(low, high))
    out = out.replace(WORDINGS_RULE, read_wordings_rule() if rule is None else rule)
    out = out.replace(TSV, tsv or 'RUN.tsv')
    out = out.replace(DATE, date)
    out = out.replace(ANGLE, angle).replace(RETURN_ANGLE, angle)
    out = out.replace(SKILL, SKILL_DIR)
    out = out.replace(KNOWN, known_text(known))
    left = [marker for marker in PLACEHOLDERS if marker in out]
    if left:
        raise TemplateChanged('placeholders left unfilled: {}'.format(left))
    return out
```

Rename `_searches` to `_wordings` (same body). In `main()`, replace the `--searches` argument with:

```python
    parser.add_argument('--wordings', type=_wordings, default=None,
                        help='Wordings budget as N-M. Default 6-8 for narrow, 8-10 for comparison')
```

and change the `fill` call to:

```python
        text = fill(read_template(), angle, args.effort, date, args.wordings, known, tsv=args.tsv)
```

Update the `--tsv` help text: `'The run fetch log: the brief lists what earlier rounds on this angle found, and its search.py command records its searches beside it'`.

- [ ] **Step 6: Run the tests**

Run: `cd skills/legwork && python3 -m pytest tests/test_brief.py -q && python3 -m pytest tests/ -q`
Expected: all PASS, including `test_the_return_only_rule_is_still_the_last_line`.

- [ ] **Step 7: Check the rule is stated once**

Run: `grep -rn "Ask the angle 6 to 10 ways" skills/ | grep -v tests/`
Expected: exactly one line, in `skills/legwork/SKILL.md`.

Run: `grep -rn "three query variants\|at least three query" skills/legwork --include=*.md`
Expected: no lines (methodology.md is handled in Task 8; if it appears there only, that is expected now and fixed next).

- [ ] **Step 8: Commit**

```bash
git add skills/legwork/SKILL.md skills/legwork/reference/subagent-brief.md skills/legwork/scripts/brief.py skills/legwork/tests/test_brief.py
git commit -m "feat(brief): subagents search with search.py, the wording rule lives once in SKILL.md and brief.py copies it

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Docs, setup and what leaves the machine

**Files:**
- Modify: `skills/legwork/reference/methodology.md` (the "### Queries" section)
- Modify: `AGENTS.md` (Layout; the Bright Data convention bullet; the Jev bullet)
- Modify: `README.md` ("## Search backend"; "## Scripts" if it lists scripts)
- Modify: `SECURITY.md` ("### What leaves your machine"; "### Credentials"; "### On disk")
- Modify: `skills/legwork/setup.sh` (after the Python check, before the Bright Data block)

**Interfaces:** none (documentation and setup).

- [ ] **Step 1: methodology.md**

Replace the opening of "### Queries" (from "The three variants..." to the end of the bullet list) with:

```markdown
The wordings, for the angle "what does Acme charge" (the rule is in `SKILL.md`
step 3; these are examples of it):

- plain: `acme pricing 2026`
- the party's own site: `site:acme.example pricing`, or `"per user per month" acme`,
  or `acme price list filetype:pdf`
- a buyer's: `how much does acme cost for a team of ten`
- a practitioner's: `acme seat licence true-up annual billing`
- a critic's: `acme too expensive alternatives`
- negative: `acme price increase 2026`, `why we left acme`
```

Leave the "Year-pin dated material only" paragraph as it is.

- [ ] **Step 2: AGENTS.md**

In the Layout block, add under `platforms.py`:

```
                              #   search.py    many wordings across Google and Exa in one call
```

Replace the bullet that begins "Bright Data is a **fallback**, never a requirement." with:

```markdown
- Every search provider is **optional**. `search.py` uses Bright Data and Exa when each is available and says which it skipped and why; with neither it exits 4 and the run searches with the built-in `WebSearch`/`WebFetch`, so a run still completes with no CLI and no keys. Anything that assumes a provider is installed or funded is a bug. Exa's key is `EXA_API_KEY`, or `~/.dbhq/legwork/exa-api-key`.
```

In the TypeSafe bullet, after "a failed call never fails a fetch,", add: "and in `search.py` it only orders leads, all or nothing, and never drops one,".

- [ ] **Step 3: README.md**

In "## Search backend", replace the first table (under "**To search:**") with:

```markdown
| Situation | Provider |
|-----------|----------|
| Every angle, 6 to 10 wordings in one call | `search.py`: every wording to Bright Data Google in parallel, and the angle to Exa Answer once. Leads are ranked, never filtered, and every one is reachable with `--more` |
| Every angle, two or three of the wordings | `WebSearch` (free), which finds pages Bright Data does not |
| No search provider available (`search.py` exits 4) | `WebSearch` for every wording |
| The answer is a record a platform holds - a thread, a package, a repository, a dated news item, a vendor's changelog | `platforms.py` (free, keyless) |
| Thin after the wordings, or geo-specific | Bright Data SERP on a second engine, with `--country` and `--language` |
| Two engines still thin | Bright Data `-m discover`, intent-ranked |
```

After the "**The ten free platforms**" paragraph, add:

```markdown
**Optional keys.** `search.py` runs on whatever is available. Bright Data uses
the CLI's own login. Exa reads `EXA_API_KEY`, or a file holding only the key at
`~/.dbhq/legwork/exa-api-key` (mode 600); without it, `search.py` runs on
Google alone and says `exa: no key`. Exa's written answer is shown, marked as
unverified and not a source; only its cited pages, once opened, can be cited.
```

If the README has a "## Scripts" table, add the same `search.py` row as in `SKILL.md`.

- [ ] **Step 4: SECURITY.md**

In "### What leaves your machine", add after the first paragraph:

```markdown
**When `search.py` runs:** each wording goes to Bright Data as search text, as
with `bd_search.py`; the angle's text goes to Exa at `api.exa.ai`, only if an
Exa key is set; and, only if a TypeSafe key is set, each lead's title and
snippet and the angle go to TypeSafe to order the leads.
```

In "### Credentials", replace the paragraph with:

```markdown
Only a Bright Data API key, an Exa API key and a TypeSafe API key, and each only
if you choose to use that option. Each is read from the environment; the Exa
and TypeSafe keys may instead sit alone in `~/.dbhq/legwork/exa-api-key` and
`~/.dbhq/legwork/typesafe-api-key`, which you create (keep them mode 600). The
skill writes none of them to disk.
```

In "### On disk", add a bullet:

```markdown
- Writes one search record per `search.py` call beside the run's fetch log
  (`<run>.searches/`), or under `/tmp/legwork/searches/` without one: the
  wordings, every provider's results and Exa's answer
```

- [ ] **Step 5: setup.sh**

Insert after the `chmod +x ...` line and before the `# --- Bright Data CLI (optional fallback) ---` comment:

```bash
# --- Optional keys: Exa (search.py) and TypeSafe (Jev ranking) ---
# Never prompted for: each is optional, and setup must succeed without either.
report_key() {
    local label="$1" var="$2" file="$3"
    if [ -n "${!var:-}" ]; then
        echo "$label: key set in \$$var"
    elif [ -s "$file" ]; then
        echo "$label: key found in $file"
    else
        echo "$label: no key (optional). To enable: save the key alone in $file (chmod 600)"
    fi
}
echo ""
report_key "Exa (search.py)" EXA_API_KEY "$HOME/.dbhq/legwork/exa-api-key"
report_key "TypeSafe Jev (ranking)" TYPESAFE_API_KEY "$HOME/.dbhq/legwork/typesafe-api-key"
```

- [ ] **Step 6: Check**

Run: `bash -n skills/legwork/setup.sh && (shellcheck -S warning skills/legwork/setup.sh || true) && python3 -c "import pathlib,sys; bad=[str(p) for p in [pathlib.Path(x) for x in ('AGENTS.md','README.md','SECURITY.md')]+list(pathlib.Path('skills/legwork').rglob('*.md')) if any(c in p.read_text() for c in ('\u2013','\u2014'))]; print(bad); sys.exit(1 if bad else 0)" && cd skills/legwork && python3 -m pytest tests/ -q`
Expected: `bash -n` silent; no shellcheck warnings on the new block; the dash check prints `[]`; suite PASS.

Run: `grep -rn "three query variants\|at least three query" skills/legwork --include=*.md`
Expected: no lines.

- [ ] **Step 7: Commit**

```bash
git add AGENTS.md README.md SECURITY.md skills/legwork/reference/methodology.md skills/legwork/setup.sh
git commit -m "docs: search.py in the ladder, optional Exa key, what leaves the machine

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Live check (orchestrator, not a subagent)

This task makes real, billed calls and needs the keys on this machine, so the orchestrator runs it by hand after Tasks 1-8 are merged into the branch. It is not hermetic and adds no test.

- [ ] **Step 1: Run one real call**

```bash
cd skills/legwork
mkdir -p /tmp/legwork-live && python3 scripts/search.py \
  --angle "which UK banks publish a public API sandbox, and what does each require before you can call it?" \
  --wording "UK bank API sandbox developer portal" \
  --wording "open banking sandbox register developer UK" \
  --wording "bank developer portal sandbox credentials free sign up" \
  --wording "UK bank API sandbox requires Open Banking Directory enrolment" \
  --wording "bank sandbox API not available to individual developers UK" \
  --wording "fintech developer review UK bank sandbox" \
  --out-dir /tmp/legwork-live | tee /tmp/legwork-live/output.txt
echo "exit ${PIPESTATUS[0]}"
```

Expected: exit 0; the status line shows `google 6/6 ok` (or names the failures), `exa ok`, `jev on` if the TypeSafe key is present; 40 leads printed; a `+N more` line; Exa's answer last under its heading; total seconds under 150.

- [ ] **Step 2: Check `--more` against the real record**

Run the `--more` line the output printed. Expected: leads 41 onwards, no network.

- [ ] **Step 3: Check a provider failing**

Run Step 1 again with `EXA_API_KEY=invalid` in front. Expected: exit 0, `exa: failed (HTTP 401: ...)` or similar in the status line, Google results unaffected.

- [ ] **Step 4: Record it**

Write `evals/runs/2026-10-<day>-wide-search-live-check.md`: what was run, the status line, the time, the lead count, how many leads came from Exa only, Exa's cost from the record, and anything that looked wrong. Commit it with `docs(evals): wide search live check`.

---

### Task 10: The eval (orchestrator, before merge)

Not a subagent task: it runs 18 legwork sessions (about $50 to $100 of Claude usage plus a few pounds of search) and needs Dan's go-ahead to spend it. It follows the spec's "The eval" section exactly; this task only restates the steps.

- [ ] **Step 1:** Run banks, Postgres and campervan from `evals/keys/`, three runs each on `main` and three on this branch, on the current Sonnet, a few at a time.
- [ ] **Step 2:** Anonymise the 18 reports (remove the receipt line), and grade each case blind against its key with the prompts in `evals/grading.md`.
- [ ] **Step 3:** Per case, take the mean of three runs for core entities covered, wrong facts (WRONG ratings plus other errors) and scope errors.
- [ ] **Step 4:** Merge only if core coverage is higher than `main`'s in at least two of the three cases and lower in none, and wrong facts and scope errors are no higher than `main`'s in any case. Report time per question, Claude cost, Bright Data and Exa spend, searches run, and how often subagents used `--more`.
- [ ] **Step 5:** Write `evals/runs/<date>-wide-search-against-answer-keys.md` whichever way it falls, as the scripted-gathering trial's record was written, and update the spec's Status line.

---

## Self-review

Checked against the spec, section by section:

| Spec section | Task |
|---|---|
| A. How a subagent uses it | 7 (brief), 6 (`--more`) |
| B. `search.py` interface and steps 1-5 | 5, 6 |
| C. Providers, including the `bd_search.py` output contract and Exa's request | 5 |
| D. Failures, the deadline contract, exit codes | 5 (calls, deadline), 6 (exit 4, zero results, Jev) |
| E. Output, `--more` | 6 |
| F. The search record | 6 |
| G. What is logged (`serp`, nothing in the `.tsv`) | 3 (pinned), 6 (record only), 7 (brief) |
| H. Wordings, stated once and copied | 7 |
| I. `bd_search.py` fixes | 1 |
| J. Skill text, `brief.py`, the free-rungs exception, `AGENTS.md`, `README.md`, `setup.sh` | 7, 8 |
| K. What leaves the machine | 8 |
| L. Entity sites, `full_name`, `site_key`, the own-site check | 3, 4 |
| `fetch._jev_request` timeout | 2 |
| Testing, including the must-fail fixture | each task; 4 for the fixture |
| Live check, eval | 9, 10 |

Placeholders: none ("RUN.tsv" in the brief is a literal the subagent replaces, as the spec says). Names are consistent across tasks: `full_name`, `site_key`, `site_belongs`, `entity_sites`, `parse_entity_sites`, `check_rows_on_own_site`, `provider_result`, `search_bd`, `search_exa`, `run_jobs`, `merge`, `rank`, `jev_scores`, `record_path`, `lead_lines`, `main`. The five Review Focus items each have a test: 1 in Task 5, 2 and 4 and 5 in Task 6, 3 in Task 3.
