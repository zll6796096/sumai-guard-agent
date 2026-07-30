from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image

from app.models import (
    ActionPlan,
    BoundingBox,
    ConfirmationItem,
    RiskFinding,
    VisionFacts,
)
from app.ontology import OntologyRepository
from app.services import canonicalization, orchestrator
from app.services.canonicalization import (
    canonical_pixel_digest,
    canonicalize_findings,
    result_key,
    semantic_hash,
)
from app.services.orchestrator import analysis_semantic_payload
from app.services.rule_engine import RuleEngine
from app.services.relationship_engine import RelationshipEngine


def _finding(
    *,
    risk_type: str,
    severity: int,
    confidence: float,
    bbox: BoundingBox,
    label: str = "テスト",
) -> RiskFinding:
    return RiskFinding(
        id="pending",
        risk_type=risk_type,
        label_ja=label,
        description_ja=f"{label}が見えます。",
        severity=severity,
        confidence=confidence,
        bbox=bbox,
        evidence_ja="写真内の根拠です。",
        basis_label_ja="根拠",
        basis_summary_ja="根拠の要約です。",
        needs_human_confirmation=False,
    )


def _confirmation(
    *,
    feature_key: str,
    confidence: float,
    label: str,
    description: str = "写真だけでは確認できません。",
) -> ConfirmationItem:
    return ConfirmationItem(
        id="pending",
        feature_key=feature_key,
        label_ja=label,
        description_ja=description,
        confidence=confidence,
        evidence_source_ids=["source-1"],
        basis_label_ja="確認根拠",
        basis_summary_ja="現地で確認する項目です。",
        needs_human_confirmation=True,
    )


def test_canonical_pixel_digest_is_stable_for_equal_pixels() -> None:
    image = Image.new("RGB", (3, 2), (10, 20, 30))

    assert canonical_pixel_digest(image) == canonical_pixel_digest(image.copy())


def test_result_key_changes_for_each_identity_input() -> None:
    base = dict(
        pixel_digest="pixel",
        room_hint="genkan",
        preprocess_version="1.0.0",
        ontology_version="1.0.0",
        schema_version="2.0.0",
        model="gemini-test",
        inference_config_version="1.0.0",
        execution_mode="forced_mock",
    )
    baseline = result_key(**base)

    for field, replacement in {
        "room_hint": "bathroom",
        "preprocess_version": "2.0.0",
        "ontology_version": "2.0.0",
        "schema_version": "3.0.0",
        "model": "gemini-other",
        "inference_config_version": "2.0.0",
        "execution_mode": "configured_mock",
    }.items():
        changed = {**base, field: replacement}
        assert result_key(**changed) != baseline


def test_result_key_uses_unambiguous_canonical_encoding() -> None:
    common = dict(
        pixel_digest="pixel",
        room_hint="genkan",
        preprocess_version="1.0.0",
        ontology_version="1.0.0",
        schema_version="2.0.0",
        execution_mode="forced_mock",
    )

    first = result_key(model="model|i", inference_config_version="c", **common)
    second = result_key(model="model", inference_config_version="i|c", **common)

    assert first != second
    assert first == result_key(model="model|i", inference_config_version="c", **common)


def test_canonicalize_confirmation_items_is_order_independent_and_non_mutating() -> None:
    call_button = _confirmation(
        feature_key="has_emergency_call_button",
        confidence=0.8,
        label="緊急通報ボタン",
    )
    handrail = _confirmation(
        feature_key="has_handrail",
        confidence=0.9,
        label="手すり",
    )
    duplicate_handrail = handrail.model_copy(
        update={"id": "duplicate", "confidence": 0.7, "label_ja": "補助手すり"}
    )
    original = [
        item.model_dump(mode="json")
        for item in (call_button, handrail, duplicate_handrail)
    ]

    forward = canonicalization.canonicalize_confirmation_items(
        [handrail, duplicate_handrail, call_button]
    )
    reverse = canonicalization.canonicalize_confirmation_items(
        [call_button, duplicate_handrail, handrail]
    )

    assert [item.model_dump(mode="json") for item in forward] == [
        item.model_dump(mode="json") for item in reverse
    ]
    assert [item.id for item in forward] == ["C1", "C2"]
    assert [item.feature_key for item in forward] == [
        "has_emergency_call_button",
        "has_handrail",
    ]
    assert [item.label_ja for item in forward] == ["緊急通報ボタン", "手すり"]
    assert [
        item.model_dump(mode="json")
        for item in (call_button, handrail, duplicate_handrail)
    ] == original
    assert all(
        canonical is not source
        for canonical, source in zip(forward, (call_button, handrail), strict=True)
    )


def test_canonicalize_confirmation_items_uses_full_dump_tiebreak_and_signed_zero() -> None:
    lexical_winner = _confirmation(
        feature_key="has_handrail",
        confidence=0.8,
        label="手すり",
        description="A",
    )
    lexical_loser = lexical_winner.model_copy(
        update={"id": "other", "description_ja": "B"}
    )
    negative_zero = _confirmation(
        feature_key="has_emergency_call_button",
        confidence=-0.0,
        label="緊急通報ボタン",
    )
    positive_zero = negative_zero.model_copy(
        update={"id": "positive", "confidence": 0.0}
    )
    original = [
        item.model_dump(mode="json")
        for item in (lexical_winner, lexical_loser, negative_zero, positive_zero)
    ]

    forward = canonicalization.canonicalize_confirmation_items(
        [lexical_loser, positive_zero, lexical_winner, negative_zero]
    )
    reverse = canonicalization.canonicalize_confirmation_items(
        [negative_zero, lexical_winner, positive_zero, lexical_loser]
    )

    assert [item.model_dump(mode="json") for item in forward] == [
        item.model_dump(mode="json") for item in reverse
    ]
    assert [item.description_ja for item in forward] == [
        "写真だけでは確認できません。",
        "A",
    ]
    assert forward[0].confidence == 0.0
    assert str(forward[0].confidence) == "0.0"
    assert [
        item.model_dump(mode="json")
        for item in (lexical_winner, lexical_loser, negative_zero, positive_zero)
    ] == original


def test_canonicalize_findings_deduplicates_same_class_high_iou_deterministically() -> None:
    preferred = _finding(
        risk_type="cluttered_path",
        severity=4,
        confidence=0.9,
        bbox=BoundingBox(x=0.1, y=0.1, w=0.4, h=0.4),
        label="優先",
    )
    duplicate = _finding(
        risk_type="cluttered_path",
        severity=3,
        confidence=0.8,
        bbox=BoundingBox(x=0.12, y=0.12, w=0.4, h=0.4),
        label="重複",
    )
    other_class = duplicate.model_copy(
        update={"risk_type": "loose_mat", "label_ja": "別クラス"}
    )

    forward = canonicalize_findings([duplicate, other_class, preferred])
    reverse = canonicalize_findings([preferred, other_class, duplicate])

    assert [item.model_dump(mode="json") for item in forward] == [
        item.model_dump(mode="json") for item in reverse
    ]
    assert [(item.risk_type, item.label_ja) for item in forward] == [
        ("cluttered_path", "優先"),
        ("loose_mat", "別クラス"),
    ]
    forward_findings, forward_plan = RuleEngine().apply(forward, "genkan")
    reverse_findings, reverse_plan = RuleEngine().apply(reverse, "genkan")
    assert semantic_hash(
        analysis_semantic_payload("genkan", forward_findings, forward_plan)
    ) == semantic_hash(
        analysis_semantic_payload("genkan", reverse_findings, reverse_plan)
    )
    action_titles = [
        action.title_ja
        for action in (
            *forward_plan.family_no_cost,
            *forward_plan.care_manager_purchase,
            *forward_plan.contractor_construction,
        )
    ]
    assert len(action_titles) == len(set(action_titles))


def test_exact_ontology_identities_with_same_risk_and_bbox_are_not_deduplicated() -> None:
    ontology = OntologyRepository.load_default()
    bbox = {"x": 0.2, "y": 0.6, "w": 0.3, "h": 0.2}
    facts = VisionFacts.model_validate(
        {
            "environment": "home",
            "room_type": "genkan",
            "visible_regions": ["walking_path"],
            "entities": [
                {
                    "ref": "shoes",
                    "ontology_key": "loose_shoes",
                    "bbox": bbox,
                    "visibility": "clear",
                    "model_score": 0.9,
                },
                {
                    "ref": "parcel",
                    "ontology_key": "cluttered_path",
                    "bbox": bbox,
                    "visibility": "clear",
                    "model_score": 0.9,
                },
            ],
            "feature_observations": [],
            "relationships": [
                {
                    "subject": "shoes",
                    "predicate": "obstructs",
                    "object": "walking_path",
                },
                {
                    "subject": "parcel",
                    "predicate": "obstructs",
                    "object": "walking_path",
                },
            ],
            "not_applicable_reason_code": None,
        }
    )

    derived = RelationshipEngine(ontology).derive(facts).visible_findings
    canonical = canonicalize_findings(derived)
    reversed_canonical = canonicalize_findings(list(reversed(derived)))
    findings, plan = RuleEngine(ontology=ontology).apply(canonical, "genkan")

    assert [item.model_dump(mode="json") for item in canonical] == [
        item.model_dump(mode="json") for item in reversed_canonical
    ]
    assert {finding.ontology_key for finding in findings} == {
        "cluttered_path",
        "loose_shoes",
    }
    assert {action.title_ja for action in plan.family_no_cost} == {
        "動線上の荷物を片付ける",
        "履かない靴は靴箱に収納する",
        "床面を片付ける",
    }


def test_exact_identity_duplicate_still_deduplicates_at_high_iou() -> None:
    base = _finding(
        risk_type="cluttered_path",
        severity=3,
        confidence=0.9,
        bbox=BoundingBox(x=0.1, y=0.1, w=0.4, h=0.4),
    ).model_copy(
        update={
            "ontology_key": "cluttered_path",
            "ontology_rule_kind": "visible_hazard",
        }
    )
    duplicate = base.model_copy(
        update={"bbox": BoundingBox(x=0.12, y=0.12, w=0.4, h=0.4)}
    )

    assert len(canonicalize_findings([duplicate, base])) == 1


def test_display_bbox_cannot_change_canonical_winner_or_semantic_hash() -> None:
    first_evidence = BoundingBox(x=0.1, y=0.1, w=0.4, h=0.4)
    second_evidence = BoundingBox(x=0.12, y=0.12, w=0.4, h=0.4)
    left_display = BoundingBox(x=0.05, y=0.05, w=0.1, h=0.1)
    right_display = BoundingBox(x=0.8, y=0.8, w=0.1, h=0.1)
    base = _finding(
        risk_type="cluttered_path",
        severity=3,
        confidence=0.9,
        bbox=first_evidence,
    ).model_copy(
        update={
            "ontology_key": "cluttered_path",
            "ontology_rule_kind": "visible_hazard",
        }
    )
    nearby = base.model_copy(update={"bbox": second_evidence})

    first = canonicalize_findings(
        [
            base.model_copy(update={"display_bbox": left_display}),
            nearby.model_copy(update={"display_bbox": right_display}),
        ]
    )
    swapped = canonicalize_findings(
        [
            base.model_copy(update={"display_bbox": right_display}),
            nearby.model_copy(update={"display_bbox": left_display}),
        ]
    )

    assert [item.model_dump(mode="json") for item in first] == [
        item.model_dump(mode="json") for item in swapped
    ]
    assert first[0].bbox == first_evidence
    assert first[0].display_bbox is None
    assert semantic_hash(
        analysis_semantic_payload("genkan", first, ActionPlan())
    ) == semantic_hash(
        analysis_semantic_payload("genkan", swapped, ActionPlan())
    )


@pytest.mark.parametrize(
    ("force_mock", "mock_mode", "require_real_gemini", "gemini_api_key", "expected"),
    [
        (True, False, False, "key", "forced_mock"),
        (False, True, False, "key", "configured_mock"),
        (False, False, False, "", "missing_key_mock"),
        (True, True, True, "key", "strict_gemini"),
        (False, False, False, "key", "gemini_with_fallback"),
    ],
)
def test_execution_mode_matches_provider_branch(
    monkeypatch: pytest.MonkeyPatch,
    force_mock: bool,
    mock_mode: bool,
    require_real_gemini: bool,
    gemini_api_key: str,
    expected: str,
) -> None:
    monkeypatch.setattr(
        orchestrator,
        "settings",
        SimpleNamespace(
            mock_mode=mock_mode,
            require_real_gemini=require_real_gemini,
            gemini_api_key=gemini_api_key,
        ),
    )

    assert orchestrator.execution_mode_for_request(force_mock=force_mock) == expected


def test_canonicalize_findings_is_input_order_independent_and_non_mutating() -> None:
    lower = _finding(
        risk_type="alpha",
        severity=3,
        confidence=0.72,
        bbox=BoundingBox(x=0.1004, y=0.2004, w=0.3004, h=0.4004),
        label="低",
    )
    higher = _finding(
        risk_type="beta",
        severity=4,
        confidence=0.82,
        bbox=BoundingBox(x=0.1005, y=0.2005, w=0.3005, h=0.4005),
        label="高",
    )
    original_lower = lower.model_dump(mode="json")
    original_higher = higher.model_dump(mode="json")

    forward = canonicalize_findings([lower, higher])
    reverse = canonicalize_findings([higher, lower])

    assert [item.model_dump(mode="json") for item in forward] == [
        item.model_dump(mode="json") for item in reverse
    ]
    assert [item.id for item in forward] == ["R1", "R2"]
    assert forward[0].risk_type == "beta"
    assert forward[0].bbox == BoundingBox(x=0.1005, y=0.2005, w=0.3005, h=0.4005)
    assert lower.model_dump(mode="json") == original_lower
    assert higher.model_dump(mode="json") == original_higher


def test_canonicalize_findings_keeps_rounded_evidence_bbox_in_frame() -> None:
    finding = _finding(
        risk_type="edge",
        severity=3,
        confidence=0.8,
        bbox=BoundingBox(x=0.9996, y=0.9996, w=0.0004, h=0.0004),
    )

    rounded = canonicalize_findings([finding])[0].bbox

    assert rounded.x + rounded.w <= 1.0
    assert rounded.y + rounded.h <= 1.0
    assert rounded == finding.bbox
    assert rounded.w > 0
    assert rounded.h > 0


def test_canonicalize_findings_discards_presentation_only_display_bbox() -> None:
    base = _finding(
        risk_type="same",
        severity=3,
        confidence=0.8,
        bbox=BoundingBox(x=0.1, y=0.2, w=0.3, h=0.4),
    )
    left = base.model_copy(
        update={"display_bbox": BoundingBox(x=0.1, y=0.1, w=0.2, h=0.2)}
    )
    right = base.model_copy(
        update={"display_bbox": BoundingBox(x=0.6, y=0.6, w=0.2, h=0.2)}
    )

    forward = canonicalize_findings([left, right])
    reverse = canonicalize_findings([right, left])

    assert [item.model_dump(mode="json") for item in forward] == [
        item.model_dump(mode="json") for item in reverse
    ]
    assert forward[0].display_bbox is None


def test_semantic_hash_is_key_order_independent_but_detects_semantic_changes() -> None:
    first = {"room_type": "genkan", "findings": [{"id": "R1", "severity": 4}]}
    reordered = {"findings": [{"severity": 4, "id": "R1"}], "room_type": "genkan"}
    changed = {"room_type": "genkan", "findings": [{"id": "R1", "severity": 3}]}

    assert semantic_hash(first) == semantic_hash(reordered)
    assert semantic_hash(first) != semantic_hash(changed)


def test_semantic_payload_excludes_display_bbox() -> None:
    finding = _finding(
        risk_type="alpha",
        severity=3,
        confidence=0.8,
        bbox=BoundingBox(x=0.1, y=0.2, w=0.3, h=0.4),
    )
    displayed = finding.model_copy(
        update={"display_bbox": BoundingBox(x=0.5, y=0.5, w=0.2, h=0.2)}
    )

    assert semantic_hash(analysis_semantic_payload("genkan", [finding], ActionPlan())) == semantic_hash(
        analysis_semantic_payload("genkan", [displayed], ActionPlan())
    )


def test_signed_zero_evidence_is_canonical_for_output_and_semantic_hash() -> None:
    negative_zero = _finding(
        risk_type="alpha",
        severity=3,
        confidence=0.8,
        bbox=BoundingBox(x=-0.0, y=-0.0, w=0.3, h=0.4),
    )
    positive_zero = negative_zero.model_copy(
        update={"bbox": BoundingBox(x=0.0, y=0.0, w=0.3, h=0.4)}
    )

    canonical_negative = canonicalize_findings([negative_zero])
    canonical_positive = canonicalize_findings([positive_zero])

    assert canonical_negative[0].model_dump(mode="json") == canonical_positive[0].model_dump(mode="json")
    assert semantic_hash(
        analysis_semantic_payload("genkan", canonical_negative, ActionPlan())
    ) == semantic_hash(analysis_semantic_payload("genkan", canonical_positive, ActionPlan()))


def test_not_applicable_semantics_distinguish_publicly_distinct_outputs() -> None:
    common = dict(room_type="auto", findings=[], action_plan=ActionPlan())
    non_home = analysis_semantic_payload(
        **common,
        is_home_environment=False,
        not_applicable_reason_ja="住宅内の安全確認対象ではない可能性があります。",
    )
    unknown_room = analysis_semantic_payload(
        **common,
        is_home_environment=True,
        not_applicable_reason_ja="写真から確認対象の部屋を特定できないため、結果を表示していません。",
    )
    insufficient_visibility = analysis_semantic_payload(
        **common,
        is_home_environment=True,
        not_applicable_reason_ja="写真から十分に確認できないため、結果を表示していません。",
    )

    assert len({semantic_hash(non_home), semantic_hash(unknown_room), semantic_hash(insufficient_visibility)}) == 3
    assert semantic_hash(unknown_room) == semantic_hash(
        analysis_semantic_payload(
            **common,
            is_home_environment=True,
            not_applicable_reason_ja="写真から確認対象の部屋を特定できないため、結果を表示していません。",
        )
    )
