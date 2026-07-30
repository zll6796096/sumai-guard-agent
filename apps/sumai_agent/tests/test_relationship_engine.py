from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import AnalysisResponse, RoomType, VisionFacts
from app.ontology import OntologyRepository
from app.services.gemini_vision import mock_vision_facts
from app.services.relationship_engine import RelationshipEngine


def _facts(**overrides: object) -> VisionFacts:
    payload: dict[str, object] = {
        "environment": "home",
        "room_type": "hallway",
        "visible_regions": ["floor", "walking_path"],
        "entities": [
            {
                "ref": "e1",
                "ontology_key": "hallway_cord",
                "bbox": {"x": 0.1, "y": 0.6, "w": 0.5, "h": 0.1},
                "visibility": "clear",
                "model_score": 0.9,
            }
        ],
        "feature_observations": [],
        "relationships": [],
        "not_applicable_reason_code": None,
    }
    payload.update(overrides)
    return VisionFacts.model_validate(payload)


def _engine() -> RelationshipEngine:
    return RelationshipEngine(OntologyRepository.load_default())


def _analysis_response_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "analysis_id": "analysis-1",
        "room_type": "hallway",
        "overall_risk_level": "low",
        "findings": [],
        "action_plan": {},
        "annotated_image_base64": "",
        "improvement_image_base64": "",
        "risk_summary_markdown": "",
        "family_actions_markdown": "",
        "care_manager_actions_markdown": "",
        "contractor_actions_markdown": "",
        "disclaimer_ja": "写真のみで最終判断しません。",
    }
    payload.update(overrides)
    return payload


def _finding_payload(
    *, ontology_key: str | None, ontology_rule_kind: str | None
) -> dict[str, object]:
    return {
        "id": "risk-1",
        "risk_type": "hallway_cord",
        "label_ja": "廊下のコード",
        "description_ja": "写真で確認されました。",
        "severity": 3,
        "confidence": 0.9,
        "bbox": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
        "evidence_ja": "写真内に可視の根拠があります。",
        "basis_label_ja": "一般的な転倒予防",
        "basis_summary_ja": "動線上のコードはつまずきにつながります。",
        "needs_human_confirmation": False,
        "ontology_key": ontology_key,
        "ontology_rule_kind": ontology_rule_kind,
    }


def test_applicable_response_rejects_expected_feature_as_risk() -> None:
    with pytest.raises(
        ValidationError, match="applicable_findings_must_be_visible_hazards"
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                findings=[
                    _finding_payload(
                        ontology_key="sufficient_lighting",
                        ontology_rule_kind="expected_feature",
                    )
                ]
            )
        )


def test_not_applicable_response_requires_empty_confirmations() -> None:
    with pytest.raises(
        ValidationError, match="not_applicable_requires_empty_findings_and_actions"
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                room_type="auto",
                is_home_environment=False,
                is_not_applicable=True,
                not_applicable_reason_ja="住宅写真ではありません。",
                confirmation_items=[
                    {
                        "id": "pending",
                        "feature_key": "has_handrail",
                        "label_ja": "手すり",
                        "description_ja": (
                            "この写真では、手すりを確認できませんでした。"
                            "これは手すりが存在しないことや、追加が必要なことを"
                            "示すものではありません。"
                        ),
                        "confidence": 0.9,
                        "basis_label_ja": "一般的な安全確認",
                        "basis_summary_ja": "手すりは支持の相談候補です。",
                        "needs_human_confirmation": True,
                    }
                ],
            )
        )


def test_applicable_response_preserves_legacy_finding_without_ontology_identity() -> None:
    response = AnalysisResponse.model_validate(
        _analysis_response_payload(
            findings=[
                _finding_payload(
                    ontology_key=None,
                    ontology_rule_kind=None,
                )
            ]
        )
    )

    assert len(response.findings) == 1


def test_hallway_cord_requires_intersects_relationship() -> None:
    facts = _facts()

    empty_result = _engine().derive(facts)
    assert empty_result.visible_findings == []
    assert empty_result.confirmation_items == []

    result = _engine().derive(
        _facts(
            relationships=[
                {"subject": "e1", "predicate": "intersects", "object": "walking_path"}
            ]
        )
    )

    findings = result.visible_findings
    assert [finding.risk_type for finding in findings] == ["hallway_cord"]
    assert findings[0].id == "pending"
    assert findings[0].confidence == 0.9
    assert findings[0].display_bbox is None
    assert result.confirmation_items == []


def test_hallway_cord_requires_configured_relationship_target() -> None:
    result = _engine().derive(
        _facts(
            visible_regions=["walking_path", "wall"],
            relationships=[
                {"subject": "e1", "predicate": "intersects", "object": "wall"}
            ],
        )
    )

    assert result.visible_findings == []
    assert result.confirmation_items == []


def test_visible_hazard_with_full_frame_placeholder_is_not_derived() -> None:
    result = _engine().derive(
        _facts(
            entities=[
                {
                    "ref": "e1",
                    "ontology_key": "hallway_cord",
                    "bbox": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
                    "visibility": "clear",
                    "model_score": 0.9,
                }
            ],
            relationships=[
                {
                    "subject": "e1",
                    "predicate": "intersects",
                    "object": "walking_path",
                }
            ],
        )
    )

    assert result.visible_findings == []
    assert result.confirmation_items == []


def test_visible_rule_identity_uses_observation_key_not_duplicate_risk_type() -> None:
    result = _engine().derive(
        _facts(
            room_type="genkan",
            visible_regions=["walking_path"],
            entities=[
                {
                    "ref": "e1",
                    "ontology_key": "cluttered_path",
                    "bbox": {"x": 0.7, "y": 0.1, "w": 0.1, "h": 0.1},
                    "visibility": "clear",
                    "model_score": 0.9,
                }
            ],
            relationships=[
                {"subject": "e1", "predicate": "obstructs", "object": "walking_path"}
            ],
        )
    )

    findings = result.visible_findings
    assert len(findings) == 1
    assert findings[0].ontology_key == "cluttered_path"
    assert findings[0].ontology_rule_kind == "visible_hazard"
    assert findings[0].label_ja == "玄関動線の障害物"
    assert findings[0].basis_summary_ja.startswith("玄関まわりの荷物や傘立て等")
    assert result.confirmation_items == []


def test_expected_feature_rule_identity_uses_neutral_ontology_label() -> None:
    result = _engine().derive(
        _facts(
            entities=[],
            feature_observations=[
                {
                    "feature_key": "sufficient_lighting",
                    "state": "absent_with_full_coverage",
                    "evidence_bbox": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
                    "model_score": 0.9,
                }
            ],
        )
    )

    assert result.visible_findings == []
    assert len(result.confirmation_items) == 1
    item = result.confirmation_items[0]
    assert item.feature_key == "sufficient_lighting"
    assert item.label_ja == "通路の照明"
    assert item.basis_summary_ja.startswith("夜間のトイレ移動など")


def test_expected_feature_becomes_neutral_confirmation_not_risk() -> None:
    result = _engine().derive(
        _facts(
            room_type="toilet",
            entities=[],
            feature_observations=[
                {
                    "feature_key": "has_emergency_call_button",
                    "state": "absent_with_full_coverage",
                    "evidence_bbox": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
                    "model_score": 0.91,
                }
            ],
        )
    )

    assert result.visible_findings == []
    assert len(result.confirmation_items) == 1
    item = result.confirmation_items[0]
    assert item.feature_key == "has_emergency_call_button"
    assert item.label_ja == "緊急呼出ボタン"
    assert item.needs_human_confirmation is True
    assert "確認できませんでした" in item.description_ja
    assert "存在しない" in item.description_ja
    assert not hasattr(item, "severity")
    assert not hasattr(item, "bbox")


def test_visible_and_confirmation_channels_remain_separate() -> None:
    result = _engine().derive(
        _facts(
            room_type="bedroom",
            visible_regions=["room"],
            entities=[
                {
                    "ref": "e1",
                    "ontology_key": "poor_lighting",
                    "bbox": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                    "visibility": "clear",
                    "model_score": 0.9,
                }
            ],
            feature_observations=[
                {
                    "feature_key": "bedside_light",
                    "state": "absent_with_full_coverage",
                    "evidence_bbox": {"x": 0.6, "y": 0.1, "w": 0.2, "h": 0.2},
                    "model_score": 0.9,
                }
            ],
            relationships=[
                {"subject": "e1", "predicate": "located_in", "object": "room"}
            ],
        )
    )

    assert [item.ontology_key for item in result.visible_findings] == [
        "poor_lighting"
    ]
    assert [item.feature_key for item in result.confirmation_items] == [
        "bedside_light"
    ]


def test_duplicate_entity_refs_fail_safe_without_duplicate_findings() -> None:
    facts = _facts(
        entities=[
            {
                "ref": "e1",
                "ontology_key": "hallway_cord",
                "bbox": {"x": 0.1, "y": 0.6, "w": 0.5, "h": 0.1},
                "visibility": "clear",
                "model_score": 0.9,
            },
            {
                "ref": "e1",
                "ontology_key": "hallway_cord",
                "bbox": {"x": 0.2, "y": 0.6, "w": 0.4, "h": 0.1},
                "visibility": "clear",
                "model_score": 0.9,
            },
        ],
        relationships=[
            {"subject": "e1", "predicate": "intersects", "object": "walking_path"}
        ],
    )

    result = _engine().derive(facts)
    assert result.visible_findings == []
    assert result.confirmation_items == []


def test_missing_bathroom_handrail_requires_full_coverage_evidence() -> None:
    facts = _facts(
        room_type="bathroom",
        entities=[],
        feature_observations=[
            {
                "feature_key": "has_handrail",
                "state": "cannot_determine",
                "evidence_bbox": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
                "model_score": 0.9,
            }
        ],
    )

    cannot_determine_result = _engine().derive(facts)
    assert cannot_determine_result.visible_findings == []
    assert cannot_determine_result.confirmation_items == []

    result = _engine().derive(
        _facts(
            room_type="bathroom",
            entities=[],
            feature_observations=[
                {
                    "feature_key": "has_handrail",
                    "state": "absent_with_full_coverage",
                    "evidence_bbox": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
                    "model_score": 0.9,
                }
            ],
        )
    )

    assert result.visible_findings == []
    assert len(result.confirmation_items) == 1
    item = result.confirmation_items[0]
    assert item.feature_key == "has_handrail"
    assert item.evidence_source_ids == [
        "MHLW_WELFARE_HOUSING",
        "MHLW_NOTICE_OLD34",
    ]
    assert item.needs_human_confirmation is True
    assert item.description_ja == (
        "この写真では、浴室手すりを確認できませんでした。"
        "これは浴室手すりが存在しないことや、追加が必要なことを示すものではありません。"
    )


def test_missing_feature_without_evidence_bbox_is_not_derived() -> None:
    facts = _facts(
        room_type="bathroom",
        entities=[],
        feature_observations=[
            {
                "feature_key": "has_handrail",
                "state": "absent_with_full_coverage",
                "evidence_bbox": None,
                "model_score": 0.9,
            }
        ],
    )

    result = _engine().derive(facts)
    assert result.visible_findings == []
    assert result.confirmation_items == []


def test_missing_feature_with_full_frame_placeholder_is_not_derived() -> None:
    facts = _facts(
        room_type="toilet",
        entities=[],
        feature_observations=[
            {
                "feature_key": "has_handrail",
                "state": "absent_with_full_coverage",
                "evidence_bbox": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
                "model_score": 0.9,
            }
        ],
    )

    result = _engine().derive(facts)
    assert result.visible_findings == []
    assert result.confirmation_items == []


def test_missing_shower_chair_requires_full_coverage_evidence() -> None:
    cannot_determine = _facts(
        room_type="bathroom",
        entities=[],
        feature_observations=[
            {
                "feature_key": "has_shower_chair",
                "state": "cannot_determine",
                "evidence_bbox": None,
                "model_score": 0.9,
            }
        ],
    )
    absent_with_coverage = _facts(
        room_type="bathroom",
        entities=[],
        feature_observations=[
            {
                "feature_key": "has_shower_chair",
                "state": "absent_with_full_coverage",
                "evidence_bbox": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
                "model_score": 0.9,
            }
        ],
    )

    cannot_determine_result = _engine().derive(cannot_determine)
    assert cannot_determine_result.visible_findings == []
    assert cannot_determine_result.confirmation_items == []

    result = _engine().derive(absent_with_coverage)
    assert result.visible_findings == []
    assert [item.feature_key for item in result.confirmation_items] == [
        "has_shower_chair"
    ]


@pytest.mark.parametrize(
    "facts",
    [
        _facts(environment="non_home"),
        _facts(environment="uncertain"),
        _facts(room_type="unknown"),
    ],
)
def test_non_home_or_unknown_room_does_not_derive_findings(facts: VisionFacts) -> None:
    result = _engine().derive(facts)
    assert result.visible_findings == []
    assert result.confirmation_items == []


@pytest.mark.parametrize("visibility", ["partial", "uncertain"])
def test_partial_or_uncertain_entity_does_not_derive_findings(visibility: str) -> None:
    facts = _facts(
        entities=[
            {
                "ref": "e1",
                "ontology_key": "hallway_cord",
                "bbox": {"x": 0.1, "y": 0.6, "w": 0.5, "h": 0.1},
                "visibility": visibility,
                "model_score": 0.9,
            }
        ],
        relationships=[
            {"subject": "e1", "predicate": "intersects", "object": "walking_path"}
        ],
    )

    result = _engine().derive(facts)
    assert result.visible_findings == []
    assert result.confirmation_items == []


@pytest.mark.parametrize(
    ("room", "risk_type"),
    [
        ("genkan", "genkan_step"),
        ("hallway", "hallway_cord"),
        ("bathroom", "bathroom_slip"),
        ("toilet", "cluttered_path"),
        ("bedroom", "cluttered_path"),
        ("kitchen", "kitchen_slip"),
    ],
)
def test_mock_facts_include_required_relationship_for_each_room(
    room: RoomType, risk_type: str
) -> None:
    result = _engine().derive(mock_vision_facts(room))

    assert [finding.risk_type for finding in result.visible_findings] == [risk_type]
    assert result.confirmation_items == []
    assert all(
        feature.state == "cannot_determine"
        for feature in mock_vision_facts(room).feature_observations
    )
