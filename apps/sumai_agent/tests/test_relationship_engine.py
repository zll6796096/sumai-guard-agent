from __future__ import annotations

import pytest

from app.models import RoomType, VisionFacts
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


def test_hallway_cord_requires_intersects_relationship() -> None:
    facts = _facts()

    assert _engine().derive(facts) == []

    findings = _engine().derive(
        _facts(
            relationships=[
                {"subject": "e1", "predicate": "intersects", "object": "walking_path"}
            ]
        )
    )

    assert [finding.risk_type for finding in findings] == ["hallway_cord"]
    assert findings[0].id == "pending"
    assert findings[0].confidence == 0.9
    assert findings[0].display_bbox is None


def test_hallway_cord_requires_configured_relationship_target() -> None:
    findings = _engine().derive(
        _facts(
            visible_regions=["walking_path", "wall"],
            relationships=[
                {"subject": "e1", "predicate": "intersects", "object": "wall"}
            ],
        )
    )

    assert findings == []


def test_visible_hazard_with_full_frame_placeholder_is_not_derived() -> None:
    findings = _engine().derive(
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

    assert findings == []


def test_visible_rule_identity_uses_observation_key_not_duplicate_risk_type() -> None:
    findings = _engine().derive(
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

    assert len(findings) == 1
    assert findings[0].ontology_key == "cluttered_path"
    assert findings[0].ontology_rule_kind == "visible_hazard"
    assert findings[0].label_ja == "玄関動線の障害物"
    assert findings[0].basis_summary_ja.startswith("玄関まわりの荷物や傘立て等")


def test_missing_rule_identity_does_not_select_visible_rule_with_same_risk_type() -> None:
    findings = _engine().derive(
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

    assert len(findings) == 1
    assert findings[0].ontology_key == "sufficient_lighting"
    assert findings[0].ontology_rule_kind == "expected_feature"
    assert findings[0].label_ja == "通路の明るさ不足"
    assert findings[0].basis_summary_ja.startswith("夜間のトイレ移動など")


def test_bedroom_expected_and_visible_lighting_rules_remain_distinct() -> None:
    facts = _facts(
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

    findings = _engine().derive(facts)

    assert [
        (finding.ontology_key, finding.ontology_rule_kind, finding.label_ja)
        for finding in findings
    ] == [
        ("poor_lighting", "visible_hazard", "寝室の暗さ"),
        ("bedside_light", "expected_feature", "枕元の明かり不足"),
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

    assert _engine().derive(facts) == []


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

    assert _engine().derive(facts) == []

    findings = _engine().derive(
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

    assert [finding.risk_type for finding in findings] == ["bathroom_missing_handrail"]
    assert findings[0].evidence_source_ids == [
        "MHLW_WELFARE_HOUSING",
        "MHLW_NOTICE_OLD34",
    ]
    assert findings[0].needs_human_confirmation is True
    assert findings[0].description_ja == (
        "写真で十分に表示された範囲では、浴室手すりを確認できませんでした。"
    )
    assert "設置位置を示すものではありません" in findings[0].evidence_ja


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

    assert _engine().derive(facts) == []


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

    assert _engine().derive(facts) == []


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

    assert _engine().derive(cannot_determine) == []
    assert [finding.risk_type for finding in _engine().derive(absent_with_coverage)] == [
        "bathroom_no_shower_chair"
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
    assert _engine().derive(facts) == []


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

    assert _engine().derive(facts) == []


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
    findings = _engine().derive(mock_vision_facts(room))

    assert [finding.risk_type for finding in findings] == [risk_type]
    assert all(
        feature.state == "cannot_determine"
        for feature in mock_vision_facts(room).feature_observations
    )
