from pathlib import Path

from news_buddy import paths


def test_runtime_root_uses_explicit_home(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEWS_BUDDY_HOME", str(data_root))

    assert paths.runtime_root() == data_root.resolve()


def test_installed_package_uses_current_directory_for_writable_data(
    monkeypatch, tmp_path
):
    package_root = tmp_path / "site-packages" / "news_buddy"
    source_root = package_root.parent
    working_dir = tmp_path / "work"
    working_dir.mkdir()
    monkeypatch.delenv("NEWS_BUDDY_HOME", raising=False)
    monkeypatch.setattr(paths, "_SOURCE_ROOT", source_root)
    monkeypatch.chdir(working_dir)

    assert paths.runtime_root() == working_dir.resolve()


def test_default_config_falls_back_to_bundled_resource(monkeypatch, tmp_path):
    source_root = tmp_path / "site-packages"
    bundled_root = source_root / "news_buddy" / "resources"
    bundled_root.mkdir(parents=True)
    bundled_config = bundled_root / "config.yaml"
    bundled_config.write_text("feeds: []\n", encoding="utf-8")
    working_dir = tmp_path / "work"
    working_dir.mkdir()

    monkeypatch.delenv("NEWS_BUDDY_HOME", raising=False)
    monkeypatch.setattr(paths, "_SOURCE_ROOT", source_root)
    monkeypatch.setattr(paths, "_BUNDLED_ROOT", bundled_root)
    monkeypatch.chdir(working_dir)

    assert paths.default_config_path() == bundled_config


def test_checkout_resource_overrides_bundled_copy(monkeypatch, tmp_path):
    source_root = tmp_path / "checkout"
    bundled_root = tmp_path / "site-packages" / "news_buddy" / "resources"
    source_prompt = source_root / "prompts" / "summarizer.md"
    source_prompt.parent.mkdir(parents=True)
    source_prompt.write_text("source", encoding="utf-8")
    bundled_prompt = bundled_root / "prompts" / "summarizer.md"
    bundled_prompt.parent.mkdir(parents=True)
    bundled_prompt.write_text("bundled", encoding="utf-8")

    monkeypatch.setattr(paths, "_SOURCE_ROOT", source_root)
    monkeypatch.setattr(paths, "_BUNDLED_ROOT", bundled_root)

    assert paths.resource_path(Path("prompts/summarizer.md")) == source_prompt
