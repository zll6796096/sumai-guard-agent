from __future__ import annotations

import base64
import io

from PIL import Image

from app.models import BoundingBox, RiskFinding
from app.services.visual_renderer import VisualRenderer, _select_visual_findings


def test_visual_renderer_returns_valid_base64_png() -> None:
    image = Image.new("RGB", (640, 480), "white")
    finding = RiskFinding(
        id="R1",
        risk_type="genkan_step",
        label_ja="玄関段差",
        description_ja="段差が見えます。",
        severity=4,
        confidence=0.9,
        bbox=BoundingBox(x=0.2, y=0.3, w=0.4, h=0.25),
        evidence_ja="上がり框の段差が見えます。",
        basis_label_ja="高齢者住宅安全チェックの一般原則",
        basis_summary_ja="段差はつまずきの要因になります。",
        needs_human_confirmation=False,
    )

    annotated, improvement = VisualRenderer().render(image, [finding])

    for encoded in [annotated, improvement]:
        raw = base64.b64decode(encoded)
        assert raw.startswith(b"\x89PNG\r\n\x1a\n")
        decoded = Image.open(io.BytesIO(raw))
        assert decoded.format == "PNG"
        assert decoded.width > 0
        assert decoded.height > 0


def test_not_applicable_renderer_returns_unannotated_identical_images() -> None:
    image = Image.new("RGB", (64, 48), "white")

    annotated, improvement = VisualRenderer().render_not_applicable(image)

    assert annotated == improvement


def test_applicable_empty_findings_returns_unannotated_identical_images() -> None:
    image = Image.new("RGB", (64, 48), (236, 232, 224))

    annotated, improvement = VisualRenderer().render(image, [], "toilet")

    assert annotated == improvement
    decoded = Image.open(io.BytesIO(base64.b64decode(improvement))).convert("RGB")
    assert decoded.size == image.size
    assert decoded.getpixel((32, 24)) == (236, 232, 224)


def test_danger_selection_uses_evidence_bbox_without_mutating_evidence_bbox() -> None:
    image = Image.new("RGB", (640, 480), "white")
    evidence_bbox = BoundingBox(x=0.05, y=0.05, w=0.10, h=0.10)
    display_bbox = BoundingBox(x=0.60, y=0.60, w=0.20, h=0.20)
    finding = RiskFinding(
        id="R1",
        risk_type="unmapped_risk",
        label_ja="表示用テスト",
        description_ja="表示用テストです。",
        severity=4,
        confidence=0.9,
        bbox=evidence_bbox,
        display_bbox=display_bbox,
        evidence_ja="写真内の根拠です。",
        basis_label_ja="根拠",
        basis_summary_ja="根拠の要約です。",
        needs_human_confirmation=False,
    )

    selected = _select_visual_findings([finding], None)
    VisualRenderer().render(image, [finding])

    assert selected[0][1] == evidence_bbox
    assert finding.bbox == evidence_bbox


def test_annotated_red_box_is_drawn_at_provider_evidence_coordinates() -> None:
    image = Image.new("RGB", (100, 100), "white")
    finding = RiskFinding(
        id="R1",
        risk_type="cluttered_path",
        label_ja="表示用テスト",
        description_ja="表示用テストです。",
        severity=4,
        confidence=0.9,
        bbox=BoundingBox(x=0.8, y=0.1, w=0.1, h=0.1),
        evidence_ja="写真内の根拠です。",
        basis_label_ja="根拠",
        basis_summary_ja="根拠の要約です。",
        needs_human_confirmation=False,
    )

    annotated, _ = VisualRenderer().render(image, [finding], "genkan")
    decoded = Image.open(io.BytesIO(base64.b64decode(annotated))).convert("RGB")

    assert decoded.getpixel((80, 10)) != (255, 255, 255)
    assert decoded.getpixel((20, 65)) == (255, 255, 255)
