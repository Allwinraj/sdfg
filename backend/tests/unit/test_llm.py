from __future__ import annotations

import json

import httpx
import pytest

from app.core.llm import (
    GeminiProvider,
    LLMOutputError,
    LLMRetryExhausted,
    SAPAICoreProvider,
    SAPTokenCache,
    _coerce_to_schema,
    _validate_json_schema,
    build_llm_provider,
)
from app.core.settings import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        llm_provider="gemini",
        gemini_api_key="test-key",
        gemini_model="gemini-flash-lite-latest",
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta",
        llm_max_retries=2,
        llm_retry_base_seconds=0.01,
        xsuaa_url="https://auth.example.com",
        xsuaa_client_id="id",
        xsuaa_client_secret="secret",
        aicore_api_url="https://api.ai.example.com",
        aicore_gpt40_mini_deployment_id="d-mini",
        aicore_gpt55_deployment_id="d-55",
        aicore_gpt41_deployment_id="d-41",
        aicore_gpt40_deployment_id="d-40",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_json_schema_required() -> None:
    with pytest.raises(Exception):
        _validate_json_schema({}, {"type": "object", "required": ["id"]})
    _validate_json_schema({"id": "a"}, {"type": "object", "required": ["id"]})


def test_null_capture_fields_are_dropped() -> None:
    schema = {
        "type": "object",
        "required": ["assistant_message"],
        "properties": {
            "assistant_message": {"type": "string"},
            "capture": {
                "type": ["object", "null"],
                "properties": {
                    "role": {"type": ["string", "null"]},
                    "industry": {"type": ["string", "null"]},
                },
            },
        },
    }
    raw = {
        "assistant_message": "What industry are you in?",
        "capture": {"role": "Treasury analyst", "industry": None},
    }
    cleaned = _coerce_to_schema(raw, schema)
    _validate_json_schema(cleaned, schema)
    assert cleaned["capture"]["role"] == "Treasury analyst"


def test_missing_required_arrays_default_to_empty() -> None:
    facts_schema = {
        "type": "object",
        "required": ["facts"],
        "properties": {"facts": {"type": "array"}},
    }
    cleaned = _coerce_to_schema({"summary": "policy"}, facts_schema)
    _validate_json_schema(cleaned, facts_schema)
    assert cleaned["facts"] == []

    wrapped = _coerce_to_schema([{"id": "a"}], facts_schema)
    _validate_json_schema(wrapped, facts_schema)
    assert wrapped["facts"] == [{"id": "a"}]


def test_interview_turn_missing_fields_are_filled() -> None:
    schema = {
        "type": "object",
        "required": ["assistant_message", "requirements", "capabilities"],
        "properties": {
            "assistant_message": {"type": "string"},
            "requirements": {"type": "array"},
            "capabilities": {"type": "object"},
            "question": {"type": ["string", "null"]},
        },
    }
    cleaned = _coerce_to_schema({"assistant_message": "How should we match?"}, schema)
    _validate_json_schema(cleaned, schema)
    assert cleaned["requirements"] == []
    assert cleaned["capabilities"] == {}


@pytest.mark.asyncio
async def test_gemini_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        body = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(_settings(), client=client)
        text = await provider.complete("extraction", "hi")
    assert text == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_gemini_retry_exhausted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(_settings(llm_max_retries=1), client=client)
        with pytest.raises(LLMRetryExhausted):
            await provider.complete("extraction", "hi")


@pytest.mark.asyncio
async def test_sap_token_cache_and_refresh() -> None:
    calls = {"token": 0, "chat": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            calls["token"] += 1
            token = "tok-1" if calls["token"] == 1 else "tok-2"
            return httpx.Response(
                200,
                json={"access_token": token, "expires_in": 3600},
            )
        calls["chat"] += 1
        auth = request.headers.get("authorization")
        assert auth in {"Bearer tok-1", "Bearer tok-2"}
        assert request.headers.get("ai-resource-group") == "default"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "matched"}}]},
        )

    cache = SAPTokenCache()
    transport = httpx.MockTransport(handler)
    settings = _settings(llm_provider="sap_ai_core")
    async with httpx.AsyncClient(transport=transport) as client:
        provider = SAPAICoreProvider(settings, client=client, token_cache=cache)
        first = await provider.complete("reconciliation", "prompt")
        second = await provider.complete("reconciliation", "prompt")
        cache.expires_at = cache.expires_at.replace(year=2000)  # type: ignore[union-attr]
        third = await provider.complete("extraction", "prompt")
    assert first == second == "matched"
    assert calls["token"] == 2
    assert calls["chat"] == 3
    assert third == "matched"


@pytest.mark.asyncio
async def test_sap_complete_json_matches_gemini_contract() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        calls["n"] += 1
        payload = json.loads(request.content.decode())
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"name": "ok"}'}}]},
        )

    transport = httpx.MockTransport(handler)
    settings = _settings(llm_provider="sap_ai_core")
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    async with httpx.AsyncClient(transport=transport) as client:
        provider = SAPAICoreProvider(settings, client=client)
        data = await provider.complete_json("reasoning", "extract", schema)
    assert data == {"name": "ok"}
    assert calls["n"] == 1


def test_build_provider_switch(monkeypatch) -> None:
    gemini = build_llm_provider(_settings(llm_provider="gemini"))
    sap = build_llm_provider(_settings(llm_provider="sap_ai_core"))
    assert type(gemini).__name__ == "GeminiProvider"
    assert type(sap).__name__ == "SAPAICoreProvider"


@pytest.mark.asyncio
async def test_complete_json_repair() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        payload = json.loads(request.content.decode())
        text = payload["contents"][0]["parts"][0]["text"]
        if "previous reply" not in text:
            body = {"candidates": [{"content": {"parts": [{"text": "not-json"}]}}]}
        else:
            body = {
                "candidates": [
                    {"content": {"parts": [{"text": '{"name": "ok"}'}]}}
                ]
            }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(_settings(), client=client)
        data = await provider.complete_json("extraction", "extract", schema)
    assert data == {"name": "ok"}
    assert calls["n"] == 2
