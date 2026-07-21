import json

from news_buddy.agent import write_html_node


def _base_state(tmp_path, enriched_items):
    return {
        "dry_run": False,
        "date_str": "2026-07-17",
        "config": {"output_dir": str(tmp_path)},
        "enriched_items": enriched_items,
        "verbose": False,
    }


def test_write_html_node_also_writes_search_index(tmp_path):
    state = _base_state(tmp_path, [
        {
            "title": "Model launches",
            "url": "https://example.test/a",
            "source": "Test Feed",
            "published_at": "2026-07-17T09:00:00Z",
            "summary": "A new model launched today.",
            "tags": ["ai"],
            "importance": 5,
        }
    ])

    write_html_node(state)

    index_path = tmp_path / "2026-07-17.json"
    manifest_path = tmp_path / "index.json"
    assert index_path.exists()
    records = json.loads(index_path.read_text(encoding="utf-8"))
    assert records[0]["title"] == "Model launches"
    assert records[0]["importance"] == 5
    # Verify that published_at is truncated to YYYY-MM-DD (date only, no time)
    assert records[0]["published_at"] == "2026-07-17"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {"dates": ["2026-07-17"]}


def test_write_html_node_skips_index_file_for_empty_digest(tmp_path):
    state = _base_state(tmp_path, [])

    write_html_node(state)

    assert not (tmp_path / "2026-07-17.json").exists()
    manifest = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert manifest == {"dates": []}
