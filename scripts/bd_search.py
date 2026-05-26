#!/usr/bin/env python3
"""
bd_search.py - Bright Data backend for the deep-research skill.

Drop-in replacement for the `search-cli` binary the skill called via
Bash. Emulates the same invocation surface:

    bd_search.py "query" --json -c 10 [-m MODE]

Search modes (general/news/academic/scholar/patents/people/images) go to the
Bright Data SERP API. Content modes (extract/scrape) + a URL go to the
Bright Data Web Unlocker. Output is always JSON on stdout; errors go to
stderr with a non-zero exit so the skill cleanly falls back to built-in
WebSearch.

Credentials are read from environment variables, falling back to
~/.deep-research/config.env (simple KEY=VALUE lines):

    BRIGHTDATA_API_TOKEN   Bright Data API token (Bearer)
    BD_SERP_ZONE           name of your SERP API zone
    BD_UNLOCKER_ZONE       name of your Web Unlocker zone
    BD_COUNTRY             optional default country code for SERP gl=

Run via the skill's venv:

    ~/.claude/skills/deep-research/.venv/bin/python \\
        ~/.claude/skills/deep-research/scripts/bd_search.py "query" --json
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

import requests

API_ENDPOINT = "https://api.brightdata.com/request"
SERP_MODES = {"general", "news", "academic", "scholar", "patents", "people", "images"}
CONTENT_MODES = {"extract", "scrape"}
TIMEOUT = 60
CONFIG_PATH = Path.home() / ".deep-research" / "config.env"
SETUP_HINT = "Re-run ~/.claude/skills/deep-research/setup.sh --reset to update credentials."
# HTTP statuses that indicate auth/quota problems (token revoked, zone deleted, balance hit, etc.).
AUTH_STATUSES = {401, 402, 403}
EXIT_AUTH = 2  # Wrapper exit code for auth/quota failures, distinct from generic failure (1).

# Google SERP "tbm" tab per mode (None = standard web results).
_TBM = {"news": "nws", "images": "isch"}


def _fail(msg: str, code: int = 1) -> None:
    """Emit a JSON error to stderr and exit non-zero (triggers skill fallback)."""
    print(json.dumps({"provider": "brightdata", "error": msg}), file=sys.stderr)
    sys.exit(code)


def _load_config_env() -> None:
    """Populate os.environ from ~/.deep-research/config.env for any unset keys.

    Real environment variables always win. File format is simple KEY=VALUE
    lines; blank lines and lines starting with `#` are ignored. Surrounding
    quotes on values are stripped. Bad lines are silently skipped — the wrapper
    will fail later if a required var is still missing, with a clear message.
    """
    if not CONFIG_PATH.is_file():
        return
    try:
        for raw in CONFIG_PATH.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        # Don't crash on a malformed/unreadable config — let _token()/zone checks fail cleanly.
        pass


def _token() -> str:
    tok = os.environ.get("BRIGHTDATA_API_TOKEN")
    if not tok:
        _fail(
            f"BRIGHTDATA_API_TOKEN not set (env or ~/.deep-research/config.env). {SETUP_HINT}",
            code=EXIT_AUTH,
        )
    return tok


def _post(zone: str, url: str) -> requests.Response:
    """Single call to the unified Bright Data /request endpoint."""
    try:
        return requests.post(
            API_ENDPOINT,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_token()}",
            },
            json={"zone": zone, "url": url, "format": "raw"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        _fail(f"request failed: {e}")


def _build_google_url(query: str, mode: str, count: int, country: str | None) -> str:
    """Construct a Google search URL with brd_json=1 for parsed results."""
    params = [f"q={quote_plus(query)}", "brd_json=1", f"num={count}"]
    tbm = _TBM.get(mode)
    if tbm:
        params.append(f"tbm={tbm}")
    if mode == "scholar":
        # Google Scholar host; brd_json parsing still applies.
        base = "https://scholar.google.com/scholar"
    elif mode == "patents":
        params = [f"q={quote_plus(query)}", "brd_json=1"]
        base = "https://patents.google.com/xhr/query"
    else:
        base = "https://www.google.com/search"
    if country:
        params.append(f"gl={country}")
    return f"{base}?{'&'.join(params)}"


def _normalize_serp(parsed: dict, count: int) -> list[dict]:
    """Map Bright Data parsed SERP JSON to the skill's loose source shape.

    Defensive: the parsed payload exposes organic results under 'organic'
    (and occasionally 'organic_results'); fields vary slightly by vertical.
    """
    organic = parsed.get("organic") or parsed.get("organic_results") or []
    results = []
    for i, item in enumerate(organic[:count], start=1):
        results.append(
            {
                "rank": item.get("rank", i),
                "title": item.get("title") or item.get("name") or "",
                "url": item.get("link") or item.get("url") or "",
                "snippet": item.get("description") or item.get("snippet") or "",
                # date is best-effort; populated when Google exposes it. Feeds
                # source_evaluator recency scoring, which defaults to 50 if null.
                "date": item.get("date") or item.get("published") or None,
                "source_type": "web",
            }
        )
    return results


def run_serp(args) -> None:
    url = _build_google_url(args.query, args.mode, args.count, args.country)
    resp = _post(args.serp_zone, url)
    if resp.status_code in AUTH_STATUSES:
        _fail(
            f"SERP auth/quota failure HTTP {resp.status_code}: {resp.text[:200]}. {SETUP_HINT}",
            code=EXIT_AUTH,
        )
    if resp.status_code != 200:
        _fail(f"SERP HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        parsed = resp.json()
    except ValueError:
        _fail("SERP response was not JSON (check brd_json support on zone)")
    results = _normalize_serp(parsed, args.count)
    if not results:
        _fail("SERP returned zero organic results")
    json.dump(
        {
            "query": args.query,
            "mode": args.mode,
            "provider": "brightdata",
            "results": results,
        },
        sys.stdout,
        ensure_ascii=False,
    )
    sys.stdout.write("\n")


def run_content(args) -> None:
    target = args.query  # in content modes the positional arg is a URL
    if not target.startswith(("http://", "https://")):
        _fail(f"{args.mode} mode requires a URL, got: {target[:80]}")
    resp = _post(args.unlocker_zone, target)
    if resp.status_code in AUTH_STATUSES:
        _fail(
            f"Unlocker auth/quota failure HTTP {resp.status_code}: {resp.text[:200]}. {SETUP_HINT}",
            code=EXIT_AUTH,
        )
    if resp.status_code != 200:
        _fail(f"Unlocker HTTP {resp.status_code}: {resp.text[:300]}")
    body = resp.text
    if args.max_chars and len(body) > args.max_chars:
        body = body[: args.max_chars]
    json.dump(
        {
            "url": target,
            "mode": args.mode,
            "provider": "brightdata",
            "title": None,  # parsed downstream by the skill if needed
            "content": body,
            "date": None,
        },
        sys.stdout,
        ensure_ascii=False,
    )
    sys.stdout.write("\n")


def main() -> None:
    _load_config_env()

    p = argparse.ArgumentParser(prog="bd_search.py", add_help=True)
    p.add_argument("query", help="search query, or URL for extract/scrape modes")
    p.add_argument("-m", "--mode", default="general")
    p.add_argument("-c", "--count", type=int, default=10)
    p.add_argument("--json", action="store_true", help="accepted for compat; output is always JSON")
    p.add_argument("--country", default=os.environ.get("BD_COUNTRY"))
    p.add_argument("--max-chars", type=int, default=20000, help="truncate scraped content")
    p.add_argument("--serp-zone", default=os.environ.get("BD_SERP_ZONE"))
    p.add_argument("--unlocker-zone", default=os.environ.get("BD_UNLOCKER_ZONE"))
    args = p.parse_args()

    if args.mode in CONTENT_MODES:
        if not args.unlocker_zone:
            _fail(
                f"BD_UNLOCKER_ZONE not set (env or ~/.deep-research/config.env). {SETUP_HINT}",
                code=EXIT_AUTH,
            )
        run_content(args)
    elif args.mode in SERP_MODES:
        if not args.serp_zone:
            _fail(
                f"BD_SERP_ZONE not set (env or ~/.deep-research/config.env). {SETUP_HINT}",
                code=EXIT_AUTH,
            )
        run_serp(args)
    else:
        _fail(f"unknown mode: {args.mode}")


if __name__ == "__main__":
    main()
