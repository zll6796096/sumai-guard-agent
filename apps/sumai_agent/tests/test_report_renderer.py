from __future__ import annotations

from app.models import VisionFacts
from app.ontology import OntologyRepository
from app.services.relationship_engine import RelationshipEngine
from app.services.report_renderer import ReportRenderer
from app.services.rule_engine import RuleEngine


def _toilet_missing_feature_result():
    ontology = OntologyRepository.load_default()
    facts = VisionFacts.model_validate(
        {
            "environment": "home",
            "room_type": "toilet",
            "visible_regions": [],
            "entities": [],
            "feature_observations": [
                {
                    "feature_key": "has_handrail",
                    "state": "absent_with_full_coverage",
                    "evidence_bbox": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.8},
                    "model_score": 1.0,
                },
                {
                    "feature_key": "has_emergency_call_button",
                    "state": "absent_with_full_coverage",
                    "evidence_bbox": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.8},
                    "model_score": 1.0,
                },
            ],
            "relationships": [],
            "not_applicable_reason_code": None,
        }
    )
    derived = RelationshipEngine(ontology).derive(facts)
    return RuleEngine(ontology=ontology).apply(derived, "toilet")


def test_missing_features_are_reported_as_unlocalized_checks_not_danger_locations() -> None:
    findings, action_plan = _toilet_missing_feature_result()

    reports = ReportRenderer().render(
        room_type="toilet",
        overall_risk_level="high",
        findings=findings,
        action_plan=action_plan,
    )

    summary = reports["risk_summary_markdown"]
    assert summary.count("### 写真内で確認できなかった設備:") == 2
    assert "### 注意箇所:" not in summary
    assert "画像上の位置表示: なし" in summary
    assert "不存在や設置位置を示すものではありません" in summary
    assert "支え不足を確認できませんでした" not in summary

    for key in (
        "family_actions_markdown",
        "care_manager_actions_markdown",
        "contractor_actions_markdown",
    ):
        markdown = reports[key]
        assert "今回検出された危険箇所" not in markdown
        if "###" in markdown:
            assert "写真内で確認できなかった設備（画像上の位置表示なし）" in markdown


def test_missing_feature_action_reasons_do_not_turn_non_detection_into_a_confirmed_risk() -> None:
    _, action_plan = _toilet_missing_feature_result()
    actions = [
        *action_plan.family_no_cost,
        *action_plan.care_manager_purchase,
        *action_plan.contractor_construction,
    ]

    assert actions
    assert all("でしたのリスク" not in action.why_ja for action in actions)
    assert all("写真内で確認できなかった" in action.why_ja for action in actions)
