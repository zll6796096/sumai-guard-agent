from __future__ import annotations

import base64
import io
from PIL import Image

from app.models import BoundingBox, RiskFinding
from app.services.visual_renderer import (
    VisualRenderer,
    _select_visual_findings,
    _get_mapped_bbox,
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
    h: float
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
    for risk_type in ["genkan_step", "toilet_missing_handrail", "kitchen_slip"]:
        imp_lbl = _improvement_label(risk_type)
        assert not any(f"R{i}" in imp_lbl for i in range(1, 10))


def test_huge_bbox_normalization() -> None:
    # 5. Huge bbox covering >65% image is normalized into a smaller visual zone.
    # Area = 0.8 * 0.9 = 0.72 (> 0.65)
    finding = _make_finding("F1", "toilet_slip", 4, 0.8, 0.1, 0.05, 0.8, 0.9)
    mapped = _get_mapped_bbox(finding, "toilet")
    # Verify the mapped bbox area is much smaller
    mapped_area = mapped.w * mapped.h
    assert mapped_area <= 0.65


def test_overlapping_deduplication() -> None:
    # 6. Overlapping bboxes are deduplicated.
    # Two identical bboxes
    f1 = _make_finding("F1", "genkan_step", 5, 0.9, 0.1, 0.1, 0.2, 0.2)
    f2 = _make_finding("F2", "genkan_step", 4, 0.8, 0.1, 0.1, 0.2, 0.2)
    selected = _select_visual_findings([f1, f2], "genkan", max_items=3)
    # Only f1 should be selected because f2 overlaps with f1 and has lower priority
    assert len(selected) == 1
    assert selected[0][0].id == "F1"


def test_toilet_missing_handrail_mapped() -> None:
    # 7. toilet_missing_handrail creates a handrail candidate zone, not full-photo box.
    finding = _make_finding("F1", "toilet_missing_handrail", 5, 0.9, 0.0, 0.0, 1.0, 1.0)
    mapped = _get_mapped_bbox(finding, "toilet")
    # Area must not cover the full photo
    assert mapped.w * mapped.h < 0.5
    # Should map to one of the toilet side wall zones
    assert mapped.x in [0.08, 0.70]
    assert mapped.y == 0.42


def test_toilet_missing_emergency_call_mapped() -> None:
    # 8. toilet_missing_emergency_call creates 緊急呼出相談 label if selected.
    finding = _make_finding("F1", "toilet_missing_emergency_call", 5, 0.9, 0.0, 0.0, 1.0, 1.0)
    
    # Check improvement label matches
    label = _improvement_label(finding.risk_type)
    assert label == "緊急呼出相談"
