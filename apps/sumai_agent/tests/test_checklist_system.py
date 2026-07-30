from __future__ import annotations

import base64
import io

from PIL import Image

from app.models import (
    BoundingBox,
    MissingSafetyFeature,
    RiskFinding,
    RoomType,
    VisionResult,
)
from app.services.checklist_engine import ChecklistEngine
from app.services.rule_engine import RuleEngine
from app.services.visual_renderer import VisualRenderer


def test_toilet_missing_handrail() -> None:
    engine = ChecklistEngine()
    vision_result = VisionResult(
        room_type="toilet",
        is_home_environment=True,
        observations={"has_handrail": False},
        visible_hazards=[],
        missing_safety_features=[
            MissingSafetyFeature(
                feature_key="has_handrail",
                confidence=0.85,
                bbox=BoundingBox(x=0.1, y=0.2, w=0.15, h=0.6),
                evidence_ja="便器側面に手すりがありません。"
            )
        ]
    )
    findings = engine.process(vision_result)
    assert len(findings) > 0
    handrail_finding = [f for f in findings if f.risk_type == "toilet_missing_handrail"]
    assert len(handrail_finding) == 1
    assert handrail_finding[0].severity == 4
    assert "厚労省" in handrail_finding[0].basis_label_ja
    assert handrail_finding[0].needs_human_confirmation is True
    assert handrail_finding[0].description_ja == (
        "写真で十分に表示された範囲では、手すりを確認できませんでした。"
    )
    assert "不存在や設置位置を示すものではありません" in (
        handrail_finding[0].evidence_ja
    )


def test_toilet_missing_emergency_call() -> None:
    engine = ChecklistEngine()
    vision_result = VisionResult(
        room_type="toilet",
        is_home_environment=True,
        observations={"has_emergency_call_button": False},
        visible_hazards=[],
        missing_safety_features=[
            MissingSafetyFeature(
                feature_key="has_emergency_call_button",
                confidence=0.75,
                bbox=BoundingBox(x=0.8, y=0.3, w=0.1, h=0.1),
                evidence_ja="緊急ボタンが確認できません。"
            )
        ]
    )
    findings = engine.process(vision_result)
    emergency_finding = [f for f in findings if f.risk_type == "toilet_missing_emergency_call"]
    assert len(emergency_finding) == 1
    assert emergency_finding[0].severity == 2
    assert "自治体" in emergency_finding[0].basis_label_ja


def test_toilet_unclear_handrail() -> None:
    engine = ChecklistEngine()
    # has_handrail is null/None
    vision_result = VisionResult(
        room_type="toilet",
        is_home_environment=True,
        observations={"has_handrail": None},
        visible_hazards=[],
        missing_safety_features=[]
    )
    findings = engine.process(vision_result)
    handrail_finding = [f for f in findings if f.risk_type == "toilet_missing_handrail"]
    assert len(handrail_finding) == 0


def test_legacy_observations_without_evidence_coordinates_create_no_findings() -> None:
    engine = ChecklistEngine()
    vision_result = VisionResult(
        room_type="genkan",
        is_home_environment=True,
        observations={"has_handrail_or_support": False, "cluttered_path": True},
        visible_hazards=[],
        missing_safety_features=[],
    )

    findings = engine.process(vision_result)
    annotated, _ = VisualRenderer().render(
        Image.new("RGB", (100, 100), "white"), findings, "genkan"
    )
    rendered = Image.open(io.BytesIO(base64.b64decode(annotated))).convert("RGB")

    assert findings == []
    assert set(rendered.getdata()) == {(255, 255, 255)}


def test_coordinate_backed_legacy_features_preserve_exact_evidence_bbox() -> None:
    expected_bbox = BoundingBox(x=0.1, y=0.2, w=0.15, h=0.6)
    visible_bbox = BoundingBox(x=0.7, y=0.1, w=0.1, h=0.1)
    vision_result = VisionResult(
        room_type="genkan",
        is_home_environment=True,
        observations={"has_handrail_or_support": False, "cluttered_path": True},
        missing_safety_features=[
            MissingSafetyFeature(
                feature_key="has_handrail_or_support",
                confidence=0.85,
                bbox=expected_bbox,
                evidence_ja="支持物が確認できません。",
            )
        ],
        visible_hazards=[
            RiskFinding(
                id="pending",
                risk_type="cluttered_path",
                label_ja="玄関動線の障害物",
                description_ja="動線に障害物があります。",
                severity=3,
                confidence=0.9,
                bbox=visible_bbox,
                evidence_ja="動線上に物があります。",
                basis_label_ja="",
                basis_summary_ja="",
                needs_human_confirmation=False,
                ontology_key="cluttered_path",
                ontology_rule_kind="visible_hazard",
            )
        ],
    )

    findings = ChecklistEngine().process(vision_result)

    assert {
        (finding.ontology_rule_kind, finding.ontology_key): finding.bbox
        for finding in findings
    } == {
        ("expected_feature", "has_handrail_or_support"): expected_bbox,
        ("visible_hazard", "cluttered_path"): visible_bbox,
    }


def test_bathroom_missing_non_slip() -> None:
    engine = ChecklistEngine()
    vision_result = VisionResult(
        room_type="bathroom",
        is_home_environment=True,
        observations={"has_non_slip_floor_or_mat": False},
        visible_hazards=[],
        missing_safety_features=[
            MissingSafetyFeature(
                feature_key="has_non_slip_floor_or_mat",
                confidence=0.80,
                bbox=BoundingBox(x=0.2, y=0.6, w=0.6, h=0.3),
                evidence_ja="滑り止め対策がありません。"
            )
        ]
    )
    findings = engine.process(vision_result)
    slip_finding = [f for f in findings if f.risk_type == "bathroom_missing_non_slip"]
    assert len(slip_finding) == 1
    assert slip_finding[0].severity == 4


def test_non_home_environment_no_findings() -> None:
    engine = ChecklistEngine()
    vision_result = VisionResult(
        room_type="auto",
        is_home_environment=False,
        observations={},
        visible_hazards=[],
        missing_safety_features=[],
        not_applicable_reason_ja="住宅内ではありません"
    )
    findings = engine.process(vision_result)
    assert len(findings) == 0


def test_action_tiers() -> None:
    rule_engine = RuleEngine()
    engine = ChecklistEngine()

    # Emergency call missing in toilet
    vision_result = VisionResult(
        room_type="toilet",
        is_home_environment=True,
        observations={"has_emergency_call_button": False},
        visible_hazards=[],
        missing_safety_features=[
            MissingSafetyFeature(
                feature_key="has_emergency_call_button",
                confidence=0.75,
                bbox=BoundingBox(x=0.8, y=0.3, w=0.1, h=0.1),
                evidence_ja="緊急ボタンなし。"
            )
        ]
    )
    findings = engine.process(vision_result)
    norm_findings, action_plan = rule_engine.apply(findings, "toilet")

    # Check emergency call actions
    # - family actions should exist
    # - care manager actions should exist (緊急通報装置・呼出ボタンを相談する)
    # - contractor actions should NOT have emergency call action since there is no contractor_action listed for it
    assert len(action_plan.family_no_cost) > 0
    assert len(action_plan.care_manager_purchase) > 0
    assert any("緊急通報" in act.title_ja for act in action_plan.care_manager_purchase)
    
    # Handrail missing in toilet
    vision_result2 = VisionResult(
        room_type="toilet",
        is_home_environment=True,
        observations={"has_handrail": False},
        visible_hazards=[],
        missing_safety_features=[
            MissingSafetyFeature(
                feature_key="has_handrail",
                confidence=0.85,
                bbox=BoundingBox(x=0.1, y=0.2, w=0.15, h=0.6),
                evidence_ja="手すりなし。"
            )
        ]
    )
    findings2 = engine.process(vision_result2)
    norm_findings2, action_plan2 = rule_engine.apply(findings2, "toilet")

    # Handrail missing can go to care manager and contractor
    assert any("手すり" in act.title_ja for act in action_plan2.care_manager_purchase)
    assert any("手すり" in act.title_ja for act in action_plan2.contractor_construction)
