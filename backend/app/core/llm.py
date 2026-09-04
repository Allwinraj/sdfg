from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml

from app.core.settings import ModelRole, Settings

logger = logging.getLogger("nexus.llm")

JSON_REPAIR_SUFFIX = (
    "\n\nYour previous reply was not valid JSON matching the required schema. "
    "Reply with JSON only, no markdown."
)


class LLMError(Exception):
    """Base LLM failure."""


class LLMRetryExhausted(LLMError):
    """Retries exhausted after transient HTTP failures."""


class LLMOutputError(LLMError):
    """Response could not be parsed or failed schema validation."""


def _load_ai_models(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _schema_types(schema: dict[str, Any]) -> list[str]:
    expected = schema.get("type")
    if expected is None:
        return []
    if isinstance(expected, list):
        return [str(item) for item in expected]
    return [str(expected)]


def _validate_json_schema(data: Any, schema: dict[str, Any], path: str = "$") -> None:
    types = _schema_types(schema)
    if not types:
        return
    if data is None:
        if "null" in types:
            return
        raise LLMOutputError(f"{path} expected {types[0]}")
    candidates = [t for t in types if t != "null"]
    if len(candidates) > 1:
        last_error: LLMOutputError | None = None
        for candidate in candidates:
            try:
                _validate_json_schema(data, {**schema, "type": candidate}, path)
                return
            except LLMOutputError as exc:
                last_error = exc
        raise last_error or LLMOutputError(f"{path} expected one of {candidates}")
    expected = candidates[0] if candidates else types[0]
    if expected == "object":
        if not isinstance(data, dict):
            raise LLMOutputError(f"{path} expected object, got {type(data).__name__}")
        for key in schema.get("required", []):
            if key not in data:
                raise LLMOutputError(f"{path} missing required property {key!r}")
        props = schema.get("properties") or {}
        for key, sub in props.items():
            if key in data:
                _validate_json_schema(data[key], sub, f"{path}.{key}")
        return
    if expected == "array":
        if not isinstance(data, list):
            raise LLMOutputError(f"{path} expected array, got {type(data).__name__}")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(data):
                _validate_json_schema(item, item_schema, f"{path}[{i}]")
        return
    if expected == "string" and not isinstance(data, str):
        raise LLMOutputError(f"{path} expected string")
    if expected == "number" and (
        not isinstance(data, (int, float)) or isinstance(data, bool)
    ):
        raise LLMOutputError(f"{path} expected number")
    if expected == "integer" and not (
        isinstance(data, int) and not isinstance(data, bool)
    ):
        if isinstance(data, float) and data.is_integer():
            return
        raise LLMOutputError(f"{path} expected integer")
    if expected == "boolean" and not isinstance(data, bool):
        raise LLMOutputError(f"{path} expected boolean")
    if expected == "null" and data is not None:
        raise LLMOutputError(f"{path} expected null")


def _default_for_schema(schema: dict[str, Any] | None) -> Any:
    types = _schema_types(schema or {})
    if "array" in types:
        return []
    if "object" in types:
        return {}
    if "string" in types:
        return ""
    if "integer" in types:
        return 0
    if "number" in types:
        return 0.0
    if "boolean" in types:
        return False
    return None


def _coerce_to_schema(data: Any, schema: dict[str, Any]) -> Any:
    types = _schema_types(schema)
    if not types:
        return data
    if "object" in types and isinstance(data, list):
        required = schema.get("required") or []
        props = schema.get("properties") or {}
        if len(required) == 1 and "array" in _schema_types(props.get(required[0]) or {}):
            data = {required[0]: data}
    if "object" in types:
        if data is None:
            data = {}
        if not isinstance(data, dict):
            return _default_for_schema(schema)
        props = schema.get("properties") or {}
        required = list(schema.get("required") or [])
        out: dict[str, Any] = {}
        keys = set(data) | set(required)
        for key in keys:
            sub = props.get(key) or {}
            if key in data:
                coerced = _coerce_to_schema(data[key], sub) if sub else data[key]
            else:
                coerced = _default_for_schema(sub)
            if coerced is None and key not in required:
                continue
            if coerced is None and key in required:
                coerced = _default_for_schema(sub)
            out[key] = coerced
        return out
    if "array" in types:
        if data is None:
            return []
        if not isinstance(data, list):
            data = [data]
        item_schema = schema.get("items")
        if not item_schema:
            return data
        cleaned = []
        for item in data:
            coerced = _coerce_to_schema(item, item_schema)
            if coerced is not None:
                cleaned.append(coerced)
        return cleaned
    if data is None:
        return _default_for_schema(schema)
    if "string" in types and not isinstance(data, str):
        if isinstance(data, (int, float, bool)):
            return str(data)
        return _default_for_schema(schema)
    if "integer" in types and isinstance(data, float) and data.is_integer():
        return int(data)
    if "number" in types and isinstance(data, bool):
        return 0.0
    return data


def _load_json_object(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    parsed = _coerce_to_schema(_extract_json(text), schema)
    _validate_json_schema(parsed, schema)
    if not isinstance(parsed, dict):
        raise LLMOutputError("top-level JSON must be an object")
    return parsed


def _extract_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner = "\n".join(lines[1:])
        if inner.rstrip().endswith("```"):
            inner = inner.rstrip()[:-3]
        stripped = inner.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end > start:
            return json.loads(stripped[start : end + 1])
        raise


class LLMProvider(Protocol):
    async def complete(
        self,
        model_role: ModelRole,
        prompt: str,
        temperature: float = 0.0,
    ) -> str: ...

    async def complete_json(
        self,
        model_role: ModelRole,
        prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]: ...


class _RetryingMixin:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _request_with_retry(self, send) -> httpx.Response:
        delay = self.settings.llm_retry_base_seconds
        last_exc: Exception | None = None
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                response = await send()
                if response.status_code in {429, 503, 502, 504}:
                    last_exc = LLMError(
                        f"transient HTTP {response.status_code}: {response.text[:300]}"
                    )
                    if attempt >= self.settings.llm_max_retries:
                        break
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                raise LLMError(str(exc)) from exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= self.settings.llm_max_retries:
                    break
                await asyncio.sleep(delay)
                delay *= 2
        raise LLMRetryExhausted(str(last_exc)) from last_exc

    async def complete_json(
        self,
        model_role: ModelRole,
        prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        schema_hint = json.dumps(schema)
        body = (
            f"{prompt}\n\nRespond with JSON only that matches this JSON Schema:\n{schema_hint}"
        )
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_json_repair_attempts + 1):
            text = await self.complete(model_role, body, temperature)
            try:
                return _load_json_object(text, schema)
            except (json.JSONDecodeError, LLMOutputError) as exc:
                last_error = exc
                body = text + JSON_REPAIR_SUFFIX
                logger.warning("llm json repair attempt %s: %s", attempt + 1, exc)
        raise LLMOutputError(str(last_error)) from last_error


class GeminiProvider(_RetryingMixin):
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        super().__init__(settings)
        self._client = client

    def _model(self, role: ModelRole) -> str:
        return self.settings.gemini_model_for(role)

    async def complete(
        self,
        model_role: ModelRole,
        prompt: str,
        temperature: float = 0.0,
    ) -> str:
        if not self.settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        url = (
            f"{self.settings.gemini_base_url.rstrip('/')}"
            f"/models/{self._model(model_role)}:generateContent"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "text/plain",
            },
        }

        async def send() -> httpx.Response:
            client = self._client or httpx.AsyncClient(timeout=60.0)
            owns = self._client is None
            try:
                return await client.post(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "X-goog-api-key": self.settings.gemini_api_key,
                    },
                    json=payload,
                )
            finally:
                if owns:
                    await client.aclose()

        response = await self._request_with_retry(send)
        body = response.json()
        try:
            return body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMOutputError(f"unexpected Gemini shape: {body!r}"[:500]) from exc

    async def complete_json(
        self,
        model_role: ModelRole,
        prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        schema_hint = json.dumps(schema)
        body = (
            f"{prompt}\n\nRespond with JSON only that matches this JSON Schema:\n{schema_hint}"
        )
        if not self.settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        url = (
            f"{self.settings.gemini_base_url.rstrip('/')}"
            f"/models/{self._model(model_role)}:generateContent"
        )
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_json_repair_attempts + 1):
            payload = {
                "contents": [{"parts": [{"text": body}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "responseMimeType": "application/json",
                },
            }

            async def send() -> httpx.Response:
                client = self._client or httpx.AsyncClient(timeout=60.0)
                owns = self._client is None
                try:
                    return await client.post(
                        url,
                        headers={
                            "Content-Type": "application/json",
                            "X-goog-api-key": self.settings.gemini_api_key,
                        },
                        json=payload,
                    )
                finally:
                    if owns:
                        await client.aclose()

            try:
                response = await self._request_with_retry(send)
                text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                return _load_json_object(text, schema)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError, LLMOutputError) as exc:
                last_error = exc
                body = body + JSON_REPAIR_SUFFIX
                logger.warning("gemini json repair attempt %s: %s", attempt + 1, exc)
        raise LLMOutputError(str(last_error)) from last_error


class SAPTokenCache:
    def __init__(self) -> None:
        self.access_token: str | None = None
        self.expires_at: datetime | None = None

    def get(self) -> str | None:
        if not self.access_token or not self.expires_at:
            return None
        if datetime.now(timezone.utc) >= self.expires_at:
            return None
        return self.access_token

    def set(self, token: str, expires_in: int) -> None:
        skew = min(60, max(expires_in // 10, 5))
        self.access_token = token
        self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - skew)


class SAPAICoreProvider(_RetryingMixin):
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        token_cache: SAPTokenCache | None = None,
    ) -> None:
        super().__init__(settings)
        self._client = client
        self.token_cache = token_cache or SAPTokenCache()

    def _token_url(self) -> str:
        base = self.settings.xsuaa_url.rstrip("/")
        if base.endswith("/oauth/token"):
            return base
        return f"{base}/oauth/token"

    def _chat_url(self, deployment_id: str) -> str:
        api = self.settings.aicore_api_url.rstrip("/")
        return (
            f"{api}/v2/inference/deployments/{deployment_id}/chat/completions"
            f"?api-version={self.settings.aicore_openai_api_version}"
        )

    async def _token(self) -> str:
        cached = self.token_cache.get()
        if cached:
            return cached
        if not (
            self.settings.xsuaa_url
            and self.settings.xsuaa_client_id
            and self.settings.xsuaa_client_secret
        ):
            raise LLMError("SAP AI Core XSUAA credentials are not set")

        async def send() -> httpx.Response:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            owns = self._client is None
            try:
                return await client.post(
                    self._token_url(),
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.settings.xsuaa_client_id,
                        "client_secret": self.settings.xsuaa_client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            finally:
                if owns:
                    await client.aclose()

        response = await self._request_with_retry(send)
        body = response.json()
        token = body.get("access_token")
        expires_in = int(body.get("expires_in") or 3600)
        if not token:
            raise LLMError("XSUAA token response missing access_token")
        self.token_cache.set(token, expires_in)
        return token

    async def complete(
        self,
        model_role: ModelRole,
        prompt: str,
        temperature: float = 0.0,
    ) -> str:
        deployment = self.settings.sap_deployment_for(model_role)
        if not deployment:
            raise LLMError(f"no SAP AI Core deployment id for role {model_role}")
        token = await self._token()

        async def send() -> httpx.Response:
            client = self._client or httpx.AsyncClient(timeout=90.0)
            owns = self._client is None
            try:
                return await client.post(
                    self._chat_url(deployment),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "AI-Resource-Group": self.settings.aicore_resource_group,
                        "Content-Type": "application/json",
                    },
                    json={
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                    },
                )
            finally:
                if owns:
                    await client.aclose()

        response = await self._request_with_retry(send)
        body = response.json()
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMOutputError(f"unexpected SAP AI Core shape: {body!r}"[:500]) from exc

    async def complete_json(
        self,
        model_role: ModelRole,
        prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        schema_hint = json.dumps(schema)
        body_prompt = (
            f"{prompt}\n\nRespond with JSON only that matches this JSON Schema:\n{schema_hint}"
        )
        deployment = self.settings.sap_deployment_for(model_role)
        if not deployment:
            raise LLMError(f"no SAP AI Core deployment id for role {model_role}")
        last_error: Exception | None = None
        for attempt in range(self.settings.llm_json_repair_attempts + 1):
            token = await self._token()
            payload = {
                "messages": [{"role": "user", "content": body_prompt}],
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            }

            async def send() -> httpx.Response:
                client = self._client or httpx.AsyncClient(timeout=90.0)
                owns = self._client is None
                try:
                    return await client.post(
                        self._chat_url(deployment),
                        headers={
                            "Authorization": f"Bearer {token}",
                            "AI-Resource-Group": self.settings.aicore_resource_group,
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                finally:
                    if owns:
                        await client.aclose()

            try:
                response = await self._request_with_retry(send)
                text = response.json()["choices"][0]["message"]["content"]
                return _load_json_object(text, schema)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError, LLMOutputError) as exc:
                last_error = exc
                body_prompt = body_prompt + JSON_REPAIR_SUFFIX
                logger.warning("sap json repair attempt %s: %s", attempt + 1, exc)
        raise LLMOutputError(str(last_error)) from last_error


def build_llm_provider(
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> LLMProvider:
    settings = settings or Settings()
    _load_ai_models(settings.ai_models_path)
    if settings.llm_provider == "gemini":
        return GeminiProvider(settings, client=client)
    if settings.llm_provider == "sap_ai_core":
        return SAPAICoreProvider(settings, client=client)
    raise LLMError(f"unknown LLM_PROVIDER {settings.llm_provider!r}")
