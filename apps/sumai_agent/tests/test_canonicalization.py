from __future__ import annotations

from PIL import Image

from app.models import ActionPlan, BoundingBox, RiskFinding
from app.services.canonicalization import (
    canonical_pixel_digest,
    canonicalize_findings,
    result_key,
    semantic_hash,
)
from app.services.orchestrator import analysis_semantic_payload


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


def test_canonical_pixel_digest_is_stable_for_equal_pixels() -> None:
    image = Image.new("RGB", (3, 2), (10, 20, 30))

    assert canonical_pixel_digest(image) == canonical_pixel_digest(image.copy())


def test_result_key_changes_for_each_identity_input() -> None:
    base = dict(
        pixel_digest="pixel",
        room_hint="genkan",
        preprocess_version="1.0.0",
        ontology_version="1.0.0",
        model="gemini-test",
        inference_config_version="1.0.0",
        execution_mode="forced_mock",
    )
    baseline = result_key(**base)

    for field, replacement in {
        "room_hint": "bathroom",
        "preprocess_version": "2.0.0",
        "ontology_version": "2.0.0",
        "model": "gemini-other",
        "inference_config_version": "2.0.0",
        "execution_mode": "configured_mock",
    }.items():
        changed = {**base, field: replacement}
        assert result_key(**changed) != baseline


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
    assert forward[0].bbox == BoundingBox(x=0.101, y=0.201, w=0.3, h=0.401)
    assert lower.model_dump(mode="json") == original_lower
    assert higher.model_dump(mode="json") == original_higher


def test_canonicalize_findings_keeps_rounded_evidence_bbox_in_frame() -> None:
    finding = _finding(
        risk_type="edge",
        severity=3,
        confidence=0.8,
        bbox=BoundingBox(x=0.9995, y=0.9995, w=0.0005, h=0.0005),
    )

    rounded = canonicalize_findings([finding])[0].bbox

    assert rounded.x + rounded.w <= 1.0
    assert rounded.y + rounded.h <= 1.0


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
