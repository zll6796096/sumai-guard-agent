from __future__ import annotations

import importlib.util
import io
import json
import sys
import uuid
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.models import (
    ActionItem,
    ActionPlan,
    AnalysisResponse,
    BoundingBox,
    ConfirmationItem,
    RiskFinding,
)
from app.ontology import OntologyRepository
from app.services.image_intake import PREPROCESS_VERSION


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


class ChunkStream(httpx.AsyncByteStream):
    def __init__(
        self,
        chunks: list[bytes | Exception],
        *,
        closed: list[bool] | None = None,
    ) -> None:
        self._chunks = chunks
        self._closed = closed

    async def __aiter__(self):
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    async def aclose(self) -> None:
        if self._closed is not None:
            self._closed.append(True)


def _events(response: httpx.Response) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in response.text.splitlines()
        if line.strip()
    ]


def _valid_toilet_payload() -> dict[str, object]:
    return AnalysisResponse(
        analysis_id="sumai_contract",
        room_type="toilet",
        assessment_status="visible_risks_found",
        overall_risk_level="medium",
        findings=[
            RiskFinding(
                id="R1",
                risk_type="cluttered_path",
                label_ja="床の物・動線阻害",
                description_ja="見える範囲の床に物があります。",
                severity=3,
                confidence=0.8,
                bbox=BoundingBox(x=0.1, y=0.2, w=0.2, h=0.2),
                evidence_source_ids=["CAA_FALL_PREVENTION"],
                evidence_ja="床の物が見えます。",
                basis_label_ja="一般注意",
                basis_summary_ja="転倒予防の一般原則です。",
                needs_human_confirmation=False,
                ontology_key="has_floor_clutter",
                ontology_rule_kind="visible_hazard",
            )
        ],
        confirmation_items=[
            ConfirmationItem(
                id="C1",
                feature_key="has_handrail",
                label_ja="手すり",
                description_ja="見える範囲で確認してください。",
                confidence=0.7,
                evidence_source_ids=[],
                basis_label_ja="写真確認",
                basis_summary_ja="写真だけでは断定しません。",
                needs_human_confirmation=True,
            )
        ],
        action_plan=ActionPlan(),
        annotated_image_base64="image",
        improvement_image_base64="image",
        risk_summary_markdown="summary",
        confirmation_items_markdown="confirmations",
        family_actions_markdown="family",
        care_manager_actions_markdown="care",
        contractor_actions_markdown="contractor",
        disclaimer_ja="POC",
        mode="mock",
        model="N/A",
        result_key="result",
        semantic_hash="semantic",
        schema_version="2.2.0",
        ontology_version="1.0.1",
        preprocess_version="1.0.0",
        inference_config_version="1.0.6",
    ).model_dump(mode="json")


def test_web_wire_models_track_agent_public_response_fields() -> None:
    web_module = _load_web_module()

    pairs = (
        (web_module.WireBoundingBox, BoundingBox),
        (web_module.WireFinding, RiskFinding),
        (web_module.WireConfirmationItem, ConfirmationItem),
        (web_module.WireActionItem, ActionItem),
        (web_module.WireActionPlan, ActionPlan),
        (web_module.WireAnalysisResponse, AnalysisResponse),
    )
    for wire_model, agent_model in pairs:
        assert set(wire_model.model_fields) == set(agent_model.model_fields)

    payload = web_module._build_local_mock(
        _png_bytes(), "toilet", "contract_test"
    )
    agent_result = AnalysisResponse.model_validate(payload)
    wire_result = web_module.WireAnalysisResponse.model_validate(payload)
    assert wire_result.model_dump(mode="json") == agent_result.model_dump(
        mode="json"
    )


def test_web_wire_room_and_version_constants_match_current_agent_ontology() -> None:
    web_module = _load_web_module()
    ontology = OntologyRepository.load_default()
    visible: set[tuple[str, str, str]] = set()
    expected: set[tuple[str, str]] = set()
    for room in ontology.room_names:
        room_data = ontology.room(room)
        assert room_data is not None
        visible.update(
            (room, item["key"], item["risk_type"])
            for item in room_data["visible_hazards"]
        )
        expected.update(
            (room, item["key"])
            for item in room_data["expected_features"]
        )

    assert web_module.CURRENT_VISIBLE_FINDING_IDENTITIES == visible
    assert web_module.CURRENT_EXPECTED_CONFIRMATION_IDENTITIES == expected
    assert web_module.CURRENT_FAMILY_FORBIDDEN_WORDS == tuple(
        ontology.action_policy["family"]["forbidden_words"]
    )
    assert web_module.CURRENT_SCHEMA_VERSION == ontology.schema_version
    assert web_module.CURRENT_ONTOLOGY_VERSION == ontology.version
    assert (
        web_module.CURRENT_INFERENCE_CONFIG_VERSION
        == ontology.inference_config_version
    )
    assert web_module.CURRENT_PREPROCESS_VERSION == PREPROCESS_VERSION


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["findings"][0].update(
            ontology_key="invented_hazard"
        ),
        lambda payload: payload["findings"][0].update(
            ontology_key="wet_floor",
            risk_type="bathroom_slip",
        ),
        lambda payload: payload["confirmation_items"][0].update(
            feature_key="invented_feature"
        ),
        lambda payload: payload["confirmation_items"][0].update(
            feature_key="clear_floor"
        ),
        lambda payload: payload["findings"].append(
            deepcopy(payload["findings"][0])
        ),
        lambda payload: payload["confirmation_items"].append(
            {
                **deepcopy(payload["confirmation_items"][0]),
                "id": "C2",
            }
        ),
    ],
)
def test_web_wire_rejects_the_same_room_scoped_adversarial_payloads_as_agent(
    mutate,
) -> None:
    web_module = _load_web_module()
    payload = _valid_toilet_payload()
    mutate(payload)

    with pytest.raises(Exception):
        AnalysisResponse.model_validate(payload)
    with pytest.raises(Exception):
        web_module.WireAnalysisResponse.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "99.0.0"),
        ("ontology_version", "99.0.0"),
        ("preprocess_version", "99.0.0"),
        ("inference_config_version", "99.0.0"),
    ],
)
def test_web_wire_rejects_non_current_contract_versions(
    field: str,
    value: str,
) -> None:
    web_module = _load_web_module()
    payload = _valid_toilet_payload()
    payload[field] = value

    with pytest.raises(Exception):
        web_module.WireAnalysisResponse.model_validate(payload)


def test_web_wire_rejects_duplicate_action_ids_and_family_forbidden_words() -> None:
    web_module = _load_web_module()
    duplicate_ids = _valid_toilet_payload()
    duplicate_ids["action_plan"] = {
        "family_no_cost": [
            {
                "id": "A1",
                "risk_id": "R1",
                "tier": "FAMILY_NO_COST",
                "title_ja": "床を片付ける",
                "description_ja": "無理のない範囲で行います。",
                "why_ja": "動線を確保するためです。",
                "cost_level": "ZERO",
                "requires_professional": False,
                "disclaimer_ja": "一般注意",
            }
        ],
        "care_manager_purchase": [
            {
                "id": "A1",
                "risk_id": "R1",
                "tier": "CARE_MANAGER_PURCHASE",
                "title_ja": "用具を相談する",
                "description_ja": "必要性を確認します。",
                "why_ja": "選択肢を確認するためです。",
                "cost_level": "LOW",
                "requires_professional": True,
                "disclaimer_ja": "一般注意",
            }
        ],
        "contractor_construction": [],
    }

    with pytest.raises(Exception):
        AnalysisResponse.model_validate(duplicate_ids)
    with pytest.raises(Exception):
        web_module.WireAnalysisResponse.model_validate(duplicate_ids)

    forbidden = _valid_toilet_payload()
    forbidden["action_plan"]["family_no_cost"] = [
        {
            "id": "A1",
            "risk_id": "R1",
            "tier": "FAMILY_NO_COST",
            "title_ja": "用具を購入する",
            "description_ja": "家族で対応します。",
            "why_ja": "動線を確保するためです。",
            "cost_level": "ZERO",
            "requires_professional": False,
            "disclaimer_ja": "一般注意",
        }
    ]

    with pytest.raises(Exception):
        AnalysisResponse.model_validate(forbidden)
    with pytest.raises(Exception):
        web_module.WireAnalysisResponse.model_validate(forbidden)


@pytest.mark.asyncio
async def test_web_stream_forwards_ndjson_chunks_without_rewriting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_module = _load_web_module()

    payload = web_module._build_local_mock(
        _png_bytes(), "toilet", "test"
    )
    stream_lines = [
        b'{"type":"progress","stage":"intake_complete"}\n',
        b'{"type":"progress","stage":"vision_complete"}\n',
        (
            json.dumps(
                {"type": "result", "payload": payload},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8"),
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
    assert _events(response) == [
        {"type": "progress", "stage": "intake_complete"},
        {"type": "progress", "stage": "vision_complete"},
        {"type": "result", "payload": payload},
    ]
    assert b"private" not in body
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
async def test_web_stream_validates_and_rewrites_allowlisted_upstream_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_module = _load_web_module()

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            content=(
                b'{"type":"progress","stage":"intake_complete"}\n'
                b'{"type":"error","error":"gemini_unavailable",'
                b'"message":"provider-secret-body"}\n'
            ),
        )

    backend = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/analyze/stream",
            files={"image": ("toilet.png", _png_bytes(), "image/png")},
            data={"room_hint": "toilet"},
        )
    await backend.aclose()

    assert _events(response) == [
        {"type": "progress", "stage": "intake_complete"},
        {
            "type": "error",
            "error": "gemini_unavailable",
            "message": "解析サービスは現在利用できません。",
        },
    ]
    assert "provider-secret-body" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize(
    "chunks",
    [
        [
            b'{"type":"progress","stage":"vision_complete"}\n',
        ],
        [
            b'{"type":"progress","stage":"intake_complete"}\n',
            b'{"type":"progress","stage":"intake_complete"}\n',
        ],
        [
            b'{"type":"progress","stage":"intake_complete"}\n',
            b'{"type":"unknown","private":"provider-secret-body"}\n',
        ],
        [
            b'{"type":"progress","stage":"intake_complete"}\n',
            b'{"type":"error","error":"private-provider-code",'
            b'"message":"provider-secret-body"}\n',
        ],
        [
            b'{"type":"progress","stage":"intake_complete"}\n',
            b'{"type":"progress","stage":"vision_complete"}\n',
            b'{"type":"result","payload":{"analysis_id":"invalid"}}\n',
        ],
        [
            b'{"type":"progress","stage":"intake_complete"}\n',
            b'not-json-provider-secret\n',
        ],
        [
            b'{"type":"progress","stage":"intake_complete"}\n',
            b"\xff\n",
        ],
    ],
)
async def test_web_stream_safely_terminates_invalid_200_protocol(
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
    chunks: list[bytes],
) -> None:
    web_module = _load_web_module()
    monkeypatch.setattr(web_module, "FRONTEND_REQUIRE_REAL_GEMINI", strict)

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            stream=ChunkStream(chunks),
        )

    backend = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/analyze/stream",
            files={"image": ("toilet.png", _png_bytes(), "image/png")},
            data={"room_hint": "toilet"},
        )
    await backend.aclose()

    events = _events(response)
    assert events
    assert events[-1]["type"] == ("error" if strict else "result")
    assert sum(event["type"] in {"error", "result"} for event in events) == 1
    assert "provider-secret" not in response.text
    assert "private-provider" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("failure_mode", ["partial_eof", "partial_exception"])
async def test_web_stream_discards_partial_line_and_emits_one_safe_terminal(
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
    failure_mode: str,
) -> None:
    web_module = _load_web_module()
    monkeypatch.setattr(web_module, "FRONTEND_REQUIRE_REAL_GEMINI", strict)
    chunks: list[bytes | Exception] = [
        b'{"type":"progress","stage":"intake_complete"}\n',
        b'{"type":"progress","stage":"vision_complete"}\n',
        b'{"type":"result","payload":{"private":"provider-secret',
    ]
    if failure_mode == "partial_exception":
        chunks.append(httpx.ReadError("private-stream-failure"))

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            stream=ChunkStream(chunks),
        )

    backend = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/analyze/stream",
            files={"image": ("toilet.png", _png_bytes(), "image/png")},
            data={"room_hint": "toilet"},
        )
    await backend.aclose()

    events = _events(response)
    assert [event["type"] for event in events[:2]] == [
        "progress",
        "progress",
    ]
    assert events[-1]["type"] == ("error" if strict else "result")
    assert sum(event["type"] in {"error", "result"} for event in events) == 1
    assert "provider-secret" not in response.text
    assert "private-stream-failure" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("strict", [False, True])
async def test_web_stream_rejects_wrong_content_type(
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
) -> None:
    web_module = _load_web_module()
    monkeypatch.setattr(web_module, "FRONTEND_REQUIRE_REAL_GEMINI", strict)

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"provider-secret-body",
        )

    backend = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/analyze/stream",
            files={"image": ("toilet.png", _png_bytes(), "image/png")},
            data={"room_hint": "toilet"},
        )
    await backend.aclose()

    events = _events(response)
    assert len(events) == 1
    assert events[0]["type"] == ("error" if strict else "result")
    assert "provider-secret-body" not in response.text


@pytest.mark.asyncio
async def test_web_stream_stops_and_closes_upstream_after_first_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_module = _load_web_module()
    payload = web_module._build_local_mock(_png_bytes(), "toilet", "test")
    terminal = (
        json.dumps(
            {"type": "result", "payload": payload},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    closed: list[bool] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            stream=ChunkStream(
                [
                    b'{"type":"progress","stage":"intake_complete"}\n',
                    b'{"type":"progress","stage":"vision_complete"}\n',
                    terminal,
                    b'{"type":"error","error":"analysis_failed",'
                    b'"message":"provider-secret-body"}\n',
                ],
                closed=closed,
            ),
        )

    backend = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(web_module, "backend_client", lambda: backend)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web_module.app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/analyze/stream",
            files={"image": ("toilet.png", _png_bytes(), "image/png")},
            data={"room_hint": "toilet"},
        )
    await backend.aclose()

    events = _events(response)
    assert [event["type"] for event in events] == [
        "progress",
        "progress",
        "result",
    ]
    assert closed == [True]
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
