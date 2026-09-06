#!/usr/bin/env python3
"""
bd_search.py - Bright Data backend for the legwork skill.

The paid rungs of both ladders, used only where the free ones cannot reach.
Shells out to the official Bright Data CLI (`brightdata` / `bdata`, package
`@brightdata/cli`, read against 0.2.0):

    bd_search.py "query" -m general --engine bing --country gb --language en
    bd_search.py "<url>"  -m scrape --find "per user" --out page.txt
    bd_search.py "<url>"  -m render                 # client-rendered pages
    bd_search.py "query"  -m discover --intent "..." # intent-ranked search
    bd_search.py "<url>"  -m pipeline --pipeline linkedin_job_listings

| Mode | CLI call | When |
|---|---|---|
| general, news, images, shopping | `brightdata search --type` | A second engine, or geo and language WebSearch cannot express |
| discover | `brightdata discover --intent` | Two engines came back thin |
| scrape | `brightdata scrape -f markdown` | fetch.py and WebFetch were both blocked |
| render | `brightdata browser open/get/close` | The page is a client-rendered shell |
| pipeline, reddit | `brightdata pipelines <name>` | A platform that blocks everything above; billed per record |

Scraped and rendered pages come back cleaned, optionally windowed around
`--find` terms, and written beside a sidecar JSON in the same shape `fetch.py`
writes, so `sources.py log --from-fetch` works on a paid fetch exactly as it
does on a free one.

Output is always JSON on stdout; errors go to stderr with a non-zero exit so
the skill falls back down the ladder.

Authentication is handled entirely by the CLI itself (run `brightdata login`,
or set `BRIGHTDATA_API_KEY`). This wrapper does not read or write any
credentials of its own.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch import default_out_path, find_windows, html_to_text, write_outputs  # noqa: E402

SERP_MODES = {"general", "news", "images", "shopping"}
CONTENT_MODES = {"extract", "scrape"}
RENDER_MODES = {"render"}
DISCOVER_MODES = {"discover"}
PIPELINE_MODES = {"reddit", "pipeline"}
# Removed on purpose: scholar, academic, patents and people. The CLI has no
# such verticals, so each silently ran an ordinary web search while letting the
# caller believe it had searched a vertical. An unusable mode that says so beats
# a usable one that lies.
RETIRED_MODES = {"scholar", "academic", "patents", "people"}
TIMEOUT_FAST = 90  # search + scrape
TIMEOUT_RENDER = 120  # a browser session: open, get, close
TIMEOUT_PIPELINE = 700  # `brightdata pipelines` polls (CLI default 600s + headroom)
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

# Our -m mode to the CLI's --type.
_TYPE_FOR_MODE = {
    "general": "web",
    "news": "news",
    "images": "images",
    "shopping": "shopping",
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


def _run(cmd: list[str], timeout: int = TIMEOUT_FAST) -> str:
    """Run the CLI and return stdout. On failure, _fail() with a useful code."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _fail(f"Bright Data CLI timed out after {timeout}s")
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
    items = (parsed.get("organic") or parsed.get("news") or parsed.get("shopping")
             or parsed.get("organic_results") or [])
    results = []
    for i, item in enumerate(items[:count], start=1):
        # A shopping row's price and seller belong in the snippet: they are the
        # part of the record worth reading, and nothing downstream models them.
        snippet = item.get("description") or item.get("snippet") or ""
        if item.get("price"):
            snippet = " ".join(x for x in (str(item.get("price")), item.get("source") or "", snippet) if x)
        results.append(
            {
                "rank": item.get("rank", i),
                "title": item.get("title") or item.get("name") or "",
                "url": item.get("link") or item.get("url") or "",
                "snippet": snippet,
                "date": item.get("date") or item.get("published") or None,
                "source_type": "web",
            }
        )
    return results


def run_serp(args) -> None:
    cli = _cli_bin()
    cmd = [
        cli,
        "search",
        args.query,
        "--type",
        _TYPE_FOR_MODE.get(args.mode, "web"),
        "--json",
    ]
    # A second engine is the point of paying at all: WebSearch is one engine
    # with no country or language control, and a UK or EU question asked of a
    # US-centric index returns a different web.
    if args.engine:
        cmd.extend(["--engine", args.engine])
    if args.language:
        cmd.extend(["--language", args.language])
    if args.page:
        cmd.extend(["--page", str(args.page)])
    if args.device:
        cmd.extend(["--device", args.device])
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
            # A paid search result is still a search result. Logging it as
            # `brightdata` would make it count as an opened page and walk
            # straight through the gate's snippet rule, so the log value is
            # stated here rather than left to the caller's judgement.
            "log_via": "serp",
            "results": results,
        },
        sys.stdout,
        ensure_ascii=False,
    )
    sys.stdout.write("\n")


def _emit_page(args, target, body) -> None:
    """Clean, window, cap, and write the sidecar fetch.py's consumers expect.

    Truncating a long page to its first N characters reliably returns the
    navigation and none of the content - measured on an eval run where two paid
    fetches came back as nav shells. Cleaning first and windowing on --find
    terms is what makes the cap safe.
    """
    text = html_to_text(body) if "<" in body[:400] else body.strip()
    passages = find_windows(text, args.find, args.window, args.max_hits) if args.find else []
    capped = text[: args.max_chars] if args.max_chars and len(text) > args.max_chars else text
    out_path = args.out or default_out_path(target)
    payload = {
        "url": target,
        "mode": args.mode,
        "provider": "brightdata",
        "log_via": "brightdata",
        "title": None,
        "date": None,
        "chars": len(text),
        "text_file": out_path,
        "verdict": "ok",
        "content": capped,
        "find": passages,
    }
    write_outputs(out_path, text, {k: v for k, v in payload.items() if k != "content"})
    json.dump(payload, sys.stdout, ensure_ascii=False)
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
    _emit_page(args, target, _run(cmd))


def run_render(args) -> None:
    """A real browser, for a page that is a shell without JavaScript.

    The session is named for the run so two subagents rendering at once do not
    share one browser and read each other's page.
    """
    target = args.query
    if not target.startswith(("http://", "https://")):
        _fail(f"render mode requires a URL, got: {target[:80]}")
    cli = _cli_bin()
    session = args.session or "legwork-{}".format(os.getpid())
    base = [cli, "browser", "--session", session]
    if args.country:
        base.extend(["--country", args.country])
    _run(base + ["open", target], timeout=TIMEOUT_RENDER)
    try:
        body = _run(base + ["get"], timeout=TIMEOUT_RENDER)
    finally:
        # Leaving a session open bills for a browser nobody is using.
        try:
            _run(base + ["close"], timeout=TIMEOUT_RENDER)
        except SystemExit:
            pass
    _emit_page(args, target, body)


def run_discover(args) -> None:
    """Intent-ranked search, for an angle two engines have left thin."""
    if not args.intent:
        _fail("discover mode requires --intent, the sentence describing what a good result answers")
    cli = _cli_bin()
    cmd = [cli, "discover", args.query, "--intent", args.intent, "--json"]
    if args.country:
        cmd.extend(["--country", args.country])
    if args.language:
        cmd.extend(["--language", args.language])
    if args.count:
        cmd.extend(["--num-results", str(args.count)])
    if args.since:
        cmd.extend(["--start-date", args.since])
    if args.until:
        cmd.extend(["--end-date", args.until])
    if args.must_contain:
        cmd.extend(["--filter-keywords", args.must_contain])
    if args.with_content:
        cmd.append("--include-content")
    raw = _run(cmd, timeout=TIMEOUT_PIPELINE)
    try:
        parsed = json.loads(raw)
    except ValueError:
        _fail(f"discover response was not JSON: {raw[:300]}")
    items = parsed if isinstance(parsed, list) else (
        parsed.get("results") or parsed.get("organic") or parsed.get("data") or [])
    results = []
    for i, item in enumerate(items[: args.count], start=1):
        results.append({
            "rank": item.get("rank", i),
            "title": item.get("title") or item.get("name") or "",
            "url": item.get("url") or item.get("link") or "",
            "snippet": item.get("snippet") or item.get("description") or "",
            "date": item.get("date") or item.get("updated") or None,
            "source_type": "web",
            "content": html_to_text(item["content"]) if item.get("content") else None,
        })
    if not results:
        _fail("discover returned no results")
    # With --with-content the page body came back and each result is a page
    # that was read; without it, these are ranked snippets like any other SERP.
    json.dump({"query": args.query, "mode": "discover", "provider": "brightdata",
               "intent": args.intent,
               "log_via": "brightdata" if args.with_content else "serp",
               "results": results}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


# Pipelines are structured-data products billed per record, not per Unlocker
# hit, so they are the last rung: used when every free path and `scrape` have
# failed on that platform. `brightdata pipelines list` prints the full set; the
# ones that matter to a decision-research question, by the source kind they
# produce:
#
#   review_aggregate  google_maps_reviews, facebook_company_reviews,
#                     amazon_product_reviews, apple_app_store, google_play_store
#   job_ad            linkedin_job_listings
#   community         reddit_posts, x_posts, youtube_comments, tiktok_comments
#   registry          linkedin_company_profile, crunchbase_company,
#                     zoominfo_company_profile, yahoo_finance_business,
#                     github_repository_file
#   vendor_pricing    google_shopping, amazon_product_search
#   press             reuter_news
#
# `reddit` stays as its own mode because reddit.com blocks the Unlocker zone
# under robots.txt, so it is the one platform where the pipeline is not a last
# resort but the only route.
_PIPELINE_FOR_MODE = {
    "reddit": ("reddit_posts", "reddit.com"),
}


def run_pipeline(args) -> None:
    target = args.query
    if args.mode == "pipeline":
        if not args.pipeline:
            _fail("pipeline mode requires --pipeline NAME; run `brightdata pipelines list` for the set")
        dataset, url_check = args.pipeline, ""
    else:
        dataset, url_check = _PIPELINE_FOR_MODE[args.mode]
    if not target.startswith(("http://", "https://")):
        _fail(f"{args.mode} mode requires a URL, got: {target[:80]}")
    if url_check and url_check not in target:
        _fail(f"{args.mode} mode expects a {url_check} URL, got: {target[:80]}")
    cli = _cli_bin()
    cmd = [cli, "pipelines", dataset, target, "--json"]
    raw = _run(cmd, timeout=TIMEOUT_PIPELINE)
    try:
        parsed = json.loads(raw)
    except ValueError:
        _fail(f"Pipeline response was not JSON: {raw[:300]}")
    # Pass the structured records through as a JSON string in `content` so the
    # skill's existing content-mode handlers can quote/parse it. Cheap and
    # avoids guessing the (per-dataset) schema in this wrapper.
    body = json.dumps(parsed, ensure_ascii=False)
    if args.max_chars and len(body) > args.max_chars:
        body = body[: args.max_chars]
    json.dump(
        {
            "url": target,
            "mode": args.mode,
            "pipeline": dataset,
            "provider": "brightdata",
            "title": None,
            "content": body,
            "date": None,
        },
        sys.stdout,
        ensure_ascii=False,
    )
    sys.stdout.write("\n")


def main() -> None:
    p = argparse.ArgumentParser(prog="bd_search.py", add_help=True)
    p.add_argument("query", help="search query, or URL for scrape/render/pipeline modes")
    p.add_argument("-m", "--mode", default="general")
    p.add_argument("-c", "--count", type=int, default=10)
    p.add_argument("--json", action="store_true", help="accepted for compat; output is always JSON")
    p.add_argument("--country", default=os.environ.get("BD_COUNTRY"))
    p.add_argument("--language", default=os.environ.get("BD_LANGUAGE"),
                   help="two-letter language code for SERP and discover")
    p.add_argument("--engine", default=None, choices=["google", "bing", "yandex"],
                   help="a second engine is the reason to pay for SERP at all")
    p.add_argument("--page", type=int, default=None, help="results page, 0-indexed; how to go deeper")
    p.add_argument("--device", default=None, choices=["desktop", "mobile"])
    p.add_argument("--intent", default=None, help="discover mode: what a good result answers")
    p.add_argument("--since", default=None, metavar="YYYY-MM-DD", help="discover mode: updated from")
    p.add_argument("--until", default=None, metavar="YYYY-MM-DD", help="discover mode: updated until")
    p.add_argument("--must-contain", default=None, dest="must_contain",
                   help="discover mode: comma-separated keywords a result must carry")
    p.add_argument("--with-content", action="store_true", dest="with_content",
                   help="discover mode: return page content with each result")
    p.add_argument("--pipeline", default=None,
                   help="pipeline mode: dataset name; see `brightdata pipelines list`")
    p.add_argument("--session", default=None, help="render mode: browser session name")
    p.add_argument("--find", action="append", default=[], metavar="TERM",
                   help="repeatable; return the passages around each term rather than the page head")
    p.add_argument("--window", type=int, default=300, help="characters either side of a --find hit")
    p.add_argument("--max-hits", type=int, default=5, dest="max_hits", help="passages per --find term")
    p.add_argument("--out", default=None, help="where to write the page text")
    p.add_argument("--max-chars", type=int, default=20000, dest="max_chars",
                   help="cap on returned content, applied after cleaning")
    p.add_argument(
        "--zone",
        default=os.environ.get("BD_SERP_ZONE") or os.environ.get("BD_UNLOCKER_ZONE"),
        help="override the CLI's default zone for SERP or scrape calls",
    )
    args = p.parse_args()

    if args.mode in RETIRED_MODES:
        _fail(
            f"mode {args.mode!r} was removed: the CLI has no such vertical, so it ran an ordinary "
            f"web search while looking like a vertical one. Use: "
            f"{', '.join(sorted(SERP_MODES | CONTENT_MODES | RENDER_MODES | DISCOVER_MODES | PIPELINE_MODES))}"
        )

    if args.mode in CONTENT_MODES:
        run_content(args)
    elif args.mode in RENDER_MODES:
        run_render(args)
    elif args.mode in DISCOVER_MODES:
        run_discover(args)
    elif args.mode in PIPELINE_MODES:
        run_pipeline(args)
    elif args.mode in SERP_MODES:
        run_serp(args)
    else:
        _fail(
            f"unknown mode: {args.mode}. One of: "
            f"{', '.join(sorted(SERP_MODES | CONTENT_MODES | RENDER_MODES | DISCOVER_MODES | PIPELINE_MODES))}"
        )


if __name__ == "__main__":
    main()
