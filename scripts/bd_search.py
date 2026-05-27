#!/usr/bin/env python3
"""
bd_search.py - Bright Data backend for the deep-research skill.

Shells out to the official Bright Data CLI (`brightdata` / `bdata`,
package `@brightdata/cli`). Preserves the historical invocation surface so
the rest of the skill doesn't need to change:

    bd_search.py "query" --json -c 10 [-m MODE]

Search modes (general/news/images, plus aliases scholar/academic/patents/people
which the CLI doesn't support natively and so fall through to web search) call
`brightdata search`. Content modes (extract/scrape) + a URL call
`brightdata scrape -f markdown`. Output is always JSON on stdout; errors go to
stderr with a non-zero exit so the skill falls back to built-in WebSearch.

Authentication is handled entirely by the CLI itself (run `brightdata login`,
or set `BRIGHTDATA_API_KEY`). This wrapper does not read or write any
credentials of its own.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

SERP_MODES = {"general", "news", "academic", "scholar", "patents", "people", "images"}
CONTENT_MODES = {"extract", "scrape"}
TIMEOUT = 90
SETUP_HINT = "Run `brightdata login` (or set BRIGHTDATA_API_KEY) to authenticate."
# Bright Data CLI exits 1 for every error. Map known auth/quota messages onto
# exit code 2 so the skill's "credentials are bad, tell the user" branch fires.
EXIT_AUTH = 2
AUTH_ERROR_SUBSTRINGS = (
    "Invalid or expired API key",
    "No API key",
    "not authenticated",
    "Authentication failed",
    "Access denied",
    "Rate limit exceeded",
    "quota",
    "balance",
    "No Web Unlocker zone",
    "No SERP zone",
)

# Map our historical -m mode to the CLI's --type. Modes the CLI doesn't model
# natively (scholar, academic, patents, people) fall through to web search;
# the downstream re-ranker handles credibility scoring either way.
_TYPE_FOR_MODE = {
    "general": "web",
    "news": "news",
    "images": "images",
    "scholar": "web",
    "academic": "web",
    "patents": "web",
    "people": "web",
}


def _fail(msg: str, code: int = 1) -> None:
    """Emit a JSON error to stderr and exit non-zero (triggers skill fallback)."""
    print(json.dumps({"provider": "brightdata", "error": msg}), file=sys.stderr)
    sys.exit(code)


def _cli_bin() -> str:
    for name in ("brightdata", "bdata"):
        path = shutil.which(name)
        if path:
            return path
    _fail(
        "Bright Data CLI not found on PATH. Install with: npm install -g @brightdata/cli",
        code=EXIT_AUTH,
    )


def _classify_exit(stderr: str) -> int:
    """Return EXIT_AUTH if stderr looks like an auth/quota failure, else 1."""
    s = stderr.lower()
    return EXIT_AUTH if any(sub.lower() in s for sub in AUTH_ERROR_SUBSTRINGS) else 1


def _run(cmd: list[str]) -> str:
    """Run the CLI and return stdout. On failure, _fail() with a useful code."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _fail(f"Bright Data CLI timed out after {TIMEOUT}s")
    except OSError as e:
        _fail(f"failed to invoke Bright Data CLI: {e}")
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        code = _classify_exit(msg)
        hint = f" {SETUP_HINT}" if code == EXIT_AUTH else ""
        _fail(f"Bright Data CLI failed: {msg[:400]}{hint}", code=code)
    return proc.stdout


def _normalize_serp(parsed: dict, count: int) -> list[dict]:
    """Map Bright Data parsed SERP JSON to the skill's loose source shape.

    Defensive across verticals: organic web results live under 'organic';
    news verticals may use 'news'. Field names ('link'/'url',
    'description'/'snippet') also vary, so we accept either.
    """
    items = parsed.get("organic") or parsed.get("news") or parsed.get("organic_results") or []
    results = []
    for i, item in enumerate(items[:count], start=1):
        results.append(
            {
                "rank": item.get("rank", i),
                "title": item.get("title") or item.get("name") or "",
                "url": item.get("link") or item.get("url") or "",
                "snippet": item.get("description") or item.get("snippet") or "",
                # date is best-effort. source_evaluator defaults to recency=50 when null.
                "date": item.get("date") or item.get("published") or None,
                "source_type": "web",
            }
        )
    return results


def run_serp(args) -> None:
    cli = _cli_bin()
    cmd = [
        cli, "search", args.query,
        "--type", _TYPE_FOR_MODE.get(args.mode, "web"),
        "--json",
    ]
    if args.country:
        cmd.extend(["--country", args.country])
    if args.zone:
        cmd.extend(["--zone", args.zone])
    raw = _run(cmd)
    try:
        parsed = json.loads(raw)
    except ValueError:
        _fail(f"SERP response was not JSON: {raw[:300]}")
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
    cli = _cli_bin()
    cmd = [cli, "scrape", target, "-f", "markdown"]
    if args.country:
        cmd.extend(["--country", args.country])
    if args.zone:
        cmd.extend(["--zone", args.zone])
    body = _run(cmd)
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
    p = argparse.ArgumentParser(prog="bd_search.py", add_help=True)
    p.add_argument("query", help="search query, or URL for extract/scrape modes")
    p.add_argument("-m", "--mode", default="general")
    p.add_argument("-c", "--count", type=int, default=10)
    p.add_argument("--json", action="store_true", help="accepted for compat; output is always JSON")
    p.add_argument("--country", default=os.environ.get("BD_COUNTRY"))
    p.add_argument("--max-chars", type=int, default=20000, help="truncate scraped content")
    p.add_argument(
        "--zone",
        default=os.environ.get("BD_SERP_ZONE") or os.environ.get("BD_UNLOCKER_ZONE"),
        help="override the CLI's default zone for SERP or scrape calls",
    )
    args = p.parse_args()

    if args.mode in CONTENT_MODES:
        run_content(args)
    elif args.mode in SERP_MODES:
        run_serp(args)
    else:
        _fail(f"unknown mode: {args.mode}")


if __name__ == "__main__":
    main()
