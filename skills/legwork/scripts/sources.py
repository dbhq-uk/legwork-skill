#!/usr/bin/env python3
"""
sources.py - fitness scoring and the run's fetch log.

Legwork ranks a source by whether it is the right KIND of thing for the CLAIM it
backs, not by whether its domain appears on an allowlist. The vendor's own
pricing page is the best possible evidence that a product costs $30; it is poor
evidence that the product is any good. A Substack by the engineer who built a
feature outranks a national newspaper on what that feature does.

That judgement is a small table (CLAIM_LADDERS) plus a recency curve whose
half-life depends on the claim kind: a 2019 pricing page is worthless, a 2019
regulatory filing is fine.

The fetch log is a TSV written alongside the report and sharing its base name.
One row per retrieval. It exists so the gate can answer two questions that
cannot otherwise be answered after the fact:

  - was this cited URL ever actually opened?   (fabricated-citation check)
  - which search ANGLE surfaced it?            (corroboration check)
  - what did it actually SAY?                  (qualitative-claim check)

The angle matters more than it looks. Legwork's Gather phase fans out across
sub-questions in order to find more sources per finding, so a raw source count
measures our own effort rather than corroboration. The angle is the layer we do
not amplify, so that is the layer corroboration is counted on.

The quote is the one field that survives its source. Roughly half of real findings
carry no figure at all, so without it a qualitative claim - "the marketplace has no
submission route" - would be backed only by proof that somebody opened the page. It
also means a claim outlives the page changing or going dead.

CLI:
    sources.py kinds
    sources.py log --tsv PATH --url URL --kind KIND --angle "..." --via direct \\
                   [--quote "..."] [--title "..."] [--date 2026-07-01] \\
                   [--text-file page.txt] [--query "..."] [--status ok]
    sources.py receipt --tsv PATH
    sources.py score --tsv PATH --claim-kind price [--format table|json]

Stdlib only. Runs on any python3 >= 3.9.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# What a source IS, independent of what it is being used to prove.
SOURCE_KINDS = (
    'vendor_pricing',       # the vendor's own pricing page
    'vendor_docs',          # official docs, API reference, changelog
    'vendor_announcement',  # dated announcement or release note
    'vendor_marketing',     # vendor blog, landing page, case study
    'registry',             # marketplace, package index, register - source of truth for existence
    'filing',               # company filing, regulator, ONS, government statistics
    'job_ad',
    'community',            # forum thread, Reddit, HN, review text
    'review_aggregate',     # G2 / Trustpilot / Capterra score pages
    'search_data',          # keyword volume, trends data
    'analyst',              # named analyst or research house
    'press',                # news coverage
    'blog',                 # third-party blog, tutorial
    'unknown',
)

# What a claim is ABOUT. 'general' is the fallback and deliberately forgiving.
CLAIM_KINDS = (
    'price',
    'capability',
    'demand',
    'market',
    'existence',
    'timeline',
    'sentiment',
    'compliance',
    'general',
)

TIERS = ('primary', 'secondary', 'commentary', 'marketing')

# Tier -> base score. Marketing is scored low rather than excluded: a vendor
# claiming its own product is popular is still evidence of what the vendor says.
TIER_BASE = {
    'primary': 100.0,
    'secondary': 70.0,
    'commentary': 40.0,
    'marketing': 15.0,
    'unrated': 30.0,
}

# For each claim kind, which source kinds sit in which tier. Anything not listed
# is 'unrated' for that claim - scored below commentary but above marketing, and
# flagged, because an unrated source is an unknown rather than a bad one.
CLAIM_LADDERS = {
    'price': {
        'primary': ('vendor_pricing',),
        'secondary': ('registry', 'vendor_docs', 'review_aggregate'),
        'commentary': ('analyst', 'press', 'blog', 'community'),
        'marketing': ('vendor_marketing',),
    },
    'capability': {
        'primary': ('vendor_docs', 'vendor_announcement'),
        'secondary': ('registry', 'community'),
        'commentary': ('blog', 'press', 'analyst'),
        'marketing': ('vendor_marketing',),
    },
    'demand': {
        'primary': ('job_ad', 'search_data', 'community', 'review_aggregate'),
        'secondary': ('analyst', 'filing'),
        'commentary': ('press', 'blog'),
        'marketing': ('vendor_marketing',),
    },
    'market': {
        'primary': ('filing',),
        'secondary': ('analyst',),
        'commentary': ('press', 'blog', 'community'),
        'marketing': ('vendor_marketing',),
    },
    'existence': {
        'primary': ('registry', 'vendor_docs'),
        'secondary': ('vendor_announcement', 'press'),
        'commentary': ('blog', 'community'),
        'marketing': ('vendor_marketing',),
    },
    'timeline': {
        'primary': ('vendor_announcement', 'vendor_docs'),
        'secondary': ('press', 'registry'),
        'commentary': ('blog', 'community', 'analyst'),
        'marketing': ('vendor_marketing',),
    },
    'sentiment': {
        'primary': ('community', 'review_aggregate'),
        'secondary': ('press',),
        'commentary': ('blog', 'analyst'),
        'marketing': ('vendor_marketing',),
    },
    'compliance': {
        'primary': ('filing', 'vendor_docs'),
        'secondary': ('vendor_announcement', 'analyst'),
        'commentary': ('press', 'blog', 'community'),
        'marketing': ('vendor_marketing',),
    },
    'general': {
        'primary': ('filing', 'vendor_docs', 'registry'),
        'secondary': ('vendor_announcement', 'press', 'analyst', 'community', 'job_ad'),
        'commentary': ('blog', 'review_aggregate', 'search_data'),
        'marketing': ('vendor_marketing',),
    },
}

# How fast a claim of this kind goes stale, in days. A price halves in value
# every six months; market structure takes three years to halve.
HALF_LIFE_DAYS = {
    'price': 180,
    'timeline': 180,
    'existence': 120,
    'demand': 365,
    'sentiment': 365,
    'capability': 540,
    'compliance': 540,
    'market': 1095,
    'general': 540,
}

# Recency never zeroes a source out: an old primary source still beats a fresh
# blog. The multiplier spans [RECENCY_FLOOR, 1.0].
RECENCY_FLOOR = 0.55
# Applied when a source carries no usable date. Sits below a fresh source but
# above a demonstrably stale one, and is reported rather than silently assumed.
RECENCY_UNKNOWN = 0.80

# Columns are appended, never inserted: a log written by an older version still
# parses positionally, which is what lets a refresh resume a run started months
# ago. 'quote' came after 'title', 'query' after 'quote'.
TSV_COLUMNS = ('url', 'kind', 'angle', 'via', 'fetched_at', 'status', 'date', 'numbers',
               'title', 'quote', 'query')

# One sentence, not a page. Long enough to carry a qualitative claim, short
# enough that the log stays a log.
MAX_QUOTE_CHARS = 300

# How the page was reached. 'api' covers a structured endpoint queried directly
# (a registry's REST API, a search API); 'local' covers evidence read from disk,
# which is the only way a finding about this repository can be recorded at all;
# 'mcp' covers a connected tool. Without these three a run is forced either to
# leave its best evidence out of the log or to re-fetch it through a transport
# the log accepts, which distorts the evidence trail rather than recording it.
# 'direct' is fetch.py: the page opened straight from this machine, which is the
# only free transport that yields page text rather than a model's summary of it.
VIA_VALUES = ('websearch', 'webfetch', 'direct', 'brightdata', 'api', 'local', 'mcp')

# A search result is a lead, not a page anybody opened. Every other transport
# returns the page or the record itself, including 'api' - a registry's own JSON
# is the record, not a snippet about it.
SNIPPET_VIA = 'websearch'


# ---------------------------------------------------------------------------
# Source-kind inference (fallback only - the caller should pass --kind)
# ---------------------------------------------------------------------------

_KIND_URL_HINTS = (
    (re.compile(r'/pricing|/plans|/buy\b|pricing\.', re.I), 'vendor_pricing'),
    (re.compile(r'^(docs|developer|learn|api|devcenter)\.|/docs/|/reference/|/api/', re.I), 'vendor_docs'),
    (re.compile(r'/changelog|/release-notes|/whats-new|/blog/.*(announc|now-available|ga\b)', re.I),
     'vendor_announcement'),
    (re.compile(r'reddit\.com|news\.ycombinator|/forum|community\.|stackoverflow\.com|/discussions?/', re.I),
     'community'),
    (re.compile(r'g2\.com|trustpilot\.|capterra\.|getapp\.', re.I), 'review_aggregate'),
    (re.compile(r'find-and-update\.company-information|companieshouse|ons\.gov|\.gov\.uk|\.gov/|europa\.eu', re.I),
     'filing'),
    (re.compile(r'/jobs?/|greenhouse\.io|lever\.co|workable\.com|indeed\.|linkedin\.com/jobs', re.I), 'job_ad'),
    (re.compile(r'trends\.google|keywordtool|ahrefs\.com|semrush\.com', re.I), 'search_data'),
    (re.compile(r'github\.com|npmjs\.com|pypi\.org|marketplace\.|skills\.sh', re.I), 'registry'),
)

_KIND_HOST_HINTS = (
    (re.compile(r'reuters\.com|apnews\.com|bbc\.|ft\.com|bloomberg\.com|theregister\.|techcrunch\.', re.I), 'press'),
    (re.compile(r'gartner\.com|forrester\.com|idc\.com|sacra\.com|cbinsights\.', re.I), 'analyst'),
)


def infer_source_kind(url, title=''):
    """Best-effort guess at what a URL is. The caller passing --kind always wins.

    Deliberately conservative: an unrecognised URL returns 'unknown' rather than
    a plausible guess, because a wrong kind silently moves a source between
    tiers, whereas 'unknown' is visible and scored as such.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    path = parsed.path or ''
    probe = host + path
    for pattern, kind in _KIND_URL_HINTS:
        if pattern.search(probe) or pattern.search(host):
            return kind
    for pattern, kind in _KIND_HOST_HINTS:
        if pattern.search(host):
            return kind
    return 'unknown'


# ---------------------------------------------------------------------------
# Dates and recency
# ---------------------------------------------------------------------------


def parse_date(value):
    """Parse an ISO-8601 date or datetime into an aware UTC datetime.

    Returns (datetime, None) or (None, reason). Naive input is assumed UTC.

    The predecessor of this function compared an aware datetime against a naive
    datetime.now(), raised TypeError, and swallowed it in a bare except - so
    every date carrying a timezone silently scored as unknown age. Everything
    here is aware, and failures are returned rather than hidden.
    """
    if value is None:
        return None, 'no date supplied'
    text = str(value).strip()
    if not text:
        return None, 'no date supplied'
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # Accept a bare date that fromisoformat on 3.9 rejects, e.g. '2026-7-1'.
        for fmt in ('%Y-%m-%d', '%d %B %Y', '%d %b %Y', '%B %d, %Y', '%b %d, %Y'):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None, 'unparseable date: {!r}'.format(str(value)[:40])
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), None


def recency_multiplier(published, claim_kind, now=None):
    """Exponential decay on a half-life chosen by claim kind.

    Returns (multiplier, age_days_or_None, note).
    """
    half_life = HALF_LIFE_DAYS.get(claim_kind, HALF_LIFE_DAYS['general'])
    parsed, reason = parse_date(published)
    if parsed is None:
        return RECENCY_UNKNOWN, None, reason
    reference = now or datetime.now(timezone.utc)
    age_days = (reference - parsed).total_seconds() / 86400.0
    if age_days < 0:
        return RECENCY_UNKNOWN, age_days, 'date is in the future'
    decay = 0.5 ** (age_days / half_life)
    multiplier = RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * decay
    return multiplier, age_days, None


# ---------------------------------------------------------------------------
# Fitness
# ---------------------------------------------------------------------------


def tier_for(source_kind, claim_kind):
    """Which tier this source kind occupies for this claim kind."""
    ladder = CLAIM_LADDERS.get(claim_kind, CLAIM_LADDERS['general'])
    for tier in TIERS:
        if source_kind in ladder.get(tier, ()):
            return tier
    return 'unrated'


def fitness(source_kind, claim_kind, published=None, now=None):
    """Score how well this source suits this claim. Returns a dict."""
    tier = tier_for(source_kind, claim_kind)
    base = TIER_BASE[tier]
    multiplier, age_days, note = recency_multiplier(published, claim_kind, now=now)
    notes = []
    if note:
        notes.append(note)
    if tier == 'unrated':
        notes.append("source kind {!r} is not rated for {!r} claims".format(source_kind, claim_kind))
    return {
        'source_kind': source_kind,
        'claim_kind': claim_kind,
        'tier': tier,
        'base': base,
        'recency_multiplier': round(multiplier, 3),
        'age_days': None if age_days is None else round(age_days, 1),
        'score': round(base * multiplier, 1),
        'notes': notes,
    }


# ---------------------------------------------------------------------------
# Numeric tokens
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r'(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?')

# A page yields far more numbers than any claim needs; cap so the log stays a
# log rather than becoming a copy of the page.
MAX_NUMBERS = 400


def extract_numbers(text, limit=MAX_NUMBERS):
    """Normalised numeric tokens found in text, insertion-ordered and unique.

    Thousands separators are stripped and trailing zeros normalised so that
    '1,600', '1600' and '1600.0' all compare equal. This is what lets the gate
    check that a figure in a finding actually appeared on a page that was
    fetched, without storing the page.
    """
    seen = {}
    for raw in _NUMBER_RE.findall(text or ''):
        token = raw.replace(',', '')
        try:
            value = float(token)
        except ValueError:
            continue
        key = str(int(value)) if value == int(value) else repr(value)
        if key not in seen:
            seen[key] = True
        if len(seen) >= limit:
            break
    return list(seen)


def numbers_for_row(explicit, page_text, quote):
    """Numeric tokens for one log row, and where they came from.

    Order matters. Page text is the strong form: every figure on the page is
    available to trace against. An explicit --numbers flag beats it because the
    caller extracted them elsewhere and knows better. The quote is the weak form
    and the important one: measured across seven real fetch logs on 2026-09-06,
    the numbers column was filled on 1 row of 215, because WebFetch returns a
    summary rather than page text and there was nothing to pass to --text-file.
    The quote is verbatim page text, so a figure inside it did appear on the
    page, and taking numbers from it is what makes figure tracing fire at all.
    """
    if explicit:
        tokens = [n.strip() for n in explicit.split(',') if n.strip()]
        if tokens:
            return tokens, 'flag'
    if page_text:
        tokens = extract_numbers(page_text)
        if tokens:
            return tokens, 'text'
    if quote:
        tokens = extract_numbers(quote)
        if tokens:
            return tokens, 'quote'
    return [], 'none'


# Curly punctuation and non-breaking spaces are the reason a quote copied from a
# rendered page fails a naive comparison against the same page's source text.
_MATCH_PUNCT = {0x2018: "'", 0x2019: "'", 0x201c: '"', 0x201d: '"',
                0x2013: '-', 0x2014: '-', 0x2212: '-', 0x00a0: ' '}


def normalise_for_match(text):
    """Fold the differences that stop a true quote matching the page it came from."""
    return re.sub(r'\s+', ' ', (text or '').translate(_MATCH_PUNCT)).strip().lower()


def quote_appears_in(quote, text):
    """Is this quote verbatim from this page text?

    The gate can check that a figure appeared on a page. Nothing could check
    that a *sentence* did, and around half of all findings carry no figure, so
    the quote is the only evidence those findings have. This is the check.
    """
    needle = normalise_for_match(quote)
    return bool(needle) and needle in normalise_for_match(text)


# ---------------------------------------------------------------------------
# Fetch log
# ---------------------------------------------------------------------------


def _clean(value):
    """TSV-safe single-line field."""
    return re.sub(r'\s+', ' ', str(value or '')).replace('\t', ' ').strip()


def append_row(tsv_path, row):
    """Append one retrieval to the log, writing the header if the file is new."""
    exists = os.path.exists(tsv_path) and os.path.getsize(tsv_path) > 0
    parent = os.path.dirname(os.path.abspath(tsv_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(tsv_path, 'a', encoding='utf-8') as handle:
        if not exists:
            handle.write('\t'.join(TSV_COLUMNS) + '\n')
        handle.write('\t'.join(_clean(row.get(column, '')) for column in TSV_COLUMNS) + '\n')


def read_rows(tsv_path):
    """Read the log. Returns [] when the file is absent.

    Tolerates a missing header (treats the file as headerless positional data)
    so a hand-edited log still parses.
    """
    if not os.path.exists(tsv_path):
        return []
    rows = []
    with open(tsv_path, encoding='utf-8') as handle:
        lines = [line.rstrip('\n') for line in handle if line.strip()]
    if not lines:
        return []
    header = lines[0].split('\t')
    if header[:1] == ['url'] and 'angle' in header:
        columns, body = header, lines[1:]
    else:
        columns, body = list(TSV_COLUMNS), lines
    for line in body:
        fields = line.split('\t')
        record = {column: (fields[i] if i < len(fields) else '') for i, column in enumerate(columns)}
        record['numbers'] = [n for n in record.get('numbers', '').split(',') if n]
        rows.append(record)
    return rows


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------

# Scoring already decays a source continuously. Freshness answers the blunter
# question the gate and the Challenge phase need: has this gone off? Two
# half-lives is the default horizon, i.e. the point at which recency has taken
# three quarters of the source's value away.
DEFAULT_STALE_HALF_LIVES = 2


def staleness_horizon_days(claim_kind, half_lives=DEFAULT_STALE_HALF_LIVES):
    """How old a source of this claim kind may be before it counts as stale."""
    return HALF_LIFE_DAYS.get(claim_kind, HALF_LIFE_DAYS['general']) * half_lives


def freshness(row, claim_kind, half_lives=DEFAULT_STALE_HALF_LIVES, now=None):
    """Classify one logged source as 'current', 'stale' or 'undated'.

    Undated is deliberately its own state rather than being folded into stale.
    They are different problems with different fixes: an undated source needs a
    date recorded, a stale one needs replacing.
    """
    horizon = staleness_horizon_days(claim_kind, half_lives)
    parsed, _ = parse_date(row.get('date'))
    if parsed is None:
        state, age_days = 'undated', None
    else:
        reference = now or datetime.now(timezone.utc)
        age_days = (reference - parsed).total_seconds() / 86400.0
        state = 'stale' if age_days > horizon else 'current'
    return {
        'url': row.get('url', ''),
        'kind': row.get('kind', ''),
        'angle': row.get('angle', ''),
        'state': state,
        'age_days': None if age_days is None else round(age_days, 1),
        'horizon_days': horizon,
    }


def freshness_audit(rows, claim_kind, half_lives=DEFAULT_STALE_HALF_LIVES, now=None):
    """Split a whole log into current, stale and undated for one claim kind."""
    results = [freshness(row, claim_kind, half_lives=half_lives, now=now) for row in rows]
    counts = {'current': 0, 'stale': 0, 'undated': 0}
    for result in results:
        counts[result['state']] += 1
    return {
        'claim_kind': claim_kind,
        'horizon_days': staleness_horizon_days(claim_kind, half_lives),
        'sources': len(results),
        'flagged': [r for r in results if r['state'] != 'current'],
        **counts,
    }


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def resume_state(rows):
    """What a previous run already paid for, so a re-run can skip it.

    A deep run that dies partway has a complete log of everything it retrieved.
    Starting over refetches pages that are already recorded, which costs time and
    (on the Bright Data path) money for nothing.
    """
    # Imported here rather than at module scope: independence imports read_rows
    # from this module, so a top-level import would be circular. By call time
    # both modules are fully loaded.
    from independence import canonicalize

    angles = {}
    fetched, failed, unquoted = [], [], []
    quoted = 0
    for row in rows:
        angle = (row.get('angle') or '').strip()
        if angle:
            angles[angle] = angles.get(angle, 0) + 1
        key = canonicalize(row.get('url', ''))
        if (row.get('status') or 'ok').lower() == 'ok':
            if key not in fetched:
                fetched.append(key)
            if (row.get('quote') or '').strip():
                quoted += 1
            elif key not in unquoted:
                unquoted.append(key)
        elif key not in failed:
            failed.append(key)
    return {
        'sources': len(rows),
        'angles': angles,
        'fetched': fetched,
        'failed': failed,
        'quoted': quoted,
        'unquoted': unquoted,
    }


def retrieval_receipt(rows):
    """What the run actually retrieved, counted from the log rather than recalled.

    The receipt line under a report's title is written by hand at the end of a
    long run, which is when a model has least attention left for arithmetic.
    Measured on real runs: a report claimed sources it had only seen in a search
    result. These counts come from the file, so the two can be compared.
    """
    from independence import canonicalize

    opened, snippet_only, blocked, queries = set(), set(), set(), set()
    brightdata = set()
    for row in rows:
        key = canonicalize(row.get('url', ''))
        via = (row.get('via') or '').strip().lower()
        query = (row.get('query') or '').strip()
        if query:
            queries.add(query)
        if (row.get('status') or 'ok').lower() != 'ok':
            blocked.add(key)
            continue
        if via == SNIPPET_VIA:
            snippet_only.add(key)
        else:
            opened.add(key)
        if via == 'brightdata':
            brightdata.add(key)
    return {
        'sources': len(rows),
        'opened': len(opened),
        # A page opened later stops being snippet-only, however it was first seen.
        'snippet_only': len(snippet_only - opened),
        'brightdata': len(brightdata),
        'blocked': len(blocked - opened),
        'queries': len(queries),
    }


def receipt_line(receipt):
    """The retrieval half of a report's receipt line, ready to paste."""
    return '{sources} sources \u00b7 {opened} opened \u00b7 {snippet_only} snippet-only \u00b7 ' \
           '{brightdata} via Bright Data \u00b7 {blocked} blocked \u00b7 {queries} queries'.format(**receipt)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_receipt(args):
    receipt = retrieval_receipt(read_rows(args.tsv))
    if args.format == 'json':
        print(json.dumps(receipt, indent=2))
        return
    print(receipt_line(receipt))


def cmd_kinds(args):
    if args.format == 'json':
        print(json.dumps({
            'source_kinds': list(SOURCE_KINDS),
            'claim_kinds': list(CLAIM_KINDS),
            'ladders': {k: {t: list(v) for t, v in ladder.items()} for k, ladder in CLAIM_LADDERS.items()},
            'half_life_days': HALF_LIFE_DAYS,
        }, indent=2))
        return
    print('source kinds: ' + ', '.join(SOURCE_KINDS))
    print()
    for claim_kind in CLAIM_KINDS:
        ladder = CLAIM_LADDERS[claim_kind]
        print('{}  (half-life {}d)'.format(claim_kind, HALF_LIFE_DAYS[claim_kind]))
        for tier in TIERS:
            entries = ladder.get(tier, ())
            if entries:
                print('  {:<11} {}'.format(tier, ', '.join(entries)))
        print()


def _apply_sidecar(args):
    """Fill the row from the JSON fetch.py (or bd_search.py) wrote beside the page.

    Retyping a URL, a title and a date that a script already has is where they
    drift, and the drift is invisible: the row looks fine and points at a
    slightly different page from the one that was read. Explicit flags still
    win, because the caller may know better than the page's own metadata.
    """
    try:
        with open(args.from_fetch, encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        print('error: cannot read --from-fetch: {}'.format(exc), file=sys.stderr)
        sys.exit(2)

    args.url = args.url or payload.get('canonical') or payload.get('url') or ''
    args.title = args.title or payload.get('title') or ''
    args.date = args.date or payload.get('date') or ''
    args.query = args.query or payload.get('query') or ''
    if not args.text_file and payload.get('text_file') and os.path.exists(payload['text_file']):
        args.text_file = payload['text_file']
    if not args.via:
        args.via = 'brightdata' if payload.get('provider') == 'brightdata' else 'direct'
    verdict = (payload.get('verdict') or 'ok').lower()
    if verdict != 'ok' and args.status == 'ok':
        # A page that would not open is evidence about the run, not about the
        # claim. Recording it is what makes the receipt's blocked count real.
        args.status = verdict
    return args


def cmd_log(args):
    if args.from_fetch:
        args = _apply_sidecar(args)
    if not args.url:
        print('error: --url is required unless --from-fetch supplies one', file=sys.stderr)
        sys.exit(2)
    if not args.via:
        print('error: --via is required unless --from-fetch supplies one', file=sys.stderr)
        sys.exit(2)
    kind = args.kind or infer_source_kind(args.url, args.title or '')
    if kind not in SOURCE_KINDS:
        print('error: unknown source kind {!r}; one of: {}'.format(kind, ', '.join(SOURCE_KINDS)), file=sys.stderr)
        sys.exit(2)
    if args.via not in VIA_VALUES:
        print('error: --via must be one of: {}'.format(', '.join(VIA_VALUES)), file=sys.stderr)
        sys.exit(2)

    page_text = None
    if args.text_file:
        try:
            with open(args.text_file, encoding='utf-8', errors='replace') as handle:
                page_text = handle.read()
        except OSError as exc:
            print('error: cannot read --text-file: {}'.format(exc), file=sys.stderr)
            sys.exit(2)

    quote = (args.quote or '')[:MAX_QUOTE_CHARS]
    numbers, numbers_from = numbers_for_row(args.numbers, page_text, quote)

    # None means "could not be checked" - no page text was supplied - which is a
    # different thing from a quote that was checked and is not on the page.
    verified = None
    if page_text is not None and quote:
        verified = quote_appears_in(quote, page_text)
        if not verified:
            print('warning: the quote was not found in the page text; re-take it from the page',
                  file=sys.stderr)

    append_row(args.tsv, {
        'url': args.url,
        'kind': kind,
        'angle': args.angle,
        'via': args.via,
        'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': args.status,
        'date': args.date or '',
        'numbers': ','.join(numbers),
        'title': args.title or '',
        'quote': quote,
        'query': args.query or '',
    })
    print(json.dumps({'status': 'logged', 'url': args.url, 'kind': kind,
                      'numbers': len(numbers), 'numbers_from': numbers_from,
                      'quoted': bool(quote), 'quote_verified': verified}))


def cmd_score(args):
    rows = read_rows(args.tsv)
    if not rows:
        print('error: no rows in {}'.format(args.tsv), file=sys.stderr)
        sys.exit(1)
    scored = []
    for row in rows:
        result = fitness(row.get('kind') or 'unknown', args.claim_kind, row.get('date'))
        result['url'] = row.get('url', '')
        result['angle'] = row.get('angle', '')
        scored.append(result)
    scored.sort(key=lambda r: r['score'], reverse=True)

    if args.format == 'json':
        print(json.dumps(scored, indent=2))
        return
    print('{:>6}  {:<11} {:<20} {}'.format('SCORE', 'TIER', 'KIND', 'URL'))
    for result in scored:
        print('{:>6.1f}  {:<11} {:<20} {}'.format(
            result['score'], result['tier'], result['source_kind'], result['url'][:70]))


def cmd_stale(args):
    rows = read_rows(args.tsv)
    if not rows:
        print('error: no rows in {}'.format(args.tsv), file=sys.stderr)
        sys.exit(1)
    result = freshness_audit(rows, args.claim_kind, half_lives=args.half_lives)
    if args.format == 'json':
        print(json.dumps(result, indent=2))
    else:
        print('{} sources against a {}-day horizon for {!r} claims: '
              '{} current, {} stale, {} undated'.format(
                  result['sources'], result['horizon_days'], result['claim_kind'],
                  result['current'], result['stale'], result['undated']))
        for entry in result['flagged']:
            age = 'undated' if entry['age_days'] is None else '{:.0f}d old'.format(entry['age_days'])
            print('  {:<8} {:<12} {}'.format(entry['state'], age, entry['url'][:70]))
    sys.exit(0 if not result['flagged'] else 1)


def cmd_resume(args):
    state = resume_state(read_rows(args.tsv))
    if args.format == 'json':
        print(json.dumps(state, indent=2))
        return
    print('{} retrievals already logged: {} distinct pages fetched, {} failed, {} carry a quote'.format(
        state['sources'], len(state['fetched']), len(state['failed']), state['quoted']))
    if state['angles']:
        print('\nangles already worked:')
        for angle, count in sorted(state['angles'].items(), key=lambda kv: -kv[1]):
            print('  {:>3}  {}'.format(count, angle))
    if state['unquoted']:
        print('\nfetched but carrying no quote (the gate will not accept these as evidence):')
        for url in state['unquoted']:
            print('  {}'.format(url[:88]))
    if state['failed']:
        print('\nfailed, worth retrying:')
        for url in state['failed']:
            print('  {}'.format(url[:88]))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='sources', description=__doc__.split('\n')[1])
    sub = parser.add_subparsers(dest='command', required=True)

    p_kinds = sub.add_parser('kinds', help='Print the claim-kind ladders')
    p_kinds.add_argument('--format', default='table', choices=['table', 'json'])

    p_log = sub.add_parser('log', help='Append one retrieval to the fetch log')
    p_log.add_argument('--tsv', required=True)
    p_log.add_argument('--url', default='', help='Required unless --from-fetch supplies one')
    p_log.add_argument('--kind', default=None, help='Source kind; inferred from the URL when omitted')
    p_log.add_argument('--angle', required=True, help='The sub-question this retrieval was answering')
    p_log.add_argument('--via', default='', choices=[''] + list(VIA_VALUES),
                       help='Required unless --from-fetch supplies one')
    p_log.add_argument('--status', default='ok')
    p_log.add_argument('--quote', default='',
                       help='The sentence that made this source worth citing, verbatim. '
                            'Truncated at {} characters.'.format(MAX_QUOTE_CHARS))
    p_log.add_argument('--title', default='')
    p_log.add_argument('--date', default='', help='Publication date of the source, ISO-8601')
    p_log.add_argument('--text-file', default=None, help='File of fetched page text; numeric tokens are extracted')
    p_log.add_argument('--numbers', default='', help='Comma-separated numeric tokens, if extracted elsewhere')
    p_log.add_argument('--from-fetch', default=None, dest='from_fetch', metavar='PATH.json',
                       help='Sidecar JSON from fetch.py or bd_search.py; fills url, title, date and text')
    p_log.add_argument('--query', default='',
                       help='The search query or endpoint call that surfaced this source')

    p_receipt = sub.add_parser('receipt', help='Counts for the receipt line, taken from the log')
    p_receipt.add_argument('--tsv', required=True)
    p_receipt.add_argument('--format', default='line', choices=['line', 'json'])

    p_score = sub.add_parser('score', help='Score logged sources against a claim kind')
    p_score.add_argument('--tsv', required=True)
    p_score.add_argument('--claim-kind', required=True, choices=list(CLAIM_KINDS))
    p_score.add_argument('--format', default='table', choices=['table', 'json'])

    p_stale = sub.add_parser('stale', help='Flag logged sources that have gone off for a claim kind')
    p_stale.add_argument('--tsv', required=True)
    p_stale.add_argument('--claim-kind', required=True, choices=list(CLAIM_KINDS))
    p_stale.add_argument('--half-lives', type=float, default=DEFAULT_STALE_HALF_LIVES,
                         help='Staleness horizon, in half-lives of the claim kind (default 2)')
    p_stale.add_argument('--format', default='table', choices=['table', 'json'])

    p_resume = sub.add_parser('resume', help='Summarise an existing fetch log so a re-run can skip it')
    p_resume.add_argument('--tsv', required=True)
    p_resume.add_argument('--format', default='table', choices=['table', 'json'])

    args = parser.parse_args(argv)
    {'kinds': cmd_kinds, 'log': cmd_log, 'receipt': cmd_receipt, 'score': cmd_score,
     'stale': cmd_stale, 'resume': cmd_resume}[args.command](args)


# Tests drive the CLI through this rather than through a subprocess, so a bug in
# argument handling fails a test rather than passing one that only exercised the
# functions underneath it.
main_with_args = main


if __name__ == '__main__':
    main()
