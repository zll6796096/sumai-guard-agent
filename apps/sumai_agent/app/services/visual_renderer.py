from __future__ import annotations

import base64
import io
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.models import RiskFinding, BoundingBox

RED = (220, 38, 38)
WHITE = (255, 255, 255)
GREEN = (22, 163, 74)
PURPLE = (147, 51, 234)
BLACK = (17, 24, 39)
WATERMARK = "コミュニケーション用イメージ｜施工図ではありません"

DANGER_LABELS = {
    "bathroom_slip": "水濡れ",
    "loose_mat": "敷物",
    "genkan_step": "段差",
    "bathtub_stepover": "段差",
    "hallway_cord": "コード",
    "cluttered_path": "障害物",
}

IMPROVEMENT_LABELS = {
    "genkan_step": "段差対策",
    "hallway_cord": "コード整理",
    "cluttered_path": "片付け",
    "loose_mat": "敷物固定",
    "bathroom_slip": "水分除去",
    "bathtub_stepover": "またぎ対策",
}


@lru_cache(maxsize=1)
def _visible_finding_identities() -> frozenset[tuple[str, str, str]]:
    from app.ontology import OntologyRepository

    ontology = OntologyRepository.load_default()
    return frozenset(
        (room, str(rule["key"]), str(rule["risk_type"]))
        for room in ontology.room_names
        for rule in (ontology.room(room) or {})["visible_hazards"]
    )


def _matches_visible_ontology(
    finding: RiskFinding,
    room_type: str | None,
) -> bool:
    if (
        finding.ontology_rule_kind != "visible_hazard"
        or not finding.ontology_key
    ):
        return False
    identities = _visible_finding_identities()
    if room_type is not None:
        return (
            room_type,
            finding.ontology_key,
            finding.risk_type,
        ) in identities
    return any(
        ontology_key == finding.ontology_key and risk_type == finding.risk_type
        for _, ontology_key, risk_type in identities
    )


def _compute_iou(b1: BoundingBox, b2: BoundingBox) -> float:
    ax1, ay1 = b1.x, b1.y
    ax2, ay2 = b1.x + b1.w, b1.y + b1.h
    bx1, by1 = b2.x, b2.y
    bx2, by2 = b2.x + b2.w, b2.y + b2.h

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area1 = b1.w * b1.h
    area2 = b2.w * b2.h
    union = area1 + area2 - intersection
    return intersection / union if union > 0.0 else 0.0


def _select_visual_findings(
    findings: list[RiskFinding], room_type: str | None, max_items: int = 3
) -> list[tuple[RiskFinding, BoundingBox]]:
    # Only a clear, localized visible hazard has an image location. An expected
    # feature bbox is the region checked for absence, not a missing object or an
    # installation position, so it must never enter visual overlap suppression.
    candidates = [
        (finding, finding.bbox)
        for finding in findings
        if _matches_visible_ontology(finding, room_type)
    ]

    # Sort by severity desc, then confidence desc
    candidates.sort(key=lambda item: (-item[0].severity, -item[0].confidence))

    selected: list[tuple[RiskFinding, BoundingBox]] = []
    for f, bbox in candidates:
        # Check overlaps with already selected
        overlap = False
        for _, sel_bbox in selected:
            if _compute_iou(bbox, sel_bbox) > 0.45:
                overlap = True
                break
        if not overlap:
            selected.append((f, bbox))
        if len(selected) >= max_items:
            break

    return selected


class VisualRenderer:
    def render(
        self, image: Image.Image, findings: list[RiskFinding], room_type: str | None = None
    ) -> tuple[str, str]:
        if not findings:
            return self.render_not_applicable(image)

        selected_findings = _select_visual_findings(findings, room_type, max_items=3)
        if not selected_findings:
            return self.render_not_applicable(image)
        annotated = self._annotated_image(image, selected_findings)
        # Improvement callouts stay on the same visible evidence. The renderer
        # never invents a room-template location for a product or construction.
        improvement = self._improvement_image(image, selected_findings)
        return _to_base64_png(annotated), _to_base64_png(improvement)

    def render_not_applicable(self, image: Image.Image) -> tuple[str, str]:
        """Return the sanitized image without risk or improvement overlays."""
        encoded = _to_base64_png(image.convert("RGB"))
        return encoded, encoded

    def _annotated_image(
        self, image: Image.Image, selected_findings: list[tuple[RiskFinding, BoundingBox]]
    ) -> Image.Image:
        canvas = image.convert("RGB").copy()
        width, height = canvas.size
        line_width = max(5, width // 140)
        label_font = _load_font(max(18, width // 32), bold=True)

        # Draw transparent fills using an RGBA overlay
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        for _, bbox in selected_findings:
            x1 = int(bbox.x * width)
            y1 = int(bbox.y * height)
            x2 = int((bbox.x + bbox.w) * width)
            y2 = int((bbox.y + bbox.h) * height)
            overlay_draw.rectangle((x1, y1, x2, y2), fill=RED + (36,))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

        # Now draw outlines and labels
        draw = ImageDraw.Draw(canvas)
        placed_label_rects = []

        for finding, bbox in selected_findings:
            x1 = int(bbox.x * width)
            y1 = int(bbox.y * height)
            x2 = int((bbox.x + bbox.w) * width)
            y2 = int((bbox.y + bbox.h) * height)
            
            draw.rectangle((x1, y1, x2, y2), outline=RED, width=line_width)

            label = DANGER_LABELS.get(finding.risk_type, "注意")
            text_bbox = draw.textbbox((0, 0), label, font=label_font)
            label_w = text_bbox[2] - text_bbox[0] + 18
            label_h = text_bbox[3] - text_bbox[1] + 14

            # Candidate positions: above, below, inside top-left, right, left
            candidates = [
                (x1, y1 - label_h),
                (x1, y2),
                (x1 + 6, y1 + 6),
                (x2, y1),
                (x1 - label_w, y1)
            ]

            chosen_pos = None
            for cx, cy in candidates:
                # bounds check
                if 0 <= cx <= width - label_w and 0 <= cy <= height - label_h:
                    cand_rect = (cx, cy, cx + label_w, cy + label_h)
                    overlap = False
                    for pr in placed_label_rects:
                        if not (cand_rect[2] < pr[0] or cand_rect[0] > pr[2] or cand_rect[3] < pr[1] or cand_rect[1] > pr[3]):
                            overlap = True
                            break
                    if not overlap:
                        chosen_pos = (cx, cy)
                        break

            if chosen_pos:
                lx, ly = chosen_pos
                placed_label_rects.append((lx, ly, lx + label_w, ly + label_h))
                draw.rectangle((lx, ly, lx + label_w, ly + label_h), fill=RED)
                draw.text((lx + 9, ly + 5), label, fill=WHITE, font=label_font)

        return canvas

    def _improvement_image(
        self, image: Image.Image, selected_findings: list[tuple[RiskFinding, BoundingBox]]
    ) -> Image.Image:
        canvas = image.convert("RGB").copy()
        width, height = canvas.size
        footer_h = max(36, height // 16)
        output = Image.new("RGB", (width, height + footer_h), (248, 250, 252))
        output.paste(canvas, (0, 0))

        overlay = Image.new("RGBA", (width, height + footer_h), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        label_font = _load_font(max(16, width // 42), bold=True)
        small_font = _load_font(max(12, width // 54))

        # Define styles for alternating callouts
        colors = [GREEN, PURPLE]
        placed_label_rects = []

        # Draw overlays
        for index, (finding, bbox) in enumerate(selected_findings):
            color = colors[index % len(colors)]
            x1 = int(bbox.x * width)
            y1 = int(bbox.y * height)
            x2 = int((bbox.x + bbox.w) * width)
            y2 = int((bbox.y + bbox.h) * height)

            overlay_draw.rounded_rectangle(
                (x1, y1, x2, y2), radius=10, fill=color + (36,), outline=color + (230,), width=4
            )

        output = Image.alpha_composite(output.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(output)

        # Draw labels directly adjacent
        for index, (finding, bbox) in enumerate(selected_findings):
            color = colors[index % len(colors)]
            x1 = int(bbox.x * width)
            y1 = int(bbox.y * height)
            x2 = int((bbox.x + bbox.w) * width)
            y2 = int((bbox.y + bbox.h) * height)

            label = _improvement_label(finding.risk_type)
            text_bbox = draw.textbbox((0, 0), label, font=label_font)
            label_w = text_bbox[2] - text_bbox[0] + 20
            label_h = text_bbox[3] - text_bbox[1] + 20

            candidates = [
                (x1, y1 - label_h),
                (x1, y2),
                (x1 + 6, y1 + 6),
                (x2, y1),
                (x1 - label_w, y1)
            ]

            chosen_pos = None
            for cx, cy in candidates:
                if 0 <= cx <= width - label_w and 0 <= cy <= height - label_h:
                    cand_rect = (cx, cy, cx + label_w, cy + label_h)
                    overlap = False
                    for pr in placed_label_rects:
                        if not (cand_rect[2] < pr[0] or cand_rect[0] > pr[2] or cand_rect[3] < pr[1] or cand_rect[1] > pr[3]):
                            overlap = True
                            break
                    if not overlap:
                        chosen_pos = (cx, cy)
                        break

            if chosen_pos:
                lx, ly = chosen_pos
                placed_label_rects.append((lx, ly, lx + label_w, ly + label_h))
                draw.rounded_rectangle(
                    (lx, ly, lx + label_w, ly + label_h),
                    radius=8,
                    fill=(255, 255, 255, 235),
                    outline=color + (230,),
                    width=2,
                )
                _safe_text(draw, (lx + 10, ly + 10), label, fill=BLACK, font=label_font)

        footer_y = height
        draw.rectangle((0, footer_y, width, footer_y + footer_h), fill=(255, 255, 255))
        _safe_text(draw, (16, footer_y + 8), WATERMARK, fill=(71, 85, 105), font=small_font)

        return output


def _improvement_label(risk_type: str) -> str:
    return IMPROVEMENT_LABELS.get(risk_type, "改善案")


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc" if bold else "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _safe_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    fill: tuple[int, int, int] | tuple[int, int, int, int],
    font: ImageFont.ImageFont,
) -> None:
    try:
        draw.text(xy, text, fill=fill, font=font)
    except UnicodeEncodeError:
        fallback = text.encode("ascii", errors="ignore").decode("ascii") or "POC image"
        draw.text(xy, fallback, fill=fill, font=font)


def _to_base64_png(image: Image.Image) -> str:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")
