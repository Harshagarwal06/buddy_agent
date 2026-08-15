from scripts.eval_image_judge import ImageJudge, parse_verdict


def test_parse_verdict_reads_plain_json():
    verdict = parse_verdict('{"has_text": true, "has_person": false, "object_group_count": 3}')
    assert verdict.has_text is True
    assert verdict.has_person is False
    assert verdict.object_group_count == 3
    assert verdict.error == ""


def test_parse_verdict_tolerates_code_fences():
    raw = '```json\n{"has_text": false, "has_person": false, "object_group_count": 2}\n```'
    verdict = parse_verdict(raw)
    assert verdict.has_text is False
    assert verdict.object_group_count == 2


def test_parse_verdict_reports_invalid_json_as_error():
    verdict = parse_verdict("I am not JSON")
    assert verdict.has_text is None
    assert verdict.has_person is None
    assert verdict.error


def test_parse_verdict_rejects_missing_keys():
    """A partial verdict must not be silently treated as clean."""
    verdict = parse_verdict('{"has_text": true}')
    assert verdict.has_person is None
    assert verdict.error


def test_parse_verdict_rejects_non_boolean_flags():
    verdict = parse_verdict('{"has_text": "yes", "has_person": false, "object_group_count": 3}')
    assert verdict.has_text is None
    assert verdict.error


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, text, raises=None):
        self._text = text
        self._raises = raises
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append(model)
        if self._raises:
            raise self._raises
        return _FakeResponse(self._text)


class _FakeClient:
    def __init__(self, text, raises=None):
        self.models = _FakeModels(text, raises)


def test_judge_returns_parsed_verdict():
    client = _FakeClient('{"has_text": true, "has_person": true, "object_group_count": 1}')
    verdict = ImageJudge(client=client).judge(b"fake-bytes")
    assert verdict.has_text is True
    assert verdict.has_person is True
    assert client.models.calls == ["gemini-3.5-flash"]


def test_judge_converts_api_errors_into_error_verdicts():
    client = _FakeClient("", raises=RuntimeError("upstream exploded"))
    verdict = ImageJudge(client=client).judge(b"fake-bytes")
    assert verdict.has_text is None
    assert "upstream exploded" in verdict.error
