from langchain_core.messages import HumanMessage, SystemMessage

from news_buddy import llm


def test_nvidia_chat_model_calls_hosted_nim(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": '{"summary":"ready"}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }

    def fake_post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return FakeResponse()

    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-token")
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    model = llm.get_sub_model(
        {
            "llm": {
                "provider": "nvidia",
                "sub_model": "meta/llama-3.1-8b-instruct",
                "temperature": 0.2,
                "top_p": 0.7,
                "max_tokens": 600,
                "timeout": 45,
            }
        }
    )

    response = model.invoke(
        [SystemMessage(content="Return JSON."), HumanMessage(content="Summarize.")]
    )

    assert response.content == '{"summary":"ready"}'
    assert response.usage_metadata == {"input_tokens": 11, "output_tokens": 7}
    assert len(calls) == 1
    url, headers, payload, timeout = calls[0]
    assert url == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer test-nvidia-token"
    assert payload["model"] == "meta/llama-3.1-8b-instruct"
    assert payload["messages"] == [
        {"role": "system", "content": "Return JSON."},
        {"role": "user", "content": "Summarize."},
    ]
    assert payload["temperature"] == 0.2
    assert payload["top_p"] == 0.7
    assert payload["max_tokens"] == 600
    assert payload["stream"] is False
    assert timeout == 45


def test_nvidia_chat_model_requires_api_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    try:
        llm.get_sub_model(
            {
                "llm": {
                    "provider": "nvidia",
                    "sub_model": "meta/llama-3.1-8b-instruct",
                }
            }
        )
    except RuntimeError as exc:
        assert "NVIDIA_API_KEY is not set" in str(exc)
    else:
        raise AssertionError("missing NVIDIA_API_KEY should fail")
