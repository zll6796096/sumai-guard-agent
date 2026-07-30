from __future__ import annotations

import base64
import io
from PIL import Image
import pytest

from app.models import BoundingBox, RiskFinding
from app.services.visual_renderer import (
    VisualRenderer,
    _select_visual_findings,
    _compute_iou,
    DANGER_LABELS,
    _improvement_label
)


def _make_finding(
    id_val: str,
    risk_type: str,
    severity: int,
    confidence: float,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    rule_kind: str = "visible_hazard",
    ontology_key: str | None = None,
) -> RiskFinding:
    return RiskFinding(
        id=id_val,
        risk_type=risk_type,
        label_ja="テスト",
        description_ja="テスト",
        severity=severity,
        confidence=confidence,
        bbox=BoundingBox(x=x, y=y, w=w, h=h),
        evidence_ja="テスト",
        basis_label_ja="テスト",
        basis_summary_ja="テスト",
        needs_human_confirmation=False,
        ontology_key=ontology_key or risk_type,
        ontology_rule_kind=rule_kind,
    )


def test_max_3_danger_annotations() -> None:
    # 1. Visual renderer draws at most 3 danger annotations.
    findings = [
        _make_finding("F1", "genkan_step", 5, 0.9, 0.1, 0.1, 0.1, 0.1),
        _make_finding("F2", "hallway_cord", 4, 0.8, 0.3, 0.3, 0.1, 0.1),
        _make_finding("F3", "cluttered_path", 3, 0.7, 0.5, 0.5, 0.1, 0.1),
        _make_finding("F4", "poor_lighting", 2, 0.6, 0.7, 0.7, 0.1, 0.1),
    ]
    selected = _select_visual_findings(findings, "genkan", max_items=3)
    assert len(selected) <= 3
    # Check that rendering runs successfully
    img = Image.new("RGB", (640, 480), "white")
    annotated, _ = VisualRenderer().render(img, findings)
    assert annotated.startswith("iVBORw0KGgo")  # valid base64 PNG header representation


def test_max_3_improvement_callouts() -> None:
    # 2. Visual renderer draws at most 3 improvement callouts.
    findings = [
        _make_finding("F1", "genkan_step", 5, 0.9, 0.1, 0.1, 0.1, 0.1),
        _make_finding("F2", "hallway_cord", 4, 0.8, 0.3, 0.3, 0.1, 0.1),
        _make_finding("F3", "cluttered_path", 3, 0.7, 0.5, 0.5, 0.1, 0.1),
        _make_finding("F4", "poor_lighting", 2, 0.6, 0.7, 0.7, 0.1, 0.1),
    ]
    selected = _select_visual_findings(findings, "genkan", max_items=3)
    assert len(selected) <= 3
    # Check that rendering runs successfully
    img = Image.new("RGB", (640, 480), "white")
    _, improvement = VisualRenderer().render(img, findings)
    assert improvement.startswith("iVBORw0KGgo")


def test_no_yo_kakunin() -> None:
    # 3. Labels never include '要確認'.
    for label in DANGER_LABELS.values():
        assert "要確認" not in label
    # Also check the default fallback and improvement labels
    assert "要確認" not in _improvement_label("toilet_missing_handrail")
    assert "要確認" not in _improvement_label("unknown_type")


def test_no_r_indices() -> None:
    # 4. Labels never include R1/R2/R3.
    for label in DANGER_LABELS.values():
        assert not any(f"R{i}" in label for i in range(1, 10))
    for risk_type in ["genkan_step", "cluttered_path", "bathroom_slip"]:
        imp_lbl = _improvement_label(risk_type)
        assert not any(f"R{i}" in imp_lbl for i in range(1, 10))


def test_renderer_maps_only_visible_ontology_risk_types() -> None:
    from app.ontology import OntologyRepository
    from app.services.visual_renderer import IMPROVEMENT_LABELS

    ontology = OntologyRepository.load_default()
    visible_risk_types = {
        rule["risk_type"]
        for room in ontology.room_names
        for rule in (ontology.room(room) or {})["visible_hazards"]
    }
    expected_risk_types = {
        rule["missing_risk_type"]
        for room in ontology.room_names
        for rule in (ontology.room(room) or {})["expected_features"]
    }

    assert set(DANGER_LABELS) <= visible_risk_types
    assert set(IMPROVEMENT_LABELS) <= visible_risk_types
    assert set(DANGER_LABELS).isdisjoint(expected_risk_types)
    assert set(IMPROVEMENT_LABELS).isdisjoint(expected_risk_types)
    assert DANGER_LABELS["loose_mat"] == "敷物"


@pytest.mark.parametrize(
    ("room_type", "ontology_key", "risk_type"),
    [
        ("toilet", "space_looks_narrow", "toilet_transfer_support"),
        ("toilet", "looks_slippery_floor", "toilet_slip"),
        ("kitchen", "kitchen_slip", "kitchen_slip"),
        ("kitchen", "reachable_storage_issue", "kitchen_unreachable_storage"),
    ],
)
def test_removed_non_visual_rules_cannot_be_selected_for_overlay(
    room_type: str,
    ontology_key: str,
    risk_type: str,
) -> None:
    finding = _make_finding(
        "F1",
        risk_type,
        5,
        0.99,
        0.1,
        0.1,
        0.3,
        0.3,
        ontology_key=ontology_key,
    )

    assert _select_visual_findings([finding], room_type) == []


def test_expected_feature_findings_are_excluded_before_overlap_suppression() -> None:
    coverage = (0.0, 0.0, 1.0, 0.8)
    findings = [
        _make_finding(
            "F1",
            "toilet_missing_handrail",
            4,
            1.0,
            *coverage,
            rule_kind="expected_feature",
            ontology_key="has_handrail",
        ),
        _make_finding(
            "F2",
            "toilet_missing_emergency_call",
            2,
            1.0,
            *coverage,
            rule_kind="expected_feature",
            ontology_key="has_emergency_call_button",
        ),
    ]

    assert _select_visual_findings(findings, "toilet") == []


def test_overlapping_deduplication() -> None:
    # 6. Overlapping bboxes are deduplicated.
    # Two identical bboxes
    f1 = _make_finding("F1", "genkan_step", 5, 0.9, 0.1, 0.1, 0.2, 0.2)
    f2 = _make_finding("F2", "genkan_step", 4, 0.8, 0.1, 0.1, 0.2, 0.2)
    selected = _select_visual_findings([f1, f2], "genkan", max_items=3)
    # Only f1 should be selected because f2 overlaps with f1 and has lower priority
    assert len(selected) == 1
    assert selected[0][0].id == "F1"


def test_visible_hazard_selection_preserves_exact_evidence_bbox() -> None:
    finding = _make_finding(
        "F1",
        "cluttered_path",
        3,
        0.9,
        0.72,
        0.12,
        0.12,
        0.10,
        ontology_key="has_floor_clutter",
    )

    assert _select_visual_findings([finding], "toilet") == [(finding, finding.bbox)]
