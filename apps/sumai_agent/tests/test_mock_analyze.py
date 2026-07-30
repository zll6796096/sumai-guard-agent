from __future__ import annotations

from copy import deepcopy
import importlib.util
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app import main as main_module
from app.main import app
from app.models import (
    ActionPlan,
    AnalysisResponse,
    BoundingBox,
    FeatureObservation,
    VisionFacts,
)
from app.services.orchestrator import AnalysisOrchestrator


WEB_APP_PATH = Path(__file__).resolve().parents[2] / "sumai_web" / "app.py"


class ExpectedOnlyVision:
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, **_kwargs: object) -> tuple[VisionFacts, str]:
        self.calls += 1
        return (
            VisionFacts(
                environment="home",
                room_type="toilet",
                visible_regions=["room"],
                entities=[],
                feature_observations=[
                    FeatureObservation(
                        feature_key="has_handrail",
                        state="absent_with_full_coverage",
                        evidence_bbox=BoundingBox(x=0.10, y=0.15, w=0.20, h=0.60),
                        model_score=0.91,
                    ),
                    FeatureObservation(
                        feature_key="has_emergency_call_button",
                        state="absent_with_full_coverage",
                        evidence_bbox=BoundingBox(x=0.65, y=0.20, w=0.15, h=0.20),
                        model_score=0.82,
                    ),
                ],
                relationships=[],
            ),
            "gemini",
        )


class NotApplicableVision:
    async def analyze(self, **_kwargs: object) -> tuple[VisionFacts, str]:
        return (
            VisionFacts(
                environment="non_home",
                room_type="unknown",
                visible_regions=[],
                entities=[],
                feature_observations=[],
                relationships=[],
                not_applicable_reason_code="non_home_environment",
            ),
            "gemini",
        )


def _png_bytes() -> bytes:
    image = Image.new("RGB", (800, 600), (236, 232, 224))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_mock_analyze_returns_valid_schema_and_japanese_reports() -> None:
    client = TestClient(app)

    response = client.post(
        "/analyze",
        data={"room_hint": "genkan", "mock": "true"},
        files={"image": ("genkan.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis_id"]
    assert payload["room_type"] in {"genkan", "hallway", "bathroom", "toilet", "bedroom", "kitchen", "auto"}
    assert payload["overall_risk_level"] in {"low", "medium", "high"}
    assert payload["is_not_applicable"] is False
    assert payload["findings"]
    assert payload["action_plan"]["family_no_cost"]
    assert payload["annotated_image_base64"]
    assert payload["improvement_image_base64"]
    assert "家族で今日できること" in payload["family_actions_markdown"]
    assert "ケアマネ・福祉用具に相談" in payload["care_manager_actions_markdown"]
    assert "専門施工・現地確認" in payload["contractor_actions_markdown"]
    assert isinstance(payload["confirmation_items_markdown"], str)
    assert payload["confirmation_items_markdown"].strip()
    assert "モデル検出スコア（未校正）:" in payload["risk_summary_markdown"]
    assert "信頼度:" not in payload["risk_summary_markdown"]
    assert "医療・介護・施工判断を代替しません" in payload["disclaimer_ja"]
    assert AnalysisResponse.model_validate(payload).is_not_applicable is False


def test_analysis_response_defaults_to_current_public_identity() -> None:
    response = AnalysisResponse(
        analysis_id="sumai_test",
        room_type="toilet",
        overall_risk_level="low",
        findings=[],
        action_plan=ActionPlan(),
        annotated_image_base64="image",
        improvement_image_base64="image",
        risk_summary_markdown="summary",
        confirmation_items_markdown="confirmations",
        family_actions_markdown="family",
        care_manager_actions_markdown="care",
        contractor_actions_markdown="contractor",
        disclaimer_ja="POC",
    )

    assert response.schema_version == "2.1.0"
    assert response.inference_config_version == "1.0.5"


def test_confirmation_only_analysis_is_neutral_canonical_and_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vision = ExpectedOnlyVision()
    subject = AnalysisOrchestrator(vision=vision)
    rendered_findings: list[list[object]] = []
    original_render = subject.visual_renderer.render

    def capture_render(
        image: Image.Image, findings: list[object], room_type: str
    ) -> tuple[str, str]:
        rendered_findings.append(findings)
        return original_render(image, findings, room_type)  # type: ignore[arg-type]

    monkeypatch.setattr(subject.visual_renderer, "render", capture_render)
    monkeypatch.setattr(main_module, "orchestrator", subject)
    client = TestClient(app)
    request = {
        "data": {"room_hint": "toilet", "mock": "false"},
        "files": {"image": ("toilet.png", _png_bytes(), "image/png")},
    }

    first = client.post("/analyze", **request)
    second = client.post("/analyze", **request)

    assert first.status_code == second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["findings"] == []
    assert first_payload["overall_risk_level"] == "low"
    assert first_payload["action_plan"] == {
        "family_no_cost": [],
        "care_manager_purchase": [],
        "contractor_construction": [],
    }
    assert [
        (item["id"], item["feature_key"])
        for item in first_payload["confirmation_items"]
    ] == [
        ("C1", "has_emergency_call_button"),
        ("C2", "has_handrail"),
    ]
    assert first_payload["annotated_image_base64"]
    assert first_payload["improvement_image_base64"]
    assert "## 写真での中性確認" in first_payload["confirmation_items_markdown"]
    assert "手すり" in first_payload["confirmation_items_markdown"]
    assert "手すり" not in first_payload["risk_summary_markdown"]
    assert rendered_findings == [[], []]
    assert vision.calls == 1
    assert first_payload["analysis_id"] != second_payload["analysis_id"]
    assert first_payload["confirmation_items"] == second_payload["confirmation_items"]
    assert first_payload["semantic_hash"] == second_payload["semantic_hash"]


def test_not_applicable_analysis_has_no_confirmation_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "orchestrator",
        AnalysisOrchestrator(vision=NotApplicableVision()),
    )
    response = TestClient(app).post(
        "/analyze",
        data={"room_hint": "auto", "mock": "false"},
        files={"image": ("not-home.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_not_applicable"] is True
    assert payload["confirmation_items"] == []
    assert isinstance(payload["confirmation_items_markdown"], str)
    assert payload["confirmation_items_markdown"].strip()


def test_analysis_response_enforces_the_public_applicability_invariant() -> None:
    client = TestClient(app)
    response = client.post(
        "/analyze",
        data={"room_hint": "genkan", "mock": "true"},
        files={"image": ("genkan.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    normal = response.json()

    neutral = deepcopy(normal)
    neutral.update({
        "is_not_applicable": True,
        "room_type": "auto",
        "overall_risk_level": "low",
        "findings": [],
        "confirmation_items": [],
        "action_plan": {
            "family_no_cost": [],
            "care_manager_purchase": [],
            "contractor_construction": [],
        },
        "not_applicable_reason_ja": "写真から十分に確認できないため、結果を表示していません。",
    })
    assert AnalysisResponse.model_validate(neutral).is_not_applicable is True

    invalid_payloads = []
    true_known_room = deepcopy(neutral)
    true_known_room["room_type"] = "genkan"
    invalid_payloads.append(true_known_room)
    true_non_low = deepcopy(neutral)
    true_non_low["overall_risk_level"] = "medium"
    invalid_payloads.append(true_non_low)
    true_finding = deepcopy(neutral)
    true_finding["findings"] = deepcopy(normal["findings"])
    invalid_payloads.append(true_finding)
    true_action = deepcopy(neutral)
    true_action["action_plan"]["family_no_cost"] = deepcopy(normal["action_plan"]["family_no_cost"])
    invalid_payloads.append(true_action)
    true_confirmation = deepcopy(neutral)
    true_confirmation["confirmation_items"] = [
        {
            "id": "C1",
            "feature_key": "has_handrail",
            "label_ja": "手すり",
            "description_ja": "写真では確認できませんでした。",
            "confidence": 0.8,
            "evidence_source_ids": [],
            "basis_label_ja": "写真で確認できる範囲",
            "basis_summary_ja": "存在しないことを示しません。",
            "needs_human_confirmation": True,
        }
    ]
    invalid_payloads.append(true_confirmation)
    true_blank_reason = deepcopy(neutral)
    true_blank_reason["not_applicable_reason_ja"] = "  "
    invalid_payloads.append(true_blank_reason)

    false_non_home = deepcopy(normal)
    false_non_home["is_home_environment"] = False
    invalid_payloads.append(false_non_home)
    false_auto = deepcopy(normal)
    false_auto["room_type"] = "auto"
    invalid_payloads.append(false_auto)
    false_blank_reason = deepcopy(normal)
    false_blank_reason["not_applicable_reason_ja"] = ""
    invalid_payloads.append(false_blank_reason)

    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            AnalysisResponse.model_validate(payload)


def test_same_mock_request_has_stable_canonical_result_but_new_request_id() -> None:
    client = TestClient(app)
    request = {
        "data": {"room_hint": "genkan", "mock": "true"},
        "files": {"image": ("genkan.png", _png_bytes(), "image/png")},
    }

    first = client.post("/analyze", **request)
    second = client.post("/analyze", **request)

    assert first.status_code == 200
    assert second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["analysis_id"] != second_payload["analysis_id"]
    for key in ("result_key", "semantic_hash", "findings", "action_plan"):
        assert first_payload[key] == second_payload[key]


def test_result_key_changes_when_room_or_execution_mode_changes() -> None:
    client = TestClient(app)
    common = {"files": {"image": ("genkan.png", _png_bytes(), "image/png")}}

    forced_mock = client.post("/analyze", data={"room_hint": "genkan", "mock": "true"}, **common)
    another_room = client.post("/analyze", data={"room_hint": "bathroom", "mock": "true"}, **common)
    configured_mock = client.post("/analyze", data={"room_hint": "genkan", "mock": "false"}, **common)

    assert forced_mock.status_code == another_room.status_code == configured_mock.status_code == 200
    assert forced_mock.json()["result_key"] != another_room.json()["result_key"]
    assert forced_mock.json()["result_key"] != configured_mock.json()["result_key"]


def test_web_local_abstention_uses_current_schema_identity_and_empty_confirmations() -> None:
    spec = importlib.util.spec_from_file_location("sumai_web_local_abstention", WEB_APP_PATH)
    assert spec and spec.loader
    web_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(web_module)

    payload = web_module._build_local_mock(_png_bytes(), "auto", "test")

    assert payload["confirmation_items"] == []
    assert isinstance(payload["confirmation_items_markdown"], str)
    assert payload["confirmation_items_markdown"].strip()
    assert payload["schema_version"] == "2.1.0"
    assert payload["inference_config_version"] == "1.0.5"
