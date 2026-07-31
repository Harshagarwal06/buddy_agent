from news_buddy import rag


class _FakeCollection:
    def __init__(self):
        self._ids = set()
        self.added = []

    def get(self, ids):
        return {"ids": [i for i in ids if i in self._ids]}

    def add(self, ids, embeddings, documents, metadatas):
        self._ids.update(ids)
        self.added.append(
            {"ids": ids, "embeddings": embeddings, "documents": documents, "metadatas": metadatas}
        )


class _FakeEmbedder:
    def embed_query(self, text):
        return [float(len(text))]


def test_embed_article_writes_okf_file_before_embedding(monkeypatch):
    fake_collection = _FakeCollection()
    write_calls = []

    monkeypatch.setattr(rag, "_get_collection", lambda: fake_collection)
    monkeypatch.setattr(rag, "_get_doc_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr(
        rag.knowledge_base, "write_article", lambda **kwargs: write_calls.append(kwargs)
    )

    rag.embed_article(
        url="https://example.test/a",
        title="Model launches",
        summary="A new model launched today.",
        tags=["ai"],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )

    assert write_calls == [
        {
            "url": "https://example.test/a",
            "title": "Model launches",
            "summary": "A new model launched today.",
            "tags": ["ai"],
            "source": "Test Feed",
            "published_at": "2026-07-17T09:00:00+00:00",
        }
    ]
    assert fake_collection.added[0]["ids"] == ["https://example.test/a"]
    assert fake_collection.added[0]["documents"] == [
        "Model launches\n\nA new model launched today."
    ]
    assert fake_collection.added[0]["metadatas"] == [
        {"url": "https://example.test/a", "title": "Model launches", "source": "Test Feed"}
    ]


def test_embed_article_skips_already_indexed_url(monkeypatch):
    fake_collection = _FakeCollection()
    fake_collection._ids.add("https://example.test/dup")
    write_calls = []

    monkeypatch.setattr(rag, "_get_collection", lambda: fake_collection)
    monkeypatch.setattr(
        rag.knowledge_base, "write_article", lambda **kwargs: write_calls.append(kwargs)
    )

    rag.embed_article(
        url="https://example.test/dup",
        title="Already indexed",
        summary="Doesn't matter.",
        tags=[],
        source="Test Feed",
        published_at="2026-07-17T09:00:00+00:00",
    )

    assert write_calls == []
    assert fake_collection.added == []
