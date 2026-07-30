from __future__ import annotations

from app.models import BoundingBox, RiskFinding
from app.ontology import OntologyRepository
from app.services.relationship_engine import RelationshipEngine
from app.services.rule_engine import RuleEngine
from app.models import VisionFacts


def _finding(
    risk_type: str = "hallway_cord",
    confidence: float = 0.8,
    severity: int = 3,
) -> RiskFinding:
    return RiskFinding(
        id="R1",
        risk_type=risk_type,
        label_ja="廊下の電源コード",
        description_ja="動線上に電源コードが見えます。",
        severity=severity,
        confidence=confidence,
        bbox=BoundingBox(x=0.1, y=0.2, w=0.4, h=0.2),
        evidence_ja="床の通路部分にコードが横切っています。",
        basis_label_ja="",
        basis_summary_ja="",
        needs_human_confirmation=False,
    )


def test_rule_engine_keeps_family_actions_no_cost_only() -> None:
    engine = RuleEngine()

    findings, plan = engine.apply([_finding("loose_mat")], "hallway")

    assert findings[0].basis_label_ja
    assert plan.family_no_cost
    for action in plan.family_no_cost:
        text = f"{action.title_ja} {action.description_ja}"
        assert action.cost_level == "ZERO"
        assert not action.requires_professional
        assert "購入" not in text
        assert "レンタル" not in text
        assert "工事" not in text
        assert "施工" not in text


def test_rule_engine_marks_low_confidence_for_human_confirmation() -> None:
    engine = RuleEngine()

    findings, _ = engine.apply([_finding(confidence=0.52)], "hallway")

    assert len(findings) == 1
    assert findings[0].needs_human_confirmation is True


def test_legacy_known_visible_risk_gets_rule_kind_for_visual_rendering() -> None:
    findings, _ = RuleEngine().apply([_finding("hallway_cord")], "hallway")

    assert findings[0].ontology_key == "hallway_cord"
    assert findings[0].ontology_rule_kind == "visible_hazard"


def test_legacy_expected_feature_always_requires_human_confirmation() -> None:
    finding = _finding("toilet_missing_handrail", confidence=0.9).model_copy(
        update={"needs_human_confirmation": False}
    )

    findings, plan = RuleEngine().apply([finding], "toilet")

    assert findings[0].ontology_key == "has_handrail"
    assert findings[0].ontology_rule_kind == "expected_feature"
    assert findings[0].needs_human_confirmation is True
    assert all(
        "写真内で確認できなかった設備" in action.why_ja
        for action in (
            *plan.family_no_cost,
            *plan.care_manager_purchase,
            *plan.contractor_construction,
        )
    )


def test_rule_engine_actions_follow_exact_relationship_rule_identity() -> None:
    ontology = OntologyRepository.load_default()
    facts = VisionFacts.model_validate(
        {
            "environment": "home",
            "room_type": "genkan",
            "visible_regions": ["walking_path"],
            "entities": [
                {
                    "ref": "e1",
                    "ontology_key": "cluttered_path",
                    "bbox": {"x": 0.7, "y": 0.1, "w": 0.1, "h": 0.1},
                    "visibility": "clear",
                    "model_score": 0.9,
                }
            ],
            "feature_observations": [],
            "relationships": [
                {"subject": "e1", "predicate": "obstructs", "object": "walking_path"}
            ],
            "not_applicable_reason_code": None,
        }
    )
    derived = RelationshipEngine(ontology).derive(facts)

    findings, plan = RuleEngine(ontology=ontology).apply(derived, "genkan")

    assert findings[0].ontology_key == "cluttered_path"
    assert findings[0].label_ja == "玄関動線の障害物"
    assert [action.title_ja for action in plan.family_no_cost] == [
        "動線上の荷物を片付ける"
    ]


def test_exact_rule_identity_overrides_stale_label_basis_and_severity() -> None:
    finding = _finding("cluttered_path", severity=5).model_copy(
        update={
            "label_ja": "誤った表示",
            "basis_label_ja": "誤った根拠",
            "basis_summary_ja": "誤った要約",
            "ontology_key": "cluttered_path",
            "ontology_rule_kind": "visible_hazard",
        }
    )

    findings, plan = RuleEngine().apply([finding], "genkan")

    assert findings[0].label_ja == "玄関動線の障害物"
    assert findings[0].severity == 3
    assert findings[0].basis_label_ja == "消費者庁 転倒予防ポイントに基づく一般注意"
    assert findings[0].basis_summary_ja.startswith("玄関まわりの荷物や傘立て等")
    assert [action.title_ja for action in plan.family_no_cost] == [
        "動線上の荷物を片付ける"
    ]
