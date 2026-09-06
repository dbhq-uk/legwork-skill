#!/usr/bin/env python3
"""
fetch.py - open one page from this machine and keep its text.

    fetch.py URL [--find TERM ...] [--out PATH] [--json]

The free rung of the page ladder, and the only one that yields page *text*.
`WebFetch` returns a model's summary of a page, which is why - measured across
seven real fetch logs on 2026-09-06, 215 rows - the numeric tokens column was
filled on exactly one row and the gate's figure tracing was proved by fixtures
while dead in production. Text on disk restores it: figures trace, quotes can
be checked against the page they claim to come from, and the publication date
is read rather than guessed.

Exit codes tell the caller which rung to try next:

    0  text written; log it
    1  network or parse error            -> WebFetch
    3  blocked, missing, or a shell     -> WebFetch, then bd_search.py -m scrape,
                                           then -m render for a client-rendered page
    4  content type this cannot read    -> WebFetch
    5  address refused by policy        -> nothing; do not fetch it by any route

Stdlib only. Runs on any python3 >= 3.9. No cookies are sent or stored, no
credentials are read, and no JavaScript is executed. robots.txt is not
consulted: this opens a single page on explicit instruction, as a browser
would. That is a policy choice and SECURITY.md states it.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import zlib
from datetime import date
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen  # noqa: F401 - urlopen is patched in tests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sources import extract_numbers  # noqa: E402

USER_AGENT = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/124.0 Safari/537.36 legwork-research/1.0 '
              '(+https://github.com/dbhq-uk/legwork-skill)')
DEFAULT_TIMEOUT = 30

# Elements whose text is furniture rather than content. Dropping them is what
# turns a page into the sentence you are looking for instead of its navigation.
DROP_ELEMENTS = frozenset((
    'script', 'style', 'noscript', 'svg', 'nav', 'header', 'footer', 'aside',
    'form', 'template', 'iframe', 'button', 'select', 'canvas',
))
BLOCK_ELEMENTS = frozenset((
    'p', 'div', 'br', 'li', 'tr', 'td', 'th', 'section', 'article', 'h1', 'h2',
    'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre', 'dt', 'dd', 'figcaption',
))

# Below this a page has a shell and no body. A real page with something worth
# citing on it clears 400 characters comfortably.
MIN_BODY_CHARS = 400
# Above this share of text sitting inside anchors, what came back is a link
# list: a client-rendered page's fallback, or an index rather than the article.
MAX_LINK_DENSITY = 0.6
BLOCKED_STATUSES = frozenset((401, 402, 403, 407, 429, 451, 503))
# A 404 or a 500 usually still has a body, and a branded error page carries
# plenty of text. Without this, "Sorry, we couldn't find that" repeated across a
# templated 404 clears the body-length test and gets logged as an opened source.
MISSING_STATUSES = frozenset((404, 410))
CHALLENGE_MARKERS = (
    'just a moment', 'enable javascript and cookies', 'checking your browser',
    'verify you are human', 'attention required! | cloudflare', 'access denied',
    'ddos protection by', 'please enable js', 'captcha',
)
MAX_BYTES = 5 * 1024 * 1024
# The cap on the wire covers the compressed body only. This one covers what it
# expands to, which is the number that matters when a server answers with a
# highly compressible payload.
MAX_DECOMPRESSED = 20 * 1024 * 1024


class _Extractor(HTMLParser):
    """HTML to readable text, keeping block boundaries and dropping furniture."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.anchor_chars = 0
        self._drop_depth = 0
        self._anchor_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_ELEMENTS:
            self._drop_depth += 1
        elif tag == 'a':
            self._anchor_depth += 1
        if tag in BLOCK_ELEMENTS:
            self.parts.append('\n')

    def handle_startendtag(self, tag, attrs):
        if tag in BLOCK_ELEMENTS:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in DROP_ELEMENTS and self._drop_depth:
            self._drop_depth -= 1
        elif tag == 'a' and self._anchor_depth:
            self._anchor_depth -= 1
        if tag in BLOCK_ELEMENTS:
            self.parts.append('\n')

    def handle_data(self, data):
        if self._drop_depth:
            return
        self.parts.append(data)
        if self._anchor_depth:
            self.anchor_chars += len(data.strip())


def _tidy(text):
    text = re.sub(r'[ \t\r\f\v]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def html_to_text(markup):
    """Readable text from HTML, with block breaks kept and furniture dropped."""
    parser = _Extractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup is normal on the open web
        pass
    return _tidy(''.join(parser.parts))


def link_density(markup):
    """Share of the text sitting inside anchors. High means a link list."""
    parser = _Extractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # noqa: BLE001
        pass
    total = len(_tidy(''.join(parser.parts)))
    return (parser.anchor_chars / total) if total else 0.0


_META_RE = re.compile(r'<meta\b[^>]*>', re.I)
_ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*("([^"]*)"|\'([^\']*)\'|([^\s>]+))')
_TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.I | re.S)
_TIME_RE = re.compile(r'<time\b[^>]*\bdatetime\s*=\s*["\']([^"\']+)', re.I)
_JSONLD_DATE_RE = re.compile(r'"(?:datePublished|dateModified|uploadDate)"\s*:\s*"([^"]+)"')
_CANONICAL_RE = re.compile(r'<link\b[^>]*\brel\s*=\s*["\']?canonical["\']?[^>]*>', re.I)
_HREF_RE = re.compile(r'\bhref\s*=\s*("([^"]*)"|\'([^\']*)\'|([^\s>]+))', re.I)

DATE_META_KEYS = (
    'article:published_time', 'article:modified_time', 'og:updated_time',
    'datepublished', 'date', 'dc.date', 'dc.date.issued', 'pubdate',
    'publish-date', 'sailthru.date', 'parsely-pub-date',
)
_ISO_DATE_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
_MONTHS = ('january', 'february', 'march', 'april', 'may', 'june', 'july',
           'august', 'september', 'october', 'november', 'december')
_TEXT_DATE_RE = re.compile(
    r'\b(\d{1,2})\s+(' + '|'.join(_MONTHS) + r')\s+(\d{4})\b|\b(' + '|'.join(_MONTHS) +
    r')\s+(\d{1,2}),?\s+(\d{4})\b', re.I)


def _valid_date(year, month, day):
    """A date string, or '' if those numbers are not a real date.

    A page is free to carry 2026-02-31. Passing it through gives every check
    downstream a date-shaped value that is not a date, and the age check reads
    "has a date" from it. Better to record nothing.
    """
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return ''


def normalise_date(value):
    """Any of the forms a page states a date in, as YYYY-MM-DD. Never guessed."""
    if not value:
        return ''
    value = html.unescape(str(value)).strip()
    match = _ISO_DATE_RE.search(value)
    if match:
        return _valid_date(*match.groups())
    match = _TEXT_DATE_RE.search(value)
    if match:
        day, month, year = (match.group(1), match.group(2), match.group(3)) if match.group(1) \
            else (match.group(5), match.group(4), match.group(6))
        return _valid_date(year, _MONTHS.index(month.lower()) + 1, day)
    # RFC 1123, as an HTTP Last-Modified header states it.
    match = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})', value)
    if match and match.group(2).lower() in [m[:3] for m in _MONTHS]:
        month = [m[:3] for m in _MONTHS].index(match.group(2).lower()) + 1
        return _valid_date(match.group(3), month, match.group(1))
    return ''


def _meta_pairs(markup):
    for tag in _META_RE.findall(markup or ''):
        attrs = {}
        for match in _ATTR_RE.finditer(tag):
            value = match.group(3) or match.group(4) or match.group(5) or ''
            attrs[match.group(1).lower()] = html.unescape(value)
        key = (attrs.get('property') or attrs.get('name') or attrs.get('itemprop') or '').lower()
        if key:
            yield key, attrs.get('content', '')


def extract_meta(markup, headers=None):
    """Title, publication date and canonical URL, from the page's own metadata.

    A date that is absent stays absent. A source with no date is not necessarily
    old, but nobody can tell, and the gate says so - guessing here would defeat
    that check rather than satisfy it.
    """
    markup = markup or ''
    # First occurrence wins. dict() keeps the last, so a page carrying its
    # publication date and then a later duplicate of the same key reported the
    # duplicate - which on a syndicated page is usually the scrape date.
    meta = {}
    for key, content in _meta_pairs(markup):
        meta.setdefault(key, content)

    title = meta.get('og:title') or meta.get('twitter:title') or ''
    if not title:
        found = _TITLE_RE.search(markup)
        title = html.unescape(found.group(1)) if found else ''
    title = re.sub(r'\s+', ' ', title).strip()

    date = ''
    for key in DATE_META_KEYS:
        if meta.get(key):
            date = normalise_date(meta[key])
            if date:
                break
    if not date:
        found = _JSONLD_DATE_RE.search(markup)
        date = normalise_date(found.group(1)) if found else ''
    if not date:
        found = _TIME_RE.search(markup)
        date = normalise_date(found.group(1)) if found else ''
    # Last-Modified is deliberately NOT used as the publication date. Measured
    # on a live vendor page on 2026-09-06: a dynamically rendered page returned
    # today's date in that header, which would have recorded a page of unknown
    # age as published today and defeated the staleness check it feeds. It is
    # reported separately so a reader can judge it.

    canonical = ''
    found = _CANONICAL_RE.search(markup)
    if found:
        href = _HREF_RE.search(found.group(0))
        if href:
            canonical = html.unescape(href.group(2) or href.group(3) or href.group(4) or '')

    last_modified = normalise_date((headers or {}).get('Last-Modified') or '')
    return {'title': title, 'date': date, 'canonical': canonical,
            'last_modified': last_modified}


def classify(text, status, markup=''):
    """ok, blocked, missing or shell - and the reason, so the caller knows the next rung.

    Any status outside the 2xx range is a failure, whatever the body says. The
    body-length test cannot stand in for this: a templated 404 or a 500 error
    page is often longer than the terse pricing page next to it, so a status
    check that only listed the blocking codes let "page not found" through as
    an opened source.
    """
    if status in BLOCKED_STATUSES:
        return 'blocked', 'HTTP {}'.format(status)
    if status in MISSING_STATUSES:
        return 'missing', 'HTTP {} - the page is not there'.format(status)
    if not 200 <= status < 300:
        return 'blocked', 'HTTP {}'.format(status)
    lowered = (text or '')[:4000].lower()
    for marker in CHALLENGE_MARKERS:
        if marker in lowered:
            return 'blocked', 'challenge page: {!r}'.format(marker)
    if len(text or '') < MIN_BODY_CHARS:
        return 'shell', 'only {} characters of text'.format(len(text or ''))
    if markup and link_density(markup) > MAX_LINK_DENSITY:
        return 'shell', 'most of the text is inside links'
    return 'ok', ''


def find_windows(text, terms, window=300, max_hits=5):
    """Passages around each term, so a long page yields its sentence cheaply.

    This is what replaces truncating a page to its first N characters, which on
    a long page reliably returns the navigation and none of the content.
    """
    passages = []
    if not text or not terms:
        return passages
    lowered = text.lower()
    for term in terms:
        needle = (term or '').strip().lower()
        if not needle:
            continue
        start, hits = 0, 0
        while hits < max_hits:
            at = lowered.find(needle, start)
            if at < 0:
                break
            left = max(0, at - window)
            right = min(len(text), at + len(needle) + window)
            passage = text[left:at] + '>>>' + text[at:at + len(needle)] + '<<<' + text[at + len(needle):right]
            passages.append(re.sub(r'\s+', ' ', passage).strip())
            start = at + len(needle)
            hits += 1
    return passages


def _decompress(raw, encoding):
    """Bounded decompression.

    The byte cap on the wire is a cap on the *compressed* body, which is no cap
    at all: a few hundred kilobytes of gzip expands to gigabytes. Decompressing
    incrementally and stopping at MAX_DECOMPRESSED is the difference between
    reading a page and being handed a bomb by a site that would rather not be
    read.
    """
    encoding = (encoding or '').lower()
    if 'gzip' in encoding:
        wbits = zlib.MAX_WBITS | 16
    elif 'deflate' in encoding:
        wbits = -zlib.MAX_WBITS
    else:
        return raw
    try:
        return zlib.decompressobj(wbits).decompress(raw, MAX_DECOMPRESSED)
    except (OSError, zlib.error):
        return raw


class BlockedAddress(Exception):
    """The URL resolves somewhere a research tool has no business going."""


def _is_public(host):
    """Does this hostname resolve only to public addresses?

    Every address the name resolves to is checked, not just the first: a name
    with one public and one loopback record would otherwise pass here and
    connect to the loopback one.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return False
        if (parsed.is_private or parsed.is_loopback or parsed.is_link_local
                or parsed.is_multicast or parsed.is_reserved or parsed.is_unspecified):
            return False
    return True


def _check_target(url):
    """Raise unless this URL is http(s) to a public host."""
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https'):
        raise BlockedAddress('refusing scheme {!r}: only http and https'.format(parts.scheme))
    if not parts.hostname:
        raise BlockedAddress('no host in URL')
    if not _is_public(parts.hostname):
        raise BlockedAddress(
            'refusing {}: resolves to a private, loopback or link-local address'.format(parts.hostname))


class _ValidatingRedirectHandler(HTTPRedirectHandler):
    """Check every hop, not just the one the caller typed.

    Validating only the first URL is no protection at all. A public page is
    free to answer 302 to http://169.254.169.254/ or to a host on the machine's
    own network, and the research question came off the open web, so the URL
    being followed is not something the user vouched for.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_target(newurl)
        return HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


_OPENER = build_opener(_ValidatingRedirectHandler)

# Every request in this module goes through the validating opener. The name is
# rebound rather than called directly so there is exactly one seam: production
# gets redirect validation, and a test patching `fetch.urlopen` still replaces
# the whole transport.
urlopen = _OPENER.open


def fetch(url, timeout=DEFAULT_TIMEOUT):
    """(status, headers, body_bytes, final_url). HTTP errors return their body.

    Raises BlockedAddress if the URL, or anything it redirects to, points at a
    private, loopback or link-local address.
    """
    _check_target(url)
    request = Request(url, headers={
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-GB,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
    })
    try:
        response = urlopen(request, timeout=timeout)  # noqa: S310 - validated above and per redirect
    except HTTPError as exc:
        body = exc.read(MAX_BYTES) if hasattr(exc, 'read') else b''
        return exc.code, dict(exc.headers or {}), _decompress(body, (exc.headers or {}).get('Content-Encoding')), url
    with response:
        headers = dict(response.headers or {})
        body = response.read(MAX_BYTES)
        return (getattr(response, 'status', 200) or 200, headers,
                _decompress(body, headers.get('Content-Encoding')), response.geturl())


def _decode(body, headers):
    charset = ''
    match = re.search(r'charset=([\w-]+)', headers.get('Content-Type', ''), re.I)
    if match:
        charset = match.group(1)
    for candidate in (charset, 'utf-8', 'latin-1'):
        if candidate:
            try:
                return body.decode(candidate)
            except (LookupError, UnicodeDecodeError):
                continue
    return body.decode('utf-8', errors='replace')


def scratch_dir():
    """Where page text goes for the life of one run.

    Namespaced by LEGWORK_RUN_ID if the caller sets one, else by process. A
    plain hash of the URL under a shared directory looked tidy and was not: a
    later run fetching the same URL would find last week's text sitting there,
    and a fetch that failed today would hand `log --from-fetch` a sidecar
    written when the page still worked. Nothing here is read back across runs.
    """
    run = os.environ.get('LEGWORK_RUN_ID') or str(os.getpid())
    folder = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'legwork', run)
    os.makedirs(folder, exist_ok=True)
    return folder


def default_out_path(url):
    digest = hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]  # noqa: S324 - a filename, not a signature
    return os.path.join(scratch_dir(), digest + '.txt')


def write_outputs(out_path, text, payload):
    """Text beside its sidecar JSON. Scratch, never the run folder.

    The fetch log stores the quote and the numeric tokens, not the page. Keeping
    page text out of the output directory is what keeps that true.
    """
    with open(out_path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    sidecar = os.path.splitext(out_path)[0] + '.json'
    with open(sidecar, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return sidecar


def _fail(payload, code):
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    sys.exit(code)


def _pdf_to_text(body, url):
    binary = shutil.which('pdftotext')
    if not binary:
        _fail({'url': url, 'verdict': 'unsupported', 'reason':
               'PDF, and pdftotext is not on PATH; use WebFetch'}, 4)
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as handle:
        handle.write(body)
        source = handle.name
    try:
        proc = subprocess.run([binary, '-q', source, '-'], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _fail({'url': url, 'verdict': 'unsupported', 'reason': 'pdftotext failed: {}'.format(exc)}, 4)
    finally:
        os.unlink(source)
    return _tidy(proc.stdout)


def main():
    parser = argparse.ArgumentParser(prog='fetch.py', description=__doc__.split('\n')[1])
    parser.add_argument('url')
    parser.add_argument('--find', action='append', default=[], metavar='TERM',
                        help='Repeatable. Print the passages around each term rather than the page.')
    parser.add_argument('--window', type=int, default=300, help='Characters either side of a --find hit')
    parser.add_argument('--max-hits', type=int, default=5, help='Passages per term')
    parser.add_argument('--out', default=None, help='Where to write the page text')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument('--json', action='store_true', help='Accepted for compat; output is always JSON')
    args = parser.parse_args()

    if not args.url.startswith(('http://', 'https://')):
        _fail({'url': args.url, 'verdict': 'error', 'reason': 'not an http(s) URL'}, 1)

    try:
        status, headers, body, final_url = fetch(args.url, timeout=args.timeout)
    except BlockedAddress as exc:
        # Its own exit code: this is not "the page would not open, try the next
        # rung", it is "this address is not a research source". Escalating to a
        # paid scrape would be the wrong response and would spend money doing it.
        _fail({'url': args.url, 'verdict': 'refused', 'reason': str(exc),
               'next': 'nothing - do not fetch this address by any route'}, 5)
    except (URLError, OSError, ValueError) as exc:
        _fail({'url': args.url, 'verdict': 'error', 'reason': str(exc)}, 1)

    content_type = (headers.get('Content-Type') or '').split(';')[0].strip().lower()
    markup = ''
    if content_type == 'application/pdf' or args.url.lower().endswith('.pdf'):
        text = _pdf_to_text(body, args.url)
        meta = extract_meta('', headers)
    elif content_type in ('text/plain', 'text/markdown', 'application/json', 'text/csv'):
        text = _tidy(_decode(body, headers))
        meta = extract_meta('', headers)
    elif content_type.startswith('text/') or content_type in (
            'application/xhtml+xml', 'application/xml', 'application/rss+xml', ''):
        markup = _decode(body, headers)
        text = html_to_text(markup)
        meta = extract_meta(markup, headers)
    else:
        _fail({'url': args.url, 'verdict': 'unsupported',
               'reason': 'content type {!r}; use WebFetch'.format(content_type)}, 4)

    verdict, reason = classify(text, status, markup)
    out_path = args.out or default_out_path(args.url)
    payload = {
        'url': args.url,
        'final_url': final_url,
        'http_status': status,
        'content_type': content_type,
        'title': meta['title'],
        'date': meta['date'],
        'last_modified': meta['last_modified'],
        'canonical': meta['canonical'],
        'chars': len(text),
        'text_file': out_path,
        'numbers': len(extract_numbers(text)),
        'verdict': verdict,
        'reason': reason,
        'find': find_windows(text, args.find, args.window, args.max_hits) if args.find else [],
    }

    if verdict != 'ok':
        payload['next'] = ('WebFetch, then bd_search.py -m scrape' if verdict == 'blocked'
                           else 'WebFetch, then bd_search.py -m render')
        # The sidecar is written for a failure too. The skill's own instruction
        # is to log the failed attempt before falling back, and that is done
        # with `sources.py log --from-fetch`, which needs a file to read. Its
        # verdict field carries the failure through, so the row lands with a
        # non-ok status rather than looking like a page that was read.
        write_outputs(out_path, text, payload)
        _fail(payload, 3)

    write_outputs(out_path, text, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
