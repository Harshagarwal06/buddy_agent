# News Buddy — LangGraph Execution Diagram

## Full Graph Flow

```mermaid
flowchart TD
    START(["▶ START\nrun_pipeline()"])

    subgraph STATE["📦 DigestState — flows through every node"]
        direction LR
        S1["config · date_str · dry_run · force · verbose"]
        S2["raw_items → unseen_items → enriched_items"]
        S3["digest · output_path"]
    end

    subgraph FETCH["① fetch_feeds_node"]
        direction TB
        F1["🔄 ThreadPoolExecutor — all 5 feeds at once"]
        F2["Hacker News RSS"]
        F3["BBC World RSS"]
        F4["The Verge RSS"]
        F5["Ars Technica RSS"]
        F6["TechCrunch RSS"]
        F7["feeds.fetch_feed_items() × 5"]
        F1 --> F2 & F3 & F4 & F5 & F6 --> F7
    end

    subgraph DEDUP["② deduplicate_node"]
        D1["state.filter_unseen()\nSQLite lookup — seen URLs"]
        D2{"Any new\narticles?"}
        D1 --> D2
    end

    subgraph SUMM["③ summarize_articles_node"]
        direction TB
        S_1["🔄 ThreadPoolExecutor — 3 articles at once"]
        S_2["extract.extract_body(url)"]
        S_3["llama3.2:3b via Ollama"]
        S_4["→ {summary, tags, importance}"]
        S_5["state.mark_seen() in SQLite"]
        S_1 --> S_2 --> S_3 --> S_4 --> S_5
    end

    subgraph FORMAT["④ format_digest_node"]
        FM1["Sort by importance ↓"]
        FM2["Top 5 → ## Top Stories"]
        FM3["Rest → grouped by tag\n(Technology, World, AI…)"]
        FM1 --> FM2 & FM3
    end

    subgraph WRITE["⑤ write_digest_node"]
        W1["Atomic write\n~/news/YYYY-MM-DD.md"]
        W2["📩 telegram_notify\nsend_digest()"]
        W1 --> W2
    end

    subgraph EMPTY["⑤ write_empty_node"]
        E1["Write 'No new articles'"]
        E2["📩 telegram_notify\nskipped if send_on_empty=false"]
        E1 --> E2
    end

    END(["⏹ END\nreturn structured result"])

    START --> FETCH
    FETCH -->|"raw_items: list[dict]"| DEDUP
    D2 -->|"unseen_items not empty"| SUMM
    D2 -->|"unseen_items is empty"| EMPTY
    SUMM -->|"enriched_items: list[dict]"| FORMAT
    FORMAT -->|"digest: str"| WRITE
    WRITE --> END
    EMPTY --> END
```

---

## State at Each Stage

```
START
  config, date_str, dry_run, force, verbose
  raw_items=[]  unseen_items=[]  enriched_items=[]  digest=""  output_path=""

  ▼ fetch_feeds_node
  raw_items=[
    {source, title, url, published_at, rss_summary},  ← up to 50 items
    ...
  ]

  ▼ deduplicate_node
  unseen_items=[
    {source, title, url, published_at, rss_summary},  ← only new ones
    ...
  ]

  ▼ summarize_articles_node
  enriched_items=[
    {source, title, url, published_at, rss_summary,
     summary, tags, importance},                       ← Ollama adds these
    ...
  ]

  ▼ format_digest_node
  digest="# News Digest — 2026-05-26\n## Top Stories\n..."

  ▼ write_digest_node
  output_path="/Users/harshagarwal/news/2026-05-26.md"

END → {digest, output_path, item_count, error}
```

---

## Parallelism Detail

```
fetch_feeds_node
┌─────────────────────────────────────────────────────┐
│  ThreadPoolExecutor(max_workers=5)                  │
│                                                     │
│  Thread 1 ──► Hacker News  ──► 10 items  ──┐       │
│  Thread 2 ──► BBC World    ──► 10 items  ──┤       │
│  Thread 3 ──► The Verge    ──►  6 items  ──┼──► [] │
│  Thread 4 ──► Ars Technica ──►  3 items  ──┤       │
│  Thread 5 ──► TechCrunch   ──►  5 items  ──┘       │
│                                                     │
│  Sequential: ~15s    Parallel: ~4s  (~4x faster)   │
└─────────────────────────────────────────────────────┘

summarize_articles_node
┌─────────────────────────────────────────────────────┐
│  ThreadPoolExecutor(max_workers=3)                  │
│                                                     │
│  Thread 1 ──► Article 1 ──► Ollama ──► summary     │
│  Thread 2 ──► Article 2 ──► Ollama ──► summary     │
│  Thread 3 ──► Article 3 ──► Ollama ──► summary     │
│               Article 4 ──► (waits for free slot)  │
│                    ...                              │
│                                                     │
│  34 articles × ~8s each = ~90s sequential          │
│  With 3 workers              = ~30s  (3x faster)   │
└─────────────────────────────────────────────────────┘
```

---

## Checkpoint (Failure Recovery)

```
MemorySaver checkpoints state after each node completes.

If Ollama crashes mid-summarization:

  fetch_feeds    ✅ saved
  deduplicate    ✅ saved
  summarize      ❌ crashed at article 17/34

  → Restart pipeline with same thread_id
  → LangGraph replays from last checkpoint
  → Resumes from article 17, not article 1
```

---

## Conditional Edge

```
deduplicate_node
        │
        ▼
  should_summarize()
        │
        ├── unseen_items is NOT empty ──► summarize_articles ──► format ──► write
        │
        └── unseen_items IS empty     ──► write_empty ──► END
                                           (saves time, skips Ollama entirely)
```
