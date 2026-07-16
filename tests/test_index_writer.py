import json

from news_buddy.index_writer import write_index, write_manifest


def test_write_index_creates_json_with_expected_fields(tmp_path):
    items = [
        {
            "title": "Model launches",
            "url": "https://example.test/a",
            "source": "Test Feed",
            "published_at": "2026-07-17",
            "summary": "A new model launched today.",
            "tags": ["ai", "product"],
            "importance": 4,
        }
    ]

    path = write_index(tmp_path, "2026-07-17", items)

    assert path == tmp_path / "2026-07-17.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == items


def test_write_index_defaults_missing_fields(tmp_path):
    path = write_index(tmp_path, "2026-07-17", [{"url": "https://example.test/b"}])

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == [
        {
            "title": "",
            "url": "https://example.test/b",
            "source": "",
            "published_at": "",
            "summary": "",
            "tags": [],
            "importance": 3,
        }
    ]


def test_write_manifest_lists_dates_newest_first(tmp_path):
    write_index(tmp_path, "2026-07-15", [])
    write_index(tmp_path, "2026-07-17", [])
    write_index(tmp_path, "2026-07-16", [])

    path = write_manifest(tmp_path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"dates": ["2026-07-17", "2026-07-16", "2026-07-15"]}


def test_write_manifest_ignores_non_date_json_files(tmp_path):
    write_index(tmp_path, "2026-07-17", [])
    (tmp_path / "index.json").write_text("{}", encoding="utf-8")
    (tmp_path / "unrelated.json").write_text("{}", encoding="utf-8")

    path = write_manifest(tmp_path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"dates": ["2026-07-17"]}
