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
    bd_search.py "<thread url>" -m reddit            # scrape first, pipeline if incomplete
    bd_search.py "<thread url>" -m reddit --route pipeline   # force the dataset job

| Mode | CLI call | When |
|---|---|---|
| general, news, images, shopping | `brightdata search --type` | A second engine, or geo and language WebSearch cannot express |
| discover | `brightdata discover --intent` | Two engines came back thin |
| scrape | `brightdata scrape -f markdown` | fetch.py and WebFetch were both blocked |
| render | `brightdata browser open/get/close` | The page is a client-rendered shell |
| pipeline | `brightdata pipelines <name>` | A platform that blocks everything above; billed per record |
| reddit | `brightdata scrape -f html`, then `brightdata pipelines reddit_posts` | A single thread tries the scrape first (about 5 to 30 s, about a cent) and falls back to the pipeline (8 to 12 min, per record) when the page is empty, blocked or holds fewer comments than it reports. A subreddit listing always uses the pipeline |

`--route auto|scrape|pipeline` (reddit mode only, default `auto`) forces a route.
`scrape` never falls back and reads single threads only. `pipeline` skips the
scrape, for a listing or a complete comment tree. The JSON says which route
produced the data (`route`), how many comments were recovered against how many
the post reports (`recovered`, `reported`), and why a fallback happened
(`fallback_reason`).

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
import re
import os
import shutil
import subprocess
import sys
import time
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch import (  # noqa: E402
    classify, default_out_path, find_windows, html_to_text, write_outputs)

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
TIMEOUT_REDDIT_SCRAPE = 120  # measured 5 to 30 s for a thread; headroom for a slow unlock
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


def _run_raw(cmd: list[str], timeout: int = TIMEOUT_FAST) -> tuple[str, str, int]:
    """Run the CLI. Return (stdout, error message, exit class); the message is empty on success.

    The exit class is 0 for success, 1 for an ordinary failure and EXIT_AUTH for
    an auth or quota failure. Callers that can fall back use this directly;
    everything else goes through _run, which fails.
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "", f"Bright Data CLI timed out after {timeout}s", 1
    except OSError as e:
        return "", f"failed to invoke Bright Data CLI: {e}", 1
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        code = _classify_exit(msg)
        hint = f" {SETUP_HINT}" if code == EXIT_AUTH else ""
        return "", f"Bright Data CLI failed: {msg[:400]}{hint}", code
    return proc.stdout, "", 0


def _run(cmd: list[str], timeout: int = TIMEOUT_FAST) -> str:
    """Run the CLI and return stdout. On failure, _fail() with a useful code."""
    out, err, code = _run_raw(cmd, timeout)
    if err:
        _fail(err, code=code)
    return out


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
        "--type",
        _TYPE_FOR_MODE.get(args.mode, "web"),
        "--json",
    ]
    # A second engine is the point of paying at all: WebSearch is one engine
    # with no country or language control, and a UK or EU question asked of a
    # US-centric index returns a different web.
    if args.engine:
        cmd.extend(["--engine", args.engine])
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
    if args.zone:
        cmd.extend(["--zone", args.zone])
    # The query goes last, after "--", so a wording that starts with "-"
    # (an exclusion such as -crypto) is a query and not an option.
    cmd.extend(["--", args.query])
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


_CLI_USAGE_RE = re.compile(r"^\s*Usage:\s+brightdata\b", re.M)


def _emit_page(args, target, body) -> None:
    """Clean, window, cap, and write the sidecar fetch.py's consumers expect.

    Truncating a long page to its first N characters reliably returns the
    navigation and none of the content - measured on an eval run where two paid
    fetches came back as nav shells. Cleaning first and windowing on --find
    terms is what makes the cap safe.
    """
    # A CLI that answers a malformed invocation with its own usage text and
    # exit 0 would otherwise be written to disk and quoted as though it were
    # the page.
    if _CLI_USAGE_RE.search(body[:400]):
        _fail(f"the CLI returned usage text rather than page content for {target[:80]}")
    text = html_to_text(body) if "<" in body[:400] else body.strip()
    passages = find_windows(text, args.find, args.window, args.max_hits) if args.find else []
    capped = text[: args.max_chars] if args.max_chars and len(text) > args.max_chars else text
    out_path = args.out or default_out_path(target)
    # Paying for a page does not mean getting one. The Unlocker and the browser
    # both return challenge pages and empty shells with a perfectly good exit
    # code, and without this the run would quote one as though it were the
    # source. There is no HTTP status on this path, so 200 stands in and the
    # content tests do the work.
    verdict, reason = classify(text, 200, body)
    payload = {
        "url": target,
        "mode": args.mode,
        "provider": "brightdata",
        "log_via": "brightdata",
        "title": None,
        "date": None,
        "chars": len(text),
        "text_file": out_path,
        "verdict": verdict,
        "reason": reason,
        "content": capped,
        "find": passages,
    }
    write_outputs(out_path, text, {k: v for k, v in payload.items() if k != "content"})
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    if verdict != "ok":
        sys.exit(3)


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
    # The CLI has no wait command, and a single-page app is often still drawing
    # itself when `open` returns. Measured on one bank portal: 7,115 bytes of
    # HTML immediately, 7,392 after a few seconds, stable thereafter. Small,
    # because the rung is already the slow one.
    if args.settle:
        time.sleep(args.settle)
    try:
        # `browser get` is a command group, not a leaf: on its own it prints its
        # own usage text and exits 0, so the "page body" came back as the CLI's
        # help. Found by an eval arm on 2026-09-06, not by a test - the test
        # asserted the verb sequence and never looked at what `get` returned.
        body = _run(base + ["get", "html"], timeout=TIMEOUT_RENDER)
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
# `reddit` is its own mode, and it has two routes. Measured on 2026-10-23:
#
#   - The Web Unlocker (`scrape -f html`) works for a single thread given its
#     full URL with the slug. One test took 27 s and returned 17 of the 17
#     comments the post reported. Cost was about a cent.
#   - A subreddit listing (/new/) took 4 s, but the server-rendered HTML holds
#     only the first few posts, so a listing cannot be read this way.
#   - A thread URL without the slug returned 149 bytes.
#   - The pipeline is an asynchronous dataset job that took about 8 to 12
#     minutes, billed per record. It is for listings and complete comment trees.
#
# So a single thread tries the scrape first and falls back to the pipeline when
# the page is empty, blocked, or holds fewer comments than it reports. A
# listing, or a thread URL with no slug, goes straight to the pipeline.
# `--route` forces either route.
_PIPELINE_FOR_MODE = {
    "reddit": ("reddit_posts", "reddit.com"),
}

ROUTES = ("auto", "scrape", "pipeline")
# An empty or blocked Unlocker answer is a few hundred bytes; a real thread
# page is hundreds of kilobytes.
MIN_REDDIT_HTML_BYTES = 2048
# /r/<sub>/comments/<id>/<slug>/ : the slug is the part a thread URL needs.
_REDDIT_THREAD_RE = re.compile(
    r"^https?://[^/]*reddit\.com/r/[^/?#]+/comments/([a-z0-9]+)(?:/([^/?#]+))?", re.I)


def _reddit_thread(url: str):
    """(thread id, slug or None) for a single-thread URL, else None (a listing)."""
    m = _REDDIT_THREAD_RE.match(url)
    return (m.group(1), m.group(2)) if m else None


def _tidy(text: str) -> str:
    """Collapse runs of whitespace inside each line and drop blank lines."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


class _RedditThreadParser(HTMLParser):
    """Pull the post and its comments out of a Reddit thread page.

    Written against the server-rendered page the Unlocker returns:
    `<shreddit-post>` carries the title, author, score and comment count as
    attributes, and each `<shreddit-comment>` carries its author, score, depth
    and parent as attributes, with the comment text in a `div slot="comment"`.
    Replies sit inside their parent's element, so a stack of open comments says
    which one a piece of text belongs to.
    """

    def __init__(self, thread_id: str | None = None):
        super().__init__(convert_charrefs=True)
        self.thread_id = thread_id
        self.post: dict | None = None
        self.comments: list[dict] = []
        self.shreddit_comment_tags = 0
        self._open: list[dict] = []
        self._capture: list | None = None  # text pieces being collected
        self._capture_tag = ""
        self._capture_depth = 0
        self._skip = 0  # inside script or style

    def _begin(self, tag: str, sink: list) -> None:
        self._capture, self._capture_tag, self._capture_depth = sink, tag, 1

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        if self._capture is not None:
            if tag == self._capture_tag:
                self._capture_depth += 1
            elif tag == "br":
                self._capture.append("\n")
            return
        if tag == "shreddit-post":
            wanted = "t3_" + self.thread_id if self.thread_id else None
            if self.post is None and (wanted is None or a.get("id") == wanted):
                self.post = {
                    "title": a.get("post-title") or "",
                    "author": a.get("author") or None,
                    "score": _to_int(a.get("score")),
                    "created": a.get("created-timestamp") or None,
                    "subreddit": a.get("subreddit-prefixed-name") or None,
                    "permalink": a.get("permalink") or None,
                    "reported_comments": _to_int(a.get("comment-count")),
                    "text": "",
                    "_text": [],
                }
        elif tag == "shreddit-comment":
            self.shreddit_comment_tags += 1
            comment = {
                "id": a.get("thingid") or None,
                "parent": a.get("parentid") or None,
                "author": a.get("author") or None,
                "score": _to_int(a.get("score")),
                "depth": _to_int(a.get("depth")) or 0,
                "created": a.get("created") or None,
                "permalink": a.get("permalink") or None,
                "text": "",
                "_text": [],
            }
            self.comments.append(comment)
            self._open.append(comment)
        elif tag == "div" and a.get("slot") == "comment" and self._open:
            self._begin("div", self._open[-1]["_text"])
        elif tag == "shreddit-post-text-body" and self.post is not None and not self.post["_text"]:
            self._begin(tag, self.post["_text"])

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if self._capture is not None:
            if tag == self._capture_tag:
                self._capture_depth -= 1
                if self._capture_depth == 0:
                    self._capture = None
            elif tag == "p":
                self._capture.append("\n")
            return
        if tag == "shreddit-comment" and self._open:
            self._open.pop()

    def handle_data(self, data):
        if self._capture is not None and not self._skip:
            self._capture.append(data)

    def result(self) -> tuple[dict | None, list[dict]]:
        for item in ([self.post] if self.post else []) + self.comments:
            item["text"] = _tidy("".join(item.pop("_text")))
        return self.post, self.comments


def _to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _render_thread(url: str, post: dict, comments: list[dict], reported) -> str:
    """The thread as plain text, replies indented under their parent."""
    head = [
        f"Title: {post['title']}",
        f"Author: {post['author']}  Score: {post['score']}  Posted: {post['created']}",
        f"URL: {url}",
        f"Comments: recovered {len(comments)} of reported {reported}",
    ]
    if post["text"]:
        head += ["", post["text"]]
    body = []
    for c in comments:
        pad = "  " * (c["depth"] or 0)
        body.append(f"{pad}[depth {c['depth']}] {c['author']} (score {c['score']}) id={c['id']} parent={c['parent']}")
        body.extend(pad + "  " + line for line in c["text"].splitlines())
    return "\n".join(head + [""] + body) + "\n"


def _scrape_reddit_thread(cli: str, args, thread_id: str):
    """Try the Unlocker on one thread.

    Returns (data, reason). `data` is None when the page cannot be used at all;
    otherwise it holds the parsed post and comments and the two counts. `reason`
    says why the result is not a complete thread, and is empty when it is.
    A failed CLI call comes back as a reason, except an auth or quota failure,
    which ends the run: falling back would only fail the same way, later.
    """
    cmd = [cli, "scrape", args.query, "-f", "html"]
    if args.country:
        cmd.extend(["--country", args.country])
    if args.zone:
        cmd.extend(["--zone", args.zone])
    body, err, code = _run_raw(cmd, timeout=TIMEOUT_REDDIT_SCRAPE)
    if err:
        if code == EXIT_AUTH:
            _fail(err, code=code)
        return None, f"scrape failed: {err}"
    size = len(body.encode("utf-8", "ignore"))
    if size < MIN_REDDIT_HTML_BYTES:
        return None, f"scrape returned only {size} bytes (empty or blocked)"
    if "<shreddit-post" not in body:
        return None, "scrape returned a page with no post in it (blocked or not a thread)"
    parser = _RedditThreadParser(thread_id)
    parser.feed(body)
    parser.close()
    post, comments = parser.result()
    if post is None:
        return None, "scrape returned a page with no post for this thread"
    reported = post["reported_comments"]
    data = {"post": post, "comments": comments, "recovered": len(comments),
            "reported": reported, "bytes": size}
    if reported is None:
        return data, f"recovered {len(comments)} comments but the post does not say how many it has"
    if len(comments) < reported:
        return data, f"recovered {len(comments)} of {reported} reported comments"
    return data, ""


def _emit_reddit_scrape(args, data: dict, elapsed: float, note: str) -> None:
    post, comments = data["post"], data["comments"]
    reported = data["reported"]
    out_path = args.out or default_out_path(args.query)
    text = _render_thread(args.query, post, comments, reported)
    # Fit the structured records under --max-chars by dropping trailing
    # comments, never by cutting the JSON string mid-way.
    keep = list(comments)
    while True:
        shown = {"post": {k: v for k, v in post.items() if k != "reported_comments"}, "comments": keep}
        content = json.dumps(shown, ensure_ascii=False)
        if not args.max_chars or len(content) <= args.max_chars or not keep:
            break
        keep = keep[: max(0, len(keep) // 2)]
    payload = {
        "url": args.query,
        "mode": args.mode,
        "route": "scrape",
        "provider": "brightdata",
        "log_via": "brightdata",
        "title": post["title"],
        "date": (post["created"] or "")[:10] or None,
        "recovered": data["recovered"],
        "reported": reported,
        "complete": not note,
        "note": note or None,
        "returned_in_content": len(keep),
        "chars": len(text),
        "text_file": out_path,
        "verdict": "ok",
        "reason": "",
        "elapsed_s": round(elapsed, 1),
        "content": content,
    }
    write_outputs(out_path, text, {k: v for k, v in payload.items() if k != "content"})
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def run_reddit(args) -> None:
    """Pick the route for a Reddit URL, try it, and say which one produced the data."""
    target = args.query
    if not target.startswith(("http://", "https://")):
        _fail(f"{args.mode} mode requires a URL, got: {target[:80]}")
    if "reddit.com" not in target:
        _fail(f"{args.mode} mode expects a reddit.com URL, got: {target[:80]}")
    thread = _reddit_thread(target)
    route = args.route
    if route == "pipeline":
        return run_pipeline(args, extra={"route": "pipeline", "route_reason": "forced with --route pipeline"})
    if thread is None:
        if route == "scrape":
            _fail("--route scrape reads a single thread (/r/<sub>/comments/<id>/<slug>/); "
                  "a listing page holds only its first few posts. Use the pipeline route.")
        return run_pipeline(args, extra={
            "route": "pipeline",
            "route_reason": "not a single-thread URL; a listing page holds only its first few posts"})
    thread_id, slug = thread
    if not slug and route == "auto":
        return run_pipeline(args, extra={
            "route": "pipeline",
            "route_reason": "the thread URL has no slug, and the scrape returns almost nothing "
                            "without it (149 bytes in testing); use the full URL to try the scrape"})
    cli = _cli_bin()
    started = time.monotonic()
    data, reason = _scrape_reddit_thread(cli, args, thread_id)
    elapsed = time.monotonic() - started
    if data is not None and not reason:
        return _emit_reddit_scrape(args, data, elapsed, "")
    if route == "scrape":
        if data is None:
            _fail(f"--route scrape: {reason}")
        # Forced, so no fallback: hand back what the page held and say it is partial.
        return _emit_reddit_scrape(args, data, elapsed, reason + " (partial; no fallback with --route scrape)")
    extra = {"route": "pipeline", "route_reason": "scrape was not enough, fell back",
             "fallback_reason": reason, "scrape_elapsed_s": round(elapsed, 1)}
    if data is not None:
        extra.update({"scrape_recovered": data["recovered"], "scrape_reported": data["reported"]})
    run_pipeline(args, extra=extra)


def run_pipeline(args, extra: dict | None = None) -> None:
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
    payload = {
        "url": target,
        "mode": args.mode,
        "pipeline": dataset,
        "provider": "brightdata",
        "title": None,
        "content": body,
        "date": None,
    }
    payload.update(extra or {})
    json.dump(payload, sys.stdout, ensure_ascii=False)
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
    p.add_argument("--engine", default=None, choices=["google", "bing"],
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
    p.add_argument("--route", default="auto", choices=ROUTES,
                   help="reddit mode: auto tries `scrape` first for a single thread and falls back to "
                        "the pipeline; scrape never falls back; pipeline skips the scrape")
    p.add_argument("--session", default=None, help="render mode: browser session name")
    p.add_argument("--settle", type=float, default=3.0,
                   help="render mode: seconds to let a single-page app finish drawing (default 3)")
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

    if args.route != "auto" and args.mode != "reddit":
        _fail(f"--route {args.route} applies to reddit mode only, not {args.mode!r}")

    if args.mode == "reddit":
        run_reddit(args)
    elif args.mode in CONTENT_MODES:
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
