import json

import pytest

from scripts.eval_image import load_topics


def test_load_topics_maps_url_to_stratum(tmp_path):
    path = tmp_path / "topics.json"
    path.write_text(json.dumps({"mechanism": ["u1", "u2"], "person": ["u3"]}))
    topics = load_topics(path)
    assert topics == {"u1": "mechanism", "u2": "mechanism", "u3": "person"}


def test_load_topics_rejects_a_url_in_both_strata(tmp_path):
    path = tmp_path / "topics.json"
    path.write_text(json.dumps({"mechanism": ["u1"], "person": ["u1"]}))
    with pytest.raises(ValueError, match="both strata"):
        load_topics(path)


def test_load_topics_rejects_unknown_strata(tmp_path):
    path = tmp_path / "topics.json"
    path.write_text(json.dumps({"mechanism": ["u1"], "vibes": ["u2"]}))
    with pytest.raises(ValueError, match="unknown stratum"):
        load_topics(path)
