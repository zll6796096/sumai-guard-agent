from __future__ import annotations

import base64
import io
import logging

import pytest
from PIL import Image

from app.models import (
    BoundingBox,
    MissingSafetyFeature,
    RiskFinding,
    VisionResult,
)
from app.services.checklist_engine import ChecklistEngine
from app.services.rule_engine import RuleEngine
from app.services.visual_renderer import VisualRenderer


def _risk_finding(
    *,
    risk_type: str,
    bbox: BoundingBox | None = None,
    confidence: float = 0.90,
    ontology_key: str | None = None,
    ontology_rule_kind: str | None = None,
) -> RiskFinding:
    return RiskFinding(
        id="legacy",
        risk_type=risk_type,
        label_ja="legacy label",
        description_ja="写真内の候補です。",
        severity=1,
        confidence=confidence,
        bbox=bbox or BoundingBox(x=0.1, y=0.1, w=0.2, h=0.2),
        evidence_ja="写真内に局所的な根拠があります。",
        basis_label_ja="",
        basis_summary_ja="",
        needs_human_confirmation=False,
        ontology_key=ontology_key,
        ontology_rule_kind=ontology_rule_kind,
    )


def _decoded_rgb(image_base64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(image_base64))).convert("RGB")


@pytest.mark.parametrize(
    ("room_type", "feature_key"),
    [
        ("toilet", "has_handrail"),
        ("toilet", "has_emergency_call_button"),
        ("bathroom", "has_non_slip_floor_or_mat"),
    ],
)
def test_coordinate_backed_missing_features_do_not_become_findings(
    room_type: str,
    feature_key: str,
) -> None:
    vision_result = VisionResult(
        room_type=room_type,
        is_home_environment=True,
        observations={feature_key: False},
        visible_hazards=[],
        missing_safety_features=[
            MissingSafetyFeature(
                feature_key=feature_key,
                confidence=0.90,
                bbox=BoundingBox(x=0.1, y=0.2, w=0.2, h=0.5),
                evidence_ja="写真の対象範囲では設備を確認できません。",
            )
        ],
    )

    assert ChecklistEngine().process(vision_result) == []


def test_missing_feature_cannot_reach_actions_or_image_overlays() -> None:
    vision_result = VisionResult(
        room_type="toilet",
        is_home_environment=True,
        observations={"has_handrail": False},
        visible_hazards=[],
        missing_safety_features=[
            MissingSafetyFeature(
                feature_key="has_handrail",
                confidence=0.90,
                bbox=BoundingBox(x=0.1, y=0.2, w=0.2, h=0.5),
                evidence_ja="写真の対象範囲では手すりを確認できません。",
            )
        ],
    )

    findings = ChecklistEngine().process(vision_result)
    normalized, action_plan = RuleEngine().apply(findings, "toilet")
    annotated, improvement = VisualRenderer().render(
        Image.new("RGB", (100, 100), "white"),
        normalized,
        "toilet",
    )

    assert normalized == []
    assert action_plan.family_no_cost == []
    assert action_plan.care_manager_purchase == []
    assert action_plan.contractor_construction == []
    assert set(_decoded_rgb(annotated).getdata()) == {(255, 255, 255)}
    assert set(_decoded_rgb(improvement).getdata()) == {(255, 255, 255)}


def test_mixed_legacy_input_returns_only_exact_visible_hazard() -> None:
    visible_bbox = BoundingBox(x=0.7, y=0.1, w=0.1, h=0.1)
    expected_bbox = BoundingBox(x=0.1, y=0.2, w=0.15, h=0.6)
    vision_result = VisionResult(
        room_type="genkan",
        is_home_environment=True,
        observations={"has_handrail_or_support": False, "cluttered_path": True},
        missing_safety_features=[
            MissingSafetyFeature(
                feature_key="has_handrail_or_support",
                confidence=0.85,
                bbox=expected_bbox,
                evidence_ja="写真の対象範囲では支持物を確認できません。",
            )
        ],
        visible_hazards=[
            _risk_finding(
                risk_type="cluttered_path",
                bbox=visible_bbox,
                ontology_key="cluttered_path",
                ontology_rule_kind="visible_hazard",
            )
        ],
    )

    findings = ChecklistEngine().process(vision_result)

    assert len(findings) == 1
    assert findings[0].id == "R1"
    assert findings[0].risk_type == "cluttered_path"
    assert findings[0].bbox == visible_bbox
    assert findings[0].ontology_key == "cluttered_path"
    assert findings[0].ontology_rule_kind == "visible_hazard"
    assert findings[0].severity == 3
    assert all(
        finding.ontology_key != "has_handrail_or_support" for finding in findings
    )


def test_expected_feature_identity_is_rejected_even_in_visible_hazards() -> None:
    vision_result = VisionResult(
        room_type="toilet",
        is_home_environment=True,
        visible_hazards=[
            _risk_finding(
                risk_type="toilet_missing_handrail",
                ontology_key="has_handrail",
                ontology_rule_kind="expected_feature",
            )
        ],
    )

    assert ChecklistEngine().process(vision_result) == []


@pytest.mark.parametrize(
    ("ontology_key", "ontology_rule_kind"),
    [
        ("cluttered_path", None),
        (None, "visible_hazard"),
    ],
)
def test_partial_ontology_identity_is_rejected(
    ontology_key: str | None,
    ontology_rule_kind: str | None,
) -> None:
    vision_result = VisionResult(
        room_type="genkan",
        is_home_environment=True,
        visible_hazards=[
            _risk_finding(
                risk_type="cluttered_path",
                ontology_key=ontology_key,
                ontology_rule_kind=ontology_rule_kind,
            )
        ],
    )

    assert ChecklistEngine().process(vision_result) == []


def test_ambiguous_risk_type_only_legacy_finding_is_rejected() -> None:
    vision_result = VisionResult(
        room_type="bedroom",
        is_home_environment=True,
        visible_hazards=[_risk_finding(risk_type="poor_lighting")],
    )

    assert ChecklistEngine().process(vision_result) == []


def test_unambiguous_risk_type_only_visible_legacy_finding_is_normalized() -> None:
    evidence_bbox = BoundingBox(x=0.2, y=0.3, w=0.4, h=0.2)
    legacy_finding = _risk_finding(
        risk_type="cluttered_path",
        bbox=evidence_bbox,
    ).model_copy(
        update={
            "label_ja": "任意のラベル",
            "severity": 5,
            "evidence_source_ids": ["UNTRUSTED_SOURCE"],
        }
    )
    vision_result = VisionResult(
        room_type="bedroom",
        is_home_environment=True,
        visible_hazards=[legacy_finding],
    )

    findings = ChecklistEngine().process(vision_result)

    assert len(findings) == 1
    assert findings[0].id == "R1"
    assert findings[0].bbox == evidence_bbox
    assert findings[0].ontology_key == "cluttered_path"
    assert findings[0].ontology_rule_kind == "visible_hazard"
    assert findings[0].label_ja == "寝室の床の障害物"
    assert findings[0].severity == 3
    assert findings[0].evidence_source_ids == ["CAA_FALL_PREVENTION"]


def test_legacy_observations_without_visible_hazards_create_no_findings() -> None:
    vision_result = VisionResult(
        room_type="genkan",
        is_home_environment=True,
        observations={"has_handrail_or_support": False, "cluttered_path": True},
    )

    assert ChecklistEngine().process(vision_result) == []


@pytest.mark.parametrize(
    ("room_type", "is_home_environment"),
    [
        ("auto", True),
        ("genkan", False),
    ],
)
def test_unknown_room_or_non_home_input_fails_closed(
    room_type: str,
    is_home_environment: bool,
) -> None:
    vision_result = VisionResult(
        room_type=room_type,
        is_home_environment=is_home_environment,
        visible_hazards=[
            _risk_finding(
                risk_type="cluttered_path",
                ontology_key="cluttered_path",
                ontology_rule_kind="visible_hazard",
            )
        ],
    )

    assert ChecklistEngine().process(vision_result) == []


@pytest.mark.parametrize(
    ("room_type", "is_home_environment", "expected_event"),
    [
        ("genkan", False, "checklist_skipped_non_home"),
        ("auto", True, "checklist_skipped_auto_room"),
        ("unknown", True, "checklist_skipped_unknown_room"),
    ],
)
def test_fail_closed_checklist_logs_the_actual_skip_reason(
    caplog: pytest.LogCaptureFixture,
    room_type: str,
    is_home_environment: bool,
    expected_event: str,
) -> None:
    result = VisionResult(
        room_type="auto" if room_type == "unknown" else room_type,
        is_home_environment=is_home_environment,
    )
    if room_type == "unknown":
        result = result.model_copy(update={"room_type": "unknown"})

    with caplog.at_level(logging.WARNING, logger="sumai.checklist_engine"):
        assert ChecklistEngine().process(result) == []

    records = [
        record
        for record in caplog.records
        if record.name == "sumai.checklist_engine"
    ]
    assert [record.getMessage() for record in records] == [expected_event]
    assert records[0].room_type == room_type
