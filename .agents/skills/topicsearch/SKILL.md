---
name: topicsearch
description: >
  Use this skill when the user types /topicsearch or asks to search past
  articles, look up news about a topic, find articles about a keyword, search
  the news archive, or phrases like "search my past articles about X",
  "what have I seen about X", "find articles mentioning X", "show me past
  news on X", or "have I seen anything about X". The user may optionally
  specify a source feed with --source and a result limit with --limit.
version: "2.0"
allowed-tools:
  - Bash
---

# topicsearch — Search Past Articles (keyword + semantic)

Search the local news archive using both keyword matching and semantic
(vector) similarity. Always run both searches and merge the results.

## Step 1 — Parse the invocation

Extract from the user's message:
- **keyword** (required): the search topic — everything after `/topicsearch`
  up to any flag. For natural language ("search past articles about AI chips"),
  extract the topic phrase.
- **--source** (optional): a feed name filter (keyword search only).
- **--limit** (optional): integer cap on results per search (default 10).

## Step 2 — Run both searches in parallel

**Keyword search** (exact title matching):
```bash
uv run python news_buddy/search.py \
  "<keyword>" \
  [--source "<source>"] \
  [--limit <N>]
```

**Semantic search** (vector similarity over full article bodies):
```bash
uv run python news_buddy/semantic_search_cli.py \
  "<keyword>" \
  [--limit <N>]
```

Run both Bash calls in the same message (parallel). Parse both JSON outputs.

## Step 3 — Interpret the results

Keyword JSON shape:
```json
{
  "query": "openai", "count": 5, "total_matches": 12, "truncated": false,
  "results": [{"title":"...","source":"...","url":"...","first_seen_at":"..."}]
}
```

Semantic JSON shape:
```json
{
  "query": "openai", "count": 5,
  "results": [{"title":"...","source":"...","url":"...","similarity":0.87}]
}
```

If either JSON contains an `"error"` key, skip that section silently (the
vector store may not exist yet if no pipeline run has completed).

## Step 4 — Merge and deduplicate

Combine both result lists, deduplicating by URL. Mark the origin of each
result: `[keyword]`, `[semantic]`, or `[both]`. Sort by:
1. Articles found by both searches (highest confidence) first
2. Then semantic results by similarity score
3. Then keyword results by recency

## Step 5 — Synthesise the mini-briefing

Format your response using this structure:

---

### Topic Briefing: "<keyword>"

**Landscape (2–3 sentences)**
Write a brief synthesis of what the matching articles collectively suggest —
key themes, major players, or trend direction. Base this ONLY on the article
titles returned; do not invent facts.

**Matching Articles** (N found)
| # | Title | Source | Date | Match |
|---|-------|--------|------|-------|
| 1 | [Title](url) | Source | YYYY-MM-DD | [both] |

Use `first_seen_at` for keyword results (truncated to YYYY-MM-DD) and show
similarity score for semantic-only results (e.g. `sim=0.87`).

**What to Read First**
Pick 1–3 articles based on specificity, recency, and similarity. One sentence
each explaining why. Prefer variety across sources.

---

## Edge cases

**Zero results from both searches**
Do NOT show the table. Reply:
> No articles matching **"<keyword>"** were found in your archive.
> The vector store builds up as you run the pipeline — try again after the next run.

**chroma_db missing (semantic error)**
Show keyword results only, and note:
> _Semantic search unavailable — run the pipeline once to build the vector store._

**Truncated keyword results** (`truncated == true`)
Add after the table:
> Showing the **<limit> most recent** keyword matches of **<total_matches> total**.
> Run again with `--limit <total_matches>` to see all.

**DB not initialised** (keyword `"error"` key in JSON)
Report the error and suggest:
> Run `python -m news_buddy run` once to initialise the database.
