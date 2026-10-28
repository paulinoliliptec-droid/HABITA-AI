import json

import httpx
import pytest

from app.core.errors import ServiceNotConfiguredError, UpstreamServiceError
from app.integrations.meta.client import MetaChatModel

KEY = "meta-key-must-never-leak"


def model_with(handler, key: str | None = KEY, **kw) -> MetaChatModel:
    return MetaChatModel(httpx.AsyncClient(transport=httpx.MockTransport(handler)), api_key=key,
                         base_url="https://api.meta.ai/v1", model_id="muse-spark-1.3", **kw)


def completion(message: dict, finish="stop") -> dict:
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


async def test_request_shape_with_tools_and_structured_output():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=completion({"content": "{\"a\": 1}"}))

    tools = [{"type": "function", "function": {"name": "t", "parameters": {"type": "object", "properties": {}}}}]
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"], "additionalProperties": False}
    result = await model_with(handler, reasoning_effort="medium").chat(
        [{"role": "user", "content": "hi"}], tools=tools, response_schema=schema, schema_name="thing"
    )
    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://api.meta.ai/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert body["model"] == "muse-spark-1.3"
    assert body["tools"] == tools
    assert "tool_choice" not in body  # Meta only supports "auto", the default
    assert body["response_format"] == {"type": "json_schema", "json_schema": {"name": "thing", "schema": schema, "strict": True}}
    assert body["reasoning_effort"] == "medium"
    assert result.content == "{\"a\": 1}" and result.usage["prompt_tokens"] == 10


async def test_tool_calls_are_parsed():
    message = {"content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": "search_regulatory_sources",
                                                          "arguments": "{\"topics\": [\"unit_division\"], \"query\": \"q\"}"}},
    ]}
    result = await model_with(lambda r: httpx.Response(200, json=completion(message, "tool_calls"))).chat([])
    assert result.finish_reason == "tool_calls"
    assert result.tool_calls[0].name == "search_regulatory_sources"
    assert result.tool_calls[0].arguments == {"topics": ["unit_division"], "query": "q"}


async def test_missing_key_is_not_configured():
    with pytest.raises(ServiceNotConfiguredError):
        await model_with(lambda r: httpx.Response(200), key=None).chat([])


def test_contributor_models_are_refused():
    with pytest.raises(ValueError):
        MetaChatModel(httpx.AsyncClient(), api_key=KEY, base_url="https://api.meta.ai/v1", model_id="muse-spark-1.3-contributor")


async def test_server_error_is_retried_once():
    responses = iter([httpx.Response(503), httpx.Response(200, json=completion({"content": "ok"}))])
    assert (await model_with(lambda r: next(responses)).chat([])).content == "ok"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": {"message": f"bad key {KEY}"}}),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json=completion({"tool_calls": [{"id": "1", "function": {"name": "t", "arguments": "[1]"}}]})),
    ],
    ids=["auth-error", "non-json", "no-choices", "non-object-arguments"],
)
async def test_failures_are_upstream_errors_and_never_leak_the_key(response, caplog):
    with pytest.raises(UpstreamServiceError) as exc:
        await model_with(lambda r: response).chat([])
    assert KEY not in exc.value.message
    assert KEY not in caplog.text
