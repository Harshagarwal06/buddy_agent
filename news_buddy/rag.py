"""ChromaDB-backed vector store for semantic search over past articles.

Uses Google models/gemini-embedding-2 (same GOOGLE_API_KEY as the LLM).
The chroma_db/ directory is created alongside state.db on first use. Each
embedded article is first written as an OKF file by knowledge_base.py,
which becomes the text that gets embedded.
"""
from __future__ import annotations

import os

try:
    import chromadb
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "RAG support is not installed. Run: pip install 'news-buddy[rag]'"
    ) from exc

from news_buddy import knowledge_base
from news_buddy.paths import runtime_root

_CHROMA_PATH = runtime_root() / "chroma_db"
_COLLECTION_NAME = "articles"

_collection: chromadb.Collection | None = None
_doc_embedder: GoogleGenerativeAIEmbeddings | None = None
_query_embedder: GoogleGenerativeAIEmbeddings | None = None


def _api_key() -> str:
    key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GOOGLE_API_KEY is not set — required for RAG embeddings.")
    return key


def _get_doc_embedder() -> GoogleGenerativeAIEmbeddings:
    global _doc_embedder
    if _doc_embedder is None:
        _doc_embedder = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-2",
            google_api_key=_api_key(),
            task_type="retrieval_document",
        )
    return _doc_embedder


def _get_query_embedder() -> GoogleGenerativeAIEmbeddings:
    global _query_embedder
    if _query_embedder is None:
        _query_embedder = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-2",
            google_api_key=_api_key(),
            task_type="retrieval_query",
        )
    return _query_embedder


def _get_collection() -> chromadb.Collection:
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
        _collection = client.get_or_create_collection(
            _COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def embed_article(
    url: str,
    title: str,
    summary: str,
    tags: list[str],
    source: str,
    published_at: str,
) -> None:
    """Write the article's OKF file, then embed and store it. No-ops silently if already indexed."""
    collection = _get_collection()
    if collection.get(ids=[url])["ids"]:
        return
    knowledge_base.write_article(
        url=url,
        title=title,
        summary=summary,
        tags=tags,
        source=source,
        published_at=published_at,
    )
    text = f"{title}\n\n{summary}" if summary.strip() else title
    vector = _get_doc_embedder().embed_query(text)
    collection.add(
        ids=[url],
        embeddings=[vector],
        documents=[text],
        metadatas=[{"url": url, "title": title, "source": source}],
    )


def semantic_search(query: str, n_results: int = 5) -> list[dict]:
    """Return the n most semantically similar past articles to query."""
    collection = _get_collection()
    total = collection.count()
    if total == 0:
        return []
    vector = _get_query_embedder().embed_query(query)
    results = collection.query(
        query_embeddings=[vector],
        n_results=min(n_results, total),
        include=["metadatas", "distances"],
    )
    return [
        {
            "title": meta["title"],
            "source": meta["source"],
            "url": meta["url"],
            "similarity": round(1 - dist, 3),
        }
        for meta, dist in zip(results["metadatas"][0], results["distances"][0])
    ]
