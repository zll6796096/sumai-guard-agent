from __future__ import annotations

import importlib.util
import io
import json
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from PIL import Image


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _load_web_module() -> object:
    app_path = (
        Path(__file__).resolve().parents[2] / "sumai_web" / "app.py"
    )
    module_name = f"sumai_web_stream_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, app_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_web_stream_forwards_ndjson_chunks_without_rewriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_module = _load_web_module()

    stream_lines = [
        b'{"type":"progress","stage":"intake_complete"}\n',
        b'{"type":"progress","stage":"vision_complete"}\n',
        b'{"type":"result","payload":{"analysis_id":"sumai_test"}}\n',
    ]
    requests: list[httpx.Request] = []

    async def backend_handler(
        request: httpx.Request,
    ) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            content=b"".join(stream_lines),
        )

    backend = httpx.AsyncClient(
        transport=httpx.MockTransport(backend_handler)
    )
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as web_client:
        async with web_client.stream(
            "POST",
            "/analyze/stream",
            files={
                "image": (
                    "toilet.png",
                    _png_bytes(),
                    "image/png",
                )
            },
            data={"room_hint": "toilet"},
        ) as response:
            body = await response.aread()
    await backend.aclose()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/x-ndjson"
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert body == b"".join(stream_lines)
    assert len(requests) == 1
    assert requests[0].url.path == "/analyze/stream"


@pytest.mark.asyncio
async def test_web_stream_sanitizes_strict_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_module = _load_web_module()
    monkeypatch.setattr(
        web_module, "FRONTEND_REQUIRE_REAL_GEMINI", True
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            content=b'{"secret":"provider-secret-body"}',
        )

    backend = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/analyze/stream",
            files={
                "image": (
                    "toilet.png",
                    _png_bytes(),
                    "image/png",
                )
            },
            data={"room_hint": "toilet"},
        )
    await backend.aclose()

    events = [
        json.loads(line)
        for line in response.text.splitlines()
        if line.strip()
    ]
    assert events == [
        {
            "type": "error",
            "error": "gemini_unavailable",
            "message": "解析サービスは現在利用できません。",
        }
    ]
    assert "provider-secret-body" not in response.text


@pytest.mark.asyncio
async def test_web_stream_uses_neutral_result_for_non_strict_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_module = _load_web_module()
    monkeypatch.setattr(
        web_module, "FRONTEND_REQUIRE_REAL_GEMINI", False
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            content=b"untrusted-upstream",
        )

    backend = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/analyze/stream",
            files={
                "image": (
                    "toilet.png",
                    _png_bytes(),
                    "image/png",
                )
            },
            data={"room_hint": "toilet"},
        )
    await backend.aclose()

    event = json.loads(response.text)
    assert event["type"] == "result"
    assert event["payload"]["is_not_applicable"] is True
    assert event["payload"]["findings"] == []
    assert event["payload"]["confirmation_items"] == []
    assert event["payload"]["action_plan"] == {
        "family_no_cost": [],
        "care_manager_purchase": [],
        "contractor_construction": [],
    }
    assert "untrusted-upstream" not in response.text


@pytest.mark.asyncio
async def test_web_stream_sanitizes_upstream_client_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_module = _load_web_module()

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            content=b"private-validation-detail",
        )

    backend = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/analyze/stream",
            files={
                "image": (
                    "toilet.png",
                    _png_bytes(),
                    "image/png",
                )
            },
            data={"room_hint": "toilet"},
        )
    await backend.aclose()

    assert json.loads(response.text) == {
        "type": "error",
        "error": "invalid_upload",
        "message": "画像または入力内容を確認してください。",
    }
    assert "private-validation-detail" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
async def test_web_stream_contains_unexpected_upstream_exception(
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
) -> None:
    web_module = _load_web_module()
    monkeypatch.setattr(
        web_module,
        "FRONTEND_REQUIRE_REAL_GEMINI",
        strict,
    )

    class BrokenBackend:
        def stream(self, *_: object, **__: object) -> None:
            raise RuntimeError("provider-secret-body")

    monkeypatch.setattr(
        web_module,
        "backend_client",
        lambda: BrokenBackend(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/analyze/stream",
            files={
                "image": (
                    "toilet.png",
                    _png_bytes(),
                    "image/png",
                )
            },
            data={"room_hint": "toilet"},
        )

    event = json.loads(response.text)
    if strict:
        assert event == {
            "type": "error",
            "error": "gemini_unavailable",
            "message": "解析サービスは現在利用できません。",
        }
    else:
        assert event["type"] == "result"
        assert event["payload"]["is_not_applicable"] is True
        assert event["payload"]["findings"] == []
        assert event["payload"]["action_plan"] == {
            "family_no_cost": [],
            "care_manager_purchase": [],
            "contractor_construction": [],
        }
    assert "provider-secret-body" not in response.text
