"""The open-weight fallbacks (afinamentos, Modal then Baseten): answer only when the model before is unavailable, and
record who answered."""

import asyncio

import pytest

import httpx

from app.core.errors import ServiceNotConfiguredError, UpstreamServiceError, UpstreamUnavailableError
from app.integrations.meta.client import MetaChatModel
from app.integrations.meta.fallback import FallbackChatModel, fallbacks_within_budget
from app.services.permit.model import ChatResult


class _Model:
    def __init__(self, model_id: str, fail: Exception | None = None) -> None:
        self.model_id, self._fail, self.calls = model_id, fail, 0

    async def chat(self, messages, *, tools=None, response_schema=None, schema_name=None) -> ChatResult:
        self.calls += 1
        await asyncio.sleep(0)
        if self._fail:
            raise self._fail
        return ChatResult(content=f'{{"by": "{self.model_id}"}}', tool_calls=[], finish_reason="stop", usage={})


def _run(coro):
    return asyncio.run(coro)


def test_primary_answers_and_fallback_is_never_called():
    primary, fallback = _Model("muse-spark-1.3"), _Model("open-weight")
    model = FallbackChatModel(primary, fallback)

    async def go():
        result = await model.chat([{"role": "user", "content": "{}"}])
        return result, model.model_id

    result, answered = _run(go())
    assert '"muse-spark-1.3"' in result.content and answered == "muse-spark-1.3"
    assert fallback.calls == 0


def test_unavailable_primary_falls_back_and_records_the_fallback():
    primary, fallback = _Model("muse-spark-1.3", UpstreamUnavailableError("down")), _Model("open-weight")
    model = FallbackChatModel(primary, fallback)

    async def go():
        result = await model.chat([{"role": "user", "content": "{}"}], response_schema={"type": "object"},
                                  schema_name="draft")
        return result, model.model_id

    result, answered = _run(go())
    assert '"open-weight"' in result.content and answered == "open-weight"
    assert (primary.calls, fallback.calls) == (1, 1)


@pytest.mark.parametrize("error", [ServiceNotConfiguredError("no key"), ValueError("malformed"),
                                   UpstreamServiceError("refused or broken answer")])
def test_other_failures_do_not_fall_back(error):
    """Only an unavailable primary falls back: never a way around a refusal, a bad answer or a missing key."""
    primary, fallback = _Model("muse-spark-1.3", error), _Model("open-weight")
    with pytest.raises(type(error)):
        _run(FallbackChatModel(primary, fallback).chat([{"role": "user", "content": "{}"}]))
    assert fallback.calls == 0


def test_modal_then_baseten():
    primary = _Model("muse-spark-1.3", UpstreamUnavailableError("down"))
    modal, baseten = _Model("modal-oss", UpstreamUnavailableError("down too")), _Model("baseten-oss")
    model = FallbackChatModel(primary, modal, baseten)

    async def go():
        result = await model.chat([{"role": "user", "content": "{}"}])
        return result, model.model_id

    result, answered = _run(go())
    assert answered == "baseten-oss" and (primary.calls, modal.calls, baseten.calls) == (1, 1, 1)


def test_a_refusal_from_modal_stops_the_chain():
    primary = _Model("muse-spark-1.3", UpstreamUnavailableError("down"))
    modal, baseten = _Model("modal-oss", UpstreamServiceError("refused")), _Model("baseten-oss")
    with pytest.raises(UpstreamServiceError):
        _run(FallbackChatModel(primary, modal, baseten).chat([{"role": "user", "content": "{}"}]))
    assert baseten.calls == 0


def test_all_unavailable_raises_unavailable():
    model = FallbackChatModel(_Model("a", UpstreamUnavailableError("down")), _Model("b", UpstreamUnavailableError("x")))
    with pytest.raises(UpstreamUnavailableError):
        _run(model.chat([{"role": "user", "content": "{}"}]))


def test_a_fallback_is_required():
    with pytest.raises(ValueError):
        FallbackChatModel(_Model("a"))


def test_concurrent_requests_record_their_own_model():
    """One request on the fallback never relabels another request answered by the primary."""

    class _Flaky(_Model):
        async def chat(self, messages, **kw):
            if messages[0]["content"] == "fail":
                self.calls += 1
                await asyncio.sleep(0)
                raise UpstreamUnavailableError("down")
            return await super().chat(messages, **kw)

    model = FallbackChatModel(_Flaky("muse-spark-1.3"), _Model("open-weight"))

    async def one(content):
        await model.chat([{"role": "user", "content": content}])
        await asyncio.sleep(0)
        return model.model_id

    async def go():
        return await asyncio.gather(one("fail"), one("ok"), one("fail"), one("ok"))

    assert _run(go()) == ["open-weight", "muse-spark-1.3", "open-weight", "muse-spark-1.3"]


def test_before_any_call_the_primary_is_reported():
    assert FallbackChatModel(_Model("muse-spark-1.3"), _Model("open-weight")).model_id == "muse-spark-1.3"


def _client(status: int, body: object = None) -> MetaChatModel:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body if body is not None else {"error": "x"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MetaChatModel(http, api_key="k", base_url="https://example.invalid/v1", model_id="muse-spark-1.3")


@pytest.mark.parametrize("status", [500, 503, 429])
def test_client_outage_is_unavailable(status, monkeypatch):
    monkeypatch.setattr("app.integrations.meta.client.asyncio.sleep", lambda *_, _real=asyncio.sleep: _real(0))
    with pytest.raises(UpstreamUnavailableError):
        _run(_client(status).chat([{"role": "user", "content": "{}"}]))


def test_client_transport_error_is_unavailable(monkeypatch):
    monkeypatch.setattr("app.integrations.meta.client.asyncio.sleep", lambda *_, _real=asyncio.sleep: _real(0))

    async def handler(request):
        raise httpx.ConnectTimeout("timeout")

    model = MetaChatModel(httpx.AsyncClient(transport=httpx.MockTransport(handler)), api_key="k",
                          base_url="https://example.invalid/v1", model_id="m")
    with pytest.raises(UpstreamUnavailableError):
        _run(model.chat([{"role": "user", "content": "{}"}]))


@pytest.mark.parametrize("status,body", [(400, None), (403, None), (200, {"choices": []})])
def test_client_refusal_or_broken_answer_is_not_unavailable(status, body):
    with pytest.raises(UpstreamServiceError) as caught:
        _run(_client(status, body).chat([{"role": "user", "content": "{}"}]))
    assert not isinstance(caught.value, UpstreamUnavailableError)


def _app(**overrides):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    values = {"_env_file": None, "google_maps_api_key": "k", "mongodb_uri": None, "app_env": "test",
              "allow_ephemeral_storage": True, "meta_api_key": "secret-meta-key"}
    return TestClient(create_app(Settings(**{**values, **overrides}),
                                 meta_transport=httpx.MockTransport(lambda r: httpx.Response(503))))


def test_wiring_off_by_default():
    with _app() as client:
        assert isinstance(client.app.state.permit_workflow._model, MetaChatModel)


def test_wiring_modal_then_baseten_for_the_workflow_only():
    with _app(modal_model_base_url="https://modal.invalid/v1", modal_model_api_key="mk", modal_model_id="llama-modal",
              baseten_model_base_url="https://baseten.invalid/v1", baseten_model_api_key="bk",
              baseten_model_id="llama-baseten") as client:
        workflow_model = client.app.state.permit_workflow._model
        assert isinstance(workflow_model, FallbackChatModel)
        assert [m.model_id for m in workflow_model._chain] == ["muse-spark-1.3", "llama-modal", "llama-baseten"]
        # The user's private photos and plans are read by Muse Spark only.
        assert isinstance(client.app.state.matter_files._model, MetaChatModel)


def test_wiring_skips_a_half_configured_provider():
    with _app(modal_model_base_url="https://modal.invalid/v1", modal_model_id="llama-modal",
              baseten_model_base_url="https://baseten.invalid/v1", baseten_model_api_key="bk",
              baseten_model_id="llama-baseten") as client:
        assert [m.model_id for m in client.app.state.permit_workflow._model._chain] == ["muse-spark-1.3",
                                                                                         "llama-baseten"]


def test_fallback_clients_try_once_with_their_own_timeout():
    with _app(modal_model_base_url="https://modal.invalid/v1", modal_model_api_key="mk",
              modal_model_id="llama-modal") as client:
        modal = client.app.state.permit_workflow._model._chain[1]
        assert modal._attempts == 1 and modal._http.timeout.read == 45.0 and modal._deadline == 45.0


def test_one_attempt_client_does_not_retry():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(503, json={})

    model = MetaChatModel(httpx.AsyncClient(transport=httpx.MockTransport(handler)), api_key="k",
                          base_url="https://example.invalid/v1", model_id="m", attempts=1)
    with pytest.raises(UpstreamUnavailableError):
        _run(model.chat([{"role": "user", "content": "{}"}]))
    assert len(calls) == 1


def test_an_attempt_has_a_total_deadline_not_only_per_read_timeouts():
    """Codex r3: a server that trickles bytes defeats httpx's per-read timeouts; the attempt still ends on time."""
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(5)  # each read would be within its timeout; the whole call is not
        return httpx.Response(200, json={})

    model = MetaChatModel(httpx.AsyncClient(transport=httpx.MockTransport(handler)), api_key="k",
                          base_url="https://example.invalid/v1", model_id="m", attempts=1, deadline_seconds=0.05)

    async def timed():
        started = asyncio.get_running_loop().time()
        with pytest.raises(UpstreamUnavailableError):
            await model.chat([{"role": "user", "content": "{}"}])
        return asyncio.get_running_loop().time() - started

    assert _run(timed()) < 1.0
    assert len(calls) == 1


def test_the_deadline_defaults_to_the_clients_read_timeout():
    model = MetaChatModel(httpx.AsyncClient(timeout=45.0), api_key="k", base_url="https://example.invalid/v1",
                          model_id="m")
    assert model._deadline == 45.0


def test_fallbacks_that_cannot_answer_before_cloud_run_ends_the_request_are_not_wired():
    """Codex r4: META_TIMEOUT_SECONDS=120 with two 45 s fallbacks would end at 330.5 s, past Cloud Run's 300 s."""
    modal, baseten = _Model("llama-modal"), _Model("llama-baseten")
    assert fallbacks_within_budget([modal, baseten], 90, 45) == [modal, baseten]  # 271 s
    assert fallbacks_within_budget([modal, baseten], 120, 45) == [modal]  # 285.5 s with Modal only
    assert fallbacks_within_budget([modal, baseten], 150, 45) == []


def test_wiring_drops_a_fallback_past_the_request_budget():
    with _app(meta_timeout_seconds=120, modal_model_base_url="https://modal.invalid/v1", modal_model_api_key="mk",
              modal_model_id="llama-modal", baseten_model_base_url="https://baseten.invalid/v1",
              baseten_model_api_key="bk", baseten_model_id="llama-baseten") as client:
        assert [m.model_id for m in client.app.state.permit_workflow._model._chain] == ["muse-spark-1.3",
                                                                                         "llama-modal"]
