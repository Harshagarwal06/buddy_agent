"""LangGraph-based news curation pipeline."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from tenacity import retry, stop_after_attempt, wait_exponential

from news_buddy import extract as _extract
from news_buddy import feeds as _feeds
from news_buddy import state as _state
from news_buddy.llm import get_sub_model

_ROOT = Path(__file__).parent.parent
_PROMPTS = _ROOT / "prompts"
_DB = _ROOT / "state.db"


# ── Typed state ───────────────────────────────────────────────────────────────

class DigestState(TypedDict):
    config: dict
    date_str: str
    dry_run: bool
    force: bool
    verbose: bool
    raw_items: list[dict]       # all fetched articles
    unseen_items: list[dict]    # after dedup
    enriched_items: list[dict]  # after extract + summarize
    digest: str                 # final markdown
    output_path: str            # written file path
    html_path: str              # written HTML file path
    total_tokens: int           # cumulative LLM tokens used this run


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(state: DigestState, msg: str) -> None:
    if state.get("verbose"):
        print(msg, file=sys.stderr)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def _invoke_with_retry(llm, messages, middleware: "SummarizationMiddleware | None" = None):
    """Call the LLM with exponential-backoff retry for transient API errors (429, 503)."""
    if middleware:
        messages = middleware.before_invoke(messages)
    resp = llm.invoke(messages)
    if middleware:
        middleware.after_invoke(resp)
    return resp


class SummarizationMiddleware:
    """Middleware that compresses the article body before each LLM call if the
    input exceeds the token budget — mirrors what LangChain's SummarizationMiddleware
    does for agent message histories, adapted for this single-turn pipeline.

    Hooks:
      before_invoke — trims the body inside the HumanMessage payload if needed.
      after_invoke  — logs token usage when the budget was exceeded.
    """

    def __init__(self, token_budget: int = 800) -> None:
        # ~4 chars per token is a reasonable approximation for English text
        self._budget_chars = token_budget * 4
        self._compressed = False

    def before_invoke(self, messages: list) -> list:
        self._compressed = False
        total_chars = sum(len(m.content) for m in messages)
        if total_chars <= self._budget_chars:
            return messages

        result = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                msg = self._compress_payload(msg, total_chars)
            result.append(msg)
        return result

    def after_invoke(self, response) -> None:
        if self._compressed:
            usage = getattr(response, "usage_metadata", None) or {}
            tokens = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)
            print(f"  [summarization-middleware] body compressed → {tokens} tokens used",
                  file=sys.stderr)

    def _compress_payload(self, msg: HumanMessage, total_chars: int) -> HumanMessage:
        try:
            payload = json.loads(msg.content)
            body = payload.get("body", "")
            overhead = total_chars - len(body)          # chars used by everything else
            allowed_body = max(200, self._budget_chars - overhead)
            if len(body) <= allowed_body:
                return msg
            payload["body"] = body[:allowed_body]
            self._compressed = True
            return HumanMessage(content=json.dumps(payload))
        except (json.JSONDecodeError, KeyError):
            return msg


_summarization_middleware = SummarizationMiddleware(token_budget=800)


def _summarize_one(sub_llm, item: dict) -> tuple[dict, int]:
    """Summarize a single article. Returns (enriched item dict, tokens used)."""
    body = _extract.extract_body(item["url"]) or item.get("rss_summary", "")
    system = (_PROMPTS / "summarizer.md").read_text()
    payload = json.dumps({"title": item["title"], "url": item["url"], "body": body[:1500]})
    resp = _invoke_with_retry(
        sub_llm,
        [SystemMessage(content=system), HumanMessage(content=payload)],
        middleware=_summarization_middleware,
    )
    text = resp.content.strip()

    # Extract token usage from response metadata (Gemini returns this)
    usage = getattr(resp, "usage_metadata", None) or {}
    tokens = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)

    # strip markdown code fences if model wraps JSON
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines()
            if not line.strip().startswith("```")
        ).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {"summary": item["title"], "tags": ["world"], "importance": 2}
    enriched = {
        **item,
        "summary": data.get("summary", item["title"]),
        "tags": data.get("tags", []),
        "importance": data.get("importance", 3),
    }
    return enriched, tokens


def _write_digest(output_dir: Path, date_str: str, markdown: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{date_str}.md"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(markdown, encoding="utf-8")
    tmp.replace(target)
    return target


# ── Nodes ─────────────────────────────────────────────────────────────────────

def fetch_feeds_node(state: DigestState) -> dict:
    """Fetch all RSS feeds in parallel."""
    config = state["config"]
    feeds = config["feeds"]
    lookback = config.get("lookback_hours", 24)
    max_items = config.get("max_items_per_feed", 10)

    if state["dry_run"]:
        _log(state, "[dry-run] fetch_feeds — skipping network calls")
        return {"raw_items": []}

    raw_items: list[dict] = []

    def _fetch(feed: dict) -> list[dict]:
        _log(state, f"Fetching {feed['name']} …")
        try:
            items = _feeds.fetch_feed_items(
                url=feed["url"],
                source_name=feed["name"],
                lookback_hours=lookback,
                max_items=max_items,
            )
            _log(state, f"  {len(items)} items from {feed['name']}")
            return items
        except Exception as e:
            print(f"[warn] {feed['name']} failed: {e}", file=sys.stderr)
            return []

    with ThreadPoolExecutor(max_workers=len(feeds)) as ex:
        futures = [ex.submit(_fetch, feed) for feed in feeds]
        for future in as_completed(futures):
            raw_items.extend(future.result())

    _log(state, f"Fetched {len(raw_items)} total items across {len(feeds)} feeds")
    return {"raw_items": raw_items}


def filter_ai_node(state: DigestState) -> dict:
    """Keep only articles that mention AI-related keywords in title or summary."""
    keywords = state["config"].get("ai_keywords", [])
    if not keywords:
        return {"raw_items": state["raw_items"]}  # no filter configured

    kw_lower = [k.lower() for k in keywords]

    def is_ai(item: dict) -> bool:
        text = (item.get("title", "") + " " + item.get("rss_summary", "")).lower()
        return any(kw in text for kw in kw_lower)

    before = len(state["raw_items"])
    filtered = [it for it in state["raw_items"] if is_ai(it)]
    _log(state, f"AI filter: {before} → {len(filtered)} articles "
                f"(kept articles matching {len(kw_lower)} keywords)")
    return {"raw_items": filtered}


def deduplicate_node(state: DigestState) -> dict:
    """Filter out already-seen articles."""
    raw = state["raw_items"]

    if state["force"] or state["dry_run"]:
        _log(state, f"Dedup skipped — {len(raw)} items pass through")
        unseen = raw
    else:
        unseen = _state.filter_unseen(_DB, raw)
        _log(state, f"{len(unseen)} new items after dedup (of {len(raw)} fetched)")

    # Hard cap to protect API quota: never summarize more than max_articles per run.
    cap = state["config"].get("max_articles")
    if cap is not None and len(unseen) > cap:
        unseen = unseen[:cap]
        _log(state, f"Capped to {cap} articles (max_articles)")
    return {"unseen_items": unseen}


def should_summarize(state: DigestState) -> str:
    """Conditional edge: skip summarization if nothing new."""
    if state["unseen_items"]:
        return "summarize_articles"
    return "write_empty"


def summarize_articles_node(state: DigestState) -> dict:
    """Extract full text and summarize each article in parallel."""
    unseen = state["unseen_items"]

    if state["dry_run"]:
        _log(state, f"[dry-run] summarize_articles — returning stubs for {len(unseen)} items")
        enriched = [
            {**it, "summary": it.get("rss_summary") or it["title"],
             "tags": ["world"], "importance": 3}
            for it in unseen
        ]
        return {"enriched_items": enriched}

    sub_llm = get_sub_model(state["config"])
    enriched: list[dict] = []
    errors: list[str] = []

    def _process(item: dict) -> tuple[dict, int]:
        _log(state, f"Summarizing: {item['title'][:70]}")
        try:
            enriched, tokens = _summarize_one(sub_llm, item)
            if not state["force"]:
                _state.mark_seen(_DB, item)
            return enriched, tokens
        except Exception as e:
            print(f"[warn] summarize failed for {item['url']}: {e}", file=sys.stderr)
            return ({**item, "summary": item.get("rss_summary") or item["title"],
                     "tags": ["world"], "importance": 2}, 0)

    total_tokens = 0
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(_process, item): item for item in unseen}
        for future in as_completed(futures):
            item_result, tokens = future.result()
            enriched.append(item_result)
            total_tokens += tokens

    _log(state, f"Summarized {len(enriched)} articles — {total_tokens} tokens used")
    return {"enriched_items": enriched, "total_tokens": total_tokens}


def format_digest_node(state: DigestState) -> dict:
    """Rank articles and build the Markdown digest string."""
    enriched = state["enriched_items"]
    date_str = state["date_str"]
    max_top = state["config"].get("max_top_stories", 5)

    enriched.sort(key=lambda x: x.get("importance", 3), reverse=True)
    top = enriched[:max_top]
    rest = enriched[max_top:]

    lines: list[str] = [f"# News Digest — {date_str}\n"]

    lines.append("## Top Stories\n")
    for it in top:
        lines.append(f"### [{it['title']}]({it['url']})")
        lines.append(f"*{it['source']} · {it['published_at'][:10]}*\n")
        lines.append(f"{it['summary']}\n")

    if rest:
        by_tag: dict[str, list[dict]] = {}
        for it in rest:
            tag = (it.get("tags") or ["other"])[0].title()
            by_tag.setdefault(tag, []).append(it)
        for tag, items in sorted(by_tag.items()):
            lines.append(f"\n## {tag}\n")
            for it in items:
                lines.append(f"### [{it['title']}]({it['url']})")
                lines.append(f"*{it['source']} · {it['published_at'][:10]}*\n")
                lines.append(f"{it['summary']}\n")

    return {"digest": "\n".join(lines)}


def write_digest_node(state: DigestState) -> dict:
    """Atomically write the digest to ~/news/YYYY-MM-DD.md."""
    if state["dry_run"]:
        _log(state, "[dry-run] write_digest — not writing file")
        return {"output_path": "/tmp/dry-run-digest.md"}

    output_dir = Path(state["config"].get("output_dir", "~/news")).expanduser()
    path = _write_digest(output_dir, state["date_str"], state["digest"])
    _log(state, f"Digest written → {path}")
    return {"output_path": str(path)}


def write_html_node(state: DigestState) -> dict:
    """Generate a styled HTML digest page alongside the Markdown file."""
    if state["dry_run"]:
        _log(state, "[dry-run] write_html — skipping")
        return {"html_path": "/tmp/dry-run-digest.html"}

    from news_buddy.html_writer import write_html
    output_dir = Path(state["config"].get("output_dir", "~/news")).expanduser()
    path = write_html(output_dir, state["date_str"], state.get("enriched_items", []))
    _log(state, f"HTML digest written → {path}")
    return {"html_path": str(path)}


def write_empty_node(state: DigestState) -> dict:
    """Write a short digest noting no new stories."""
    date_str = state["date_str"]
    digest = f"# News Digest — {date_str}\n\nNo new articles found.\n"

    if state["dry_run"]:
        _log(state, "[dry-run] write_empty — no new articles")
        return {"digest": digest, "output_path": "/tmp/dry-run-digest.md"}

    output_dir = Path(state["config"].get("output_dir", "~/news")).expanduser()
    path = _write_digest(output_dir, date_str, digest)
    _log(state, f"Empty digest written → {path}")
    return {"digest": digest, "output_path": str(path)}


# ── Graph assembly ────────────────────────────────────────────────────────────

def build_graph(checkpointing: bool = True):
    graph = StateGraph(DigestState)

    graph.add_node("fetch_feeds",        fetch_feeds_node)
    graph.add_node("filter_ai",          filter_ai_node)
    graph.add_node("deduplicate",        deduplicate_node)
    graph.add_node("summarize_articles", summarize_articles_node)
    graph.add_node("format_digest",      format_digest_node)
    graph.add_node("write_digest",       write_digest_node)
    graph.add_node("write_empty",        write_empty_node)
    graph.add_node("write_html",         write_html_node)

    graph.set_entry_point("fetch_feeds")
    graph.add_edge("fetch_feeds",        "filter_ai")
    graph.add_edge("filter_ai",          "deduplicate")
    graph.add_conditional_edges("deduplicate", should_summarize)
    graph.add_edge("summarize_articles", "format_digest")
    graph.add_edge("format_digest",      "write_digest")
    graph.add_edge("write_digest",       "write_html")
    graph.add_edge("write_empty",        "write_html")
    graph.add_edge("write_html",         END)

    checkpointer = MemorySaver() if checkpointing else None
    return graph.compile(checkpointer=checkpointer)


# ── Public API ────────────────────────────────────────────────────────────────

def run_pipeline(
    config: dict,
    date_str: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Run the full curation pipeline.

    Returns a structured result dict:
      {
        "digest":       str,   # full Markdown content
        "output_path":  str,   # path of the written file
        "item_count":   int,   # number of articles summarized
        "error":        str | None,  # set if the pipeline crashed
      }
    """
    resolved_date = date_str or date.today().isoformat()
    graph = build_graph()
    try:
        result = graph.invoke(
            {
                "config": config,
                "date_str": resolved_date,
                "dry_run": dry_run,
                "force": force,
                "verbose": verbose,
                "raw_items": [],
                "unseen_items": [],
                "enriched_items": [],
                "digest": "",
                "output_path": "",
                "html_path": "",
                "total_tokens": 0,
            },
            config={"configurable": {"thread_id": "news-buddy"}},
        )
        return {
            "digest":       result["digest"],
            "output_path":  result["output_path"],
            "html_path":    result.get("html_path", ""),
            "item_count":   len(result.get("enriched_items", [])),
            "total_tokens": result.get("total_tokens", 0),
            "error":        None,
        }
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        print(f"[error] Pipeline failed: {error_msg}", file=sys.stderr)
        return {
            "digest":      "",
            "output_path": "",
            "item_count":  0,
            "error":       error_msg,
        }
