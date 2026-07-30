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
        "confirmation_items_markdown": "確認項目",
        "family_actions_markdown": "",
        "care_manager_actions_markdown": "",
        "contractor_actions_markdown": "",
        "disclaimer_ja": "写真のみで最終判断しません。",
    }
    payload.update(overrides)
    return payload


def _finding_payload(
    *,
    ontology_key: str | None,
    ontology_rule_kind: str | None,
    risk_type: str = "hallway_cord",
) -> dict[str, object]:
    return {
        "id": "R1",
        "risk_type": risk_type,
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


def _action_payload(
    *,
    action_id: str = "A1",
    risk_id: str = "R1",
    tier: str = "FAMILY_NO_COST",
    cost_level: str = "ZERO",
    requires_professional: bool = False,
    title_ja: str = "コードを壁沿いに寄せる",
) -> dict[str, object]:
    return {
        "id": action_id,
        "risk_id": risk_id,
        "tier": tier,
        "title_ja": title_ja,
        "description_ja": "見えるコードを安全な位置へ移動します。",
        "why_ja": "つまずきの原因を減らすためです。",
        "cost_level": cost_level,
        "requires_professional": requires_professional,
        "disclaimer_ja": "無理のない範囲で行ってください。",
    }


def _confirmation_payload(
    *,
    confirmation_id: str = "C1",
    feature_key: str = "clear_path",
) -> dict[str, object]:
    return {
        "id": confirmation_id,
        "feature_key": feature_key,
        "label_ja": "確認項目",
        "description_ja": "写真外も含めて現地で確認してください。",
        "confidence": 0.8,
        "evidence_source_ids": [],
        "basis_label_ja": "写真で確認できる範囲",
        "basis_summary_ja": "写真だけでは実際の有無を判断できません。",
        "needs_human_confirmation": True,
    }


@pytest.mark.parametrize(
    ("ontology_key", "ontology_rule_kind"),
    [
        (None, None),
        ("hallway_cord", None),
        (None, "visible_hazard"),
        ("sufficient_lighting", "expected_feature"),
        ("", "visible_hazard"),
    ],
)
def test_applicable_response_rejects_finding_without_complete_visible_identity(
    ontology_key: str | None, ontology_rule_kind: str | None
) -> None:
    with pytest.raises(
        ValidationError, match="applicable_findings_must_be_visible_hazards"
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                findings=[
                    _finding_payload(
                        ontology_key=ontology_key,
                        ontology_rule_kind=ontology_rule_kind,
                    )
                ]
            )
        )


@pytest.mark.parametrize(
    ("ontology_key", "risk_type"),
    [
        ("sufficient_lighting", "hallway_cord"),
        ("unknown_key", "hallway_cord"),
        ("kitchen_slip", "kitchen_slip"),
        ("hallway_cord", "arbitrary_risk_type"),
    ],
)
def test_applicable_response_rejects_finding_outside_room_visible_ontology(
    ontology_key: str, risk_type: str
) -> None:
    with pytest.raises(
        ValidationError, match="applicable_findings_must_match_visible_ontology"
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                findings=[
                    _finding_payload(
                        ontology_key=ontology_key,
                        ontology_rule_kind="visible_hazard",
                        risk_type=risk_type,
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


def test_applicable_response_accepts_finding_with_complete_visible_identity() -> None:
    response = AnalysisResponse.model_validate(
        _analysis_response_payload(
            overall_risk_level="medium",
            findings=[
                _finding_payload(
                    ontology_key="hallway_cord",
                    ontology_rule_kind="visible_hazard",
                )
            ]
        )
    )

    assert len(response.findings) == 1


@pytest.mark.parametrize(
    "finding_ids",
    [
        ["risk-1"],
        ["R2", "R1"],
        ["R1", "R1"],
    ],
)
def test_analysis_response_requires_canonical_unique_finding_ids(
    finding_ids: list[str],
) -> None:
    findings = [
        {
            **_finding_payload(
                ontology_key="hallway_cord",
                ontology_rule_kind="visible_hazard",
            ),
            "id": finding_id,
        }
        for finding_id in finding_ids
    ]

    with pytest.raises(
        ValidationError,
        match="finding_ids_must_be_canonical",
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                overall_risk_level="medium",
                findings=findings,
            )
        )


@pytest.mark.parametrize("overall_risk_level", ["medium", "high"])
def test_analysis_response_zero_findings_requires_low_risk(
    overall_risk_level: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match="overall_risk_level_must_match_findings",
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                overall_risk_level=overall_risk_level,
            )
        )


def test_analysis_response_zero_findings_requires_empty_actions() -> None:
    with pytest.raises(
        ValidationError,
        match="zero_findings_require_empty_actions",
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                action_plan={"family_no_cost": [_action_payload(risk_id="C1")]},
            )
        )


@pytest.mark.parametrize(
    ("severity", "overall_risk_level"),
    [
        (1, "medium"),
        (2, "low"),
        (3, "high"),
        (4, "medium"),
        (5, "medium"),
    ],
)
def test_analysis_response_overall_risk_must_match_max_finding_severity(
    severity: int,
    overall_risk_level: str,
) -> None:
    finding = _finding_payload(
        ontology_key="hallway_cord",
        ontology_rule_kind="visible_hazard",
    )
    finding["severity"] = severity

    with pytest.raises(
        ValidationError,
        match="overall_risk_level_must_match_findings",
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                overall_risk_level=overall_risk_level,
                findings=[finding],
            )
        )


def test_analysis_response_action_must_reference_a_finding() -> None:
    with pytest.raises(
        ValidationError,
        match="action_risk_id_must_reference_finding",
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                overall_risk_level="medium",
                findings=[
                    _finding_payload(
                        ontology_key="hallway_cord",
                        ontology_rule_kind="visible_hazard",
                    )
                ],
                action_plan={
                    "family_no_cost": [_action_payload(risk_id="C1")],
                },
            )
        )


@pytest.mark.parametrize(
    ("action_plan", "error_code"),
    [
        (
            {
                "family_no_cost": [
                    _action_payload(
                        tier="CARE_MANAGER_PURCHASE",
                    )
                ]
            },
            "action_must_match_plan_tier",
        ),
        (
            {
                "family_no_cost": [
                    _action_payload(
                        cost_level="LOW",
                    )
                ]
            },
            "action_must_match_plan_policy",
        ),
        (
            {
                "family_no_cost": [
                    _action_payload(
                        requires_professional=True,
                    )
                ]
            },
            "action_must_match_plan_policy",
        ),
        (
            {
                "family_no_cost": [
                    _action_payload(
                        title_ja="専門業者に工事を依頼する",
                    )
                ]
            },
            "family_action_contains_forbidden_word",
        ),
        (
            {
                "care_manager_purchase": [
                    _action_payload(
                        tier="CONTRACTOR_CONSTRUCTION",
                        cost_level="HIGH",
                        requires_professional=True,
                    )
                ]
            },
            "action_must_match_plan_tier",
        ),
    ],
)
def test_analysis_response_rejects_action_plan_policy_mismatches(
    action_plan: dict[str, object],
    error_code: str,
) -> None:
    with pytest.raises(ValidationError, match=error_code):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                overall_risk_level="medium",
                findings=[
                    _finding_payload(
                        ontology_key="hallway_cord",
                        ontology_rule_kind="visible_hazard",
                    )
                ],
                action_plan=action_plan,
            )
        )


def test_analysis_response_action_ids_are_unique_across_tiers() -> None:
    with pytest.raises(
        ValidationError,
        match="action_ids_must_be_unique",
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                overall_risk_level="medium",
                findings=[
                    _finding_payload(
                        ontology_key="hallway_cord",
                        ontology_rule_kind="visible_hazard",
                    )
                ],
                action_plan={
                    "family_no_cost": [_action_payload(action_id="A1")],
                    "care_manager_purchase": [
                        _action_payload(
                            action_id="A1",
                            tier="CARE_MANAGER_PURCHASE",
                            cost_level="LOW",
                            requires_professional=True,
                        )
                    ],
                },
            )
        )


@pytest.mark.parametrize(
    "forbidden_word",
    ["購入", "レンタル", "工事", "施工", "設置を依頼", "専門"],
)
def test_analysis_response_rejects_every_family_forbidden_word(
    forbidden_word: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match="family_action_contains_forbidden_word",
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                overall_risk_level="medium",
                findings=[
                    _finding_payload(
                        ontology_key="hallway_cord",
                        ontology_rule_kind="visible_hazard",
                    )
                ],
                action_plan={
                    "family_no_cost": [
                        _action_payload(title_ja=f"{forbidden_word}する")
                    ],
                },
            )
        )


def test_analysis_response_accepts_consistent_finding_and_actions() -> None:
    response = AnalysisResponse.model_validate(
        _analysis_response_payload(
            overall_risk_level="medium",
            findings=[
                _finding_payload(
                    ontology_key="hallway_cord",
                    ontology_rule_kind="visible_hazard",
                )
            ],
            action_plan={
                "family_no_cost": [_action_payload()],
                "care_manager_purchase": [
                    _action_payload(
                        action_id="A2",
                        tier="CARE_MANAGER_PURCHASE",
                        cost_level="LOW",
                        requires_professional=True,
                    )
                ],
                "contractor_construction": [
                    _action_payload(
                        action_id="A3",
                        tier="CONTRACTOR_CONSTRUCTION",
                        cost_level="HIGH",
                        requires_professional=True,
                    )
                ],
            },
        )
    )

    assert response.overall_risk_level == "medium"
    assert len(response.action_plan.family_no_cost) == 1


@pytest.mark.parametrize("feature_key", ["has_handrail", "invented_device"])
def test_applicable_response_rejects_confirmation_outside_room_expected_ontology(
    feature_key: str,
) -> None:
    with pytest.raises(
        ValidationError,
        match="applicable_confirmation_items_must_match_expected_ontology",
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                room_type="hallway",
                confirmation_items=[
                    _confirmation_payload(feature_key=feature_key)
                ],
            )
        )


@pytest.mark.parametrize(
    "confirmation_items",
    [
        [_confirmation_payload(confirmation_id="pending")],
        [
            _confirmation_payload(
                confirmation_id="C2",
                feature_key="clear_path",
            ),
            _confirmation_payload(
                confirmation_id="C1",
                feature_key="sufficient_lighting",
            ),
        ],
    ],
)
def test_analysis_response_requires_canonical_confirmation_ids(
    confirmation_items: list[dict[str, object]],
) -> None:
    with pytest.raises(
        ValidationError,
        match="confirmation_ids_must_be_canonical",
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                confirmation_items=confirmation_items,
            )
        )


def test_analysis_response_requires_unique_confirmation_feature_keys() -> None:
    with pytest.raises(
        ValidationError,
        match="confirmation_feature_keys_must_be_unique",
    ):
        AnalysisResponse.model_validate(
            _analysis_response_payload(
                confirmation_items=[
                    _confirmation_payload(
                        confirmation_id="C1",
                        feature_key="clear_path",
                    ),
                    _confirmation_payload(
                        confirmation_id="C2",
                        feature_key="clear_path",
                    ),
                ],
            )
        )


def test_analysis_response_accepts_canonical_unique_confirmation_items() -> None:
    response = AnalysisResponse.model_validate(
        _analysis_response_payload(
            confirmation_items=[
                _confirmation_payload(
                    confirmation_id="C1",
                    feature_key="clear_path",
                ),
                _confirmation_payload(
                    confirmation_id="C2",
                    feature_key="sufficient_lighting",
                ),
            ],
        )
    )

    assert [item.id for item in response.confirmation_items] == ["C1", "C2"]


def test_analysis_response_requires_non_empty_confirmation_markdown() -> None:
    missing = _analysis_response_payload()
    missing.pop("confirmation_items_markdown")

    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(missing)
    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(
            _analysis_response_payload(confirmation_items_markdown="")
        )

    response = AnalysisResponse.model_validate(
        _analysis_response_payload(
            confirmation_items_markdown="写真だけでは確認できない項目"
        )
    )
    assert response.confirmation_items_markdown == "写真だけでは確認できない項目"


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
    assert item.basis_label_ja == "写真で確認できる範囲"
    assert item.basis_summary_ja == (
        "この項目は、現在の写真で通路の照明を確認できなかったという観察だけを"
        "示します。写真だけでは実際の有無や追加の必要性を判断できません。"
    )


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


def test_confirmation_serialized_copy_is_exact_neutral_boundary() -> None:
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
    assert item.description_ja == (
        "この写真では、浴室手すりを確認できませんでした。"
        "これは浴室手すりが存在しないことや、追加が必要なことを示すものではありません。"
    )
    assert item.basis_label_ja == "写真で確認できる範囲"
    assert item.basis_summary_ja == (
        "この項目は、現在の写真で浴室手すりを確認できなかったという観察だけを"
        "示します。写真だけでは実際の有無や追加の必要性を判断できません。"
    )
    serialized = item.model_dump()
    assert set(serialized).isdisjoint(
        {
            "risk_type",
            "severity",
            "bbox",
            "display_bbox",
            "family_actions",
            "care_manager_actions",
            "contractor_actions",
        }
    )
    serialized_copy = item.model_dump_json()
    for ontology_policy_fragment in (
        "住宅改修の検討対象",
        "設置・貸与する自治体事業",
        "極めて重要",
    ):
        assert ontology_policy_fragment not in serialized_copy


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


def test_toilet_without_explicit_visible_obstacle_has_no_visible_risk() -> None:
    result = _engine().derive(
        _facts(
            room_type="toilet",
            visible_regions=["room"],
            entities=[],
            feature_observations=[
                {
                    "feature_key": "has_handrail",
                    "state": "absent_with_full_coverage",
                    "evidence_bbox": {
                        "x": 0.1,
                        "y": 0.1,
                        "w": 0.8,
                        "h": 0.8,
                    },
                    "model_score": 0.9,
                }
            ],
            relationships=[],
        )
    )

    assert result.visible_findings == []
    assert [item.feature_key for item in result.confirmation_items] == [
        "has_handrail"
    ]


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
        ("kitchen", "cluttered_path"),
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


@pytest.mark.parametrize(
    ("room_type", "ontology_key", "predicate", "target"),
    [
        ("toilet", "space_looks_narrow", "obstructs", "walking_path"),
        ("toilet", "looks_slippery_floor", "located_in", "floor"),
        ("kitchen", "kitchen_slip", "located_in", "floor"),
        ("kitchen", "reachable_storage_issue", "located_in", "storage"),
    ],
)
def test_non_visual_inference_keys_never_derive_visible_findings(
    room_type: str,
    ontology_key: str,
    predicate: str,
    target: str,
) -> None:
    result = _engine().derive(
        _facts(
            room_type=room_type,
            visible_regions=[target],
            entities=[
                {
                    "ref": "e1",
                    "ontology_key": ontology_key,
                    "bbox": {"x": 0.2, "y": 0.2, "w": 0.3, "h": 0.3},
                    "visibility": "clear",
                    "model_score": 0.99,
                }
            ],
            feature_observations=[],
            relationships=[
                {"subject": "e1", "predicate": predicate, "object": target}
            ],
        )
    )

    assert result.visible_findings == []
    assert result.confirmation_items == []


def test_explicit_localized_wet_floor_still_derives_bathroom_slip() -> None:
    result = _engine().derive(
        _facts(
            room_type="bathroom",
            visible_regions=["floor"],
            entities=[
                {
                    "ref": "e1",
                    "ontology_key": "wet_floor",
                    "bbox": {"x": 0.2, "y": 0.6, "w": 0.3, "h": 0.2},
                    "visibility": "clear",
                    "model_score": 0.9,
                }
            ],
            feature_observations=[],
            relationships=[
                {"subject": "e1", "predicate": "located_in", "object": "floor"}
            ],
        )
    )

    assert [finding.risk_type for finding in result.visible_findings] == [
        "bathroom_slip"
    ]
