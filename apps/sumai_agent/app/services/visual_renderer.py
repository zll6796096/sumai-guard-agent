from __future__ import annotations

import base64
import io
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.models import RiskFinding, BoundingBox

RED = (220, 38, 38)
WHITE = (255, 255, 255)
GREEN = (22, 163, 74)
PURPLE = (147, 51, 234)
BLUE = (14, 116, 144)
YELLOW = (245, 158, 11)
BLACK = (17, 24, 39)
WATERMARK = "コミュニケーション用イメージ｜施工図ではありません"

# Visual zone coordinates: (x, y, w, h) relative
VISUAL_ZONES = {
    "toilet": {
        "toilet_missing_handrail": {"left": (0.08, 0.42, 0.17, 0.36), "right": (0.70, 0.42, 0.22, 0.36)},
        "toilet_transfer_support": {"left": (0.08, 0.42, 0.17, 0.36), "right": (0.70, 0.42, 0.22, 0.36)},
        "toilet_missing_emergency_call": (0.68, 0.30, 0.25, 0.28),
        "toilet_slip": (0.18, 0.68, 0.64, 0.24),
        "looks_slippery_floor": (0.18, 0.68, 0.64, 0.24),
        "cluttered_path": (0.25, 0.70, 0.50, 0.22),
    },
    "bathroom": {
        "bathroom_missing_handrail": {"left": (0.10, 0.30, 0.18, 0.50), "right": (0.72, 0.30, 0.18, 0.50)},
        "bathroom_missing_non_slip": (0.20, 0.70, 0.60, 0.25),
        "bathroom_slip": (0.20, 0.70, 0.60, 0.25),
        "bathroom_missing_emergency_call": (0.70, 0.35, 0.20, 0.30),
        "bathtub_stepover": (0.30, 0.50, 0.40, 0.25),
    },
    "hallway": {
        "hallway_cord": (0.10, 0.75, 0.80, 0.15),
        "cluttered_path": (0.25, 0.70, 0.50, 0.25),
        "poor_lighting": (0.30, 0.10, 0.40, 0.20),
    },
    "genkan": {
        "genkan_step": (0.15, 0.60, 0.70, 0.20),
        "large_step": (0.15, 0.60, 0.70, 0.20),
        "genkan_missing_support": (0.08, 0.30, 0.15, 0.50),
        "loose_shoes": (0.20, 0.65, 0.60, 0.25),
        "cluttered_path": (0.20, 0.65, 0.60, 0.25),
    },
    "bedroom": {
        "clear_path_from_bed": (0.20, 0.70, 0.60, 0.22),
        "cluttered_path": (0.20, 0.70, 0.60, 0.22),
        "loose_mat": (0.25, 0.72, 0.50, 0.20),
        "poor_lighting": (0.70, 0.20, 0.20, 0.30),
    },
    "kitchen": {
        "kitchen_slip": (0.20, 0.75, 0.60, 0.20),
        "cluttered_path": (0.25, 0.70, 0.50, 0.25),
        "reachable_storage_issue": (0.15, 0.15, 0.70, 0.25),
    }
}

ROOM_ANCHORS = {
    "toilet": (0.25, 0.65, 0.50, 0.25),
    "bathroom": (0.30, 0.60, 0.40, 0.30),
    "hallway": (0.25, 0.70, 0.50, 0.25),
    "genkan": (0.20, 0.60, 0.60, 0.30),
    "bedroom": (0.25, 0.65, 0.50, 0.25),
    "kitchen": (0.25, 0.70, 0.50, 0.25),
}

DANGER_LABELS = {
    "toilet_missing_handrail": "支え不足",
    "toilet_transfer_support": "支え不足",
    "bathroom_missing_handrail": "支え不足",
    "genkan_missing_support": "支え不足",
    "bedroom_missing_support": "支え不足",
    "stairs": "支え不足",
    "missing_handrail": "支え不足",
    
    "toilet_missing_emergency_call": "連絡手段",
    "bathroom_missing_emergency_call": "連絡手段",
    
    "toilet_slip": "滑り",
    "bathroom_slip": "滑り",
    "bathroom_missing_non_slip": "滑り",
    "kitchen_slip": "滑り",
    "looks_slippery_floor": "滑り",
    "loose_mat": "滑り",
    
    "genkan_step": "段差",
    "large_step": "段差",
    "genkan_invisible_step": "段差",
    "bathtub_stepover": "段差",
    
    "hallway_cord": "コード",
}


def _get_mapped_bbox(finding: RiskFinding, room_type: str | None) -> BoundingBox:
    # Rendering may map or expand a local presentation box, never the evidence box.
    display_bbox = finding.display_bbox or finding.bbox
    if room_type and room_type in VISUAL_ZONES:
        mapped = VISUAL_ZONES[room_type].get(finding.risk_type)
        if mapped:
            if isinstance(mapped, dict):
                center_x = display_bbox.x + display_bbox.w / 2
                zone_coords = mapped["right"] if center_x > 0.5 else mapped["left"]
            else:
                zone_coords = mapped
            x, y, w, h = zone_coords
            return BoundingBox(x=x, y=y, w=w, h=h)

    # Check if original is huge (>65%)
    orig_area = display_bbox.w * display_bbox.h
    if orig_area > 0.65:
        anchor = None
        if room_type and room_type in ROOM_ANCHORS:
            anchor = ROOM_ANCHORS[room_type]
        if not anchor:
            anchor = (0.25, 0.65, 0.50, 0.25)
        x, y, w, h = anchor
        return BoundingBox(x=x, y=y, w=w, h=h)

    return display_bbox


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
    # Danger annotations are evidence, so selection and overlap suppression use
    # provider evidence coordinates. Presentation mapping is improvement-only.
    candidates = [(finding, finding.bbox) for finding in findings]

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
        selected_findings = _select_visual_findings(findings, room_type, max_items=3)
        annotated = self._annotated_image(image, selected_findings)
        improvement_findings = [
            (finding, _get_mapped_bbox(finding, room_type))
            for finding, _ in selected_findings
        ]
        improvement = self._improvement_image(image, improvement_findings)
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

        if not selected_findings:
            # Fallback if no findings selected (draw clean default overlay)
            draw.rounded_rectangle(
                (36, int(height * 0.58), width - 36, int(height * 0.82)),
                radius=14,
                fill=GREEN + (42,),
                outline=GREEN + (220,),
                width=4,
            )
            _safe_text(draw, (56, int(height * 0.64)), "動線確保", fill=BLACK, font=label_font)

        footer_y = height
        draw.rectangle((0, footer_y, width, footer_y + footer_h), fill=(255, 255, 255))
        _safe_text(draw, (16, footer_y + 8), WATERMARK, fill=(71, 85, 105), font=small_font)

        return output


def _bbox_pixels(finding: RiskFinding, width: int, height: int) -> tuple[int, int, int, int]:
    display_bbox = finding.display_bbox or finding.bbox
    x1 = int(display_bbox.x * width)
    y1 = int(display_bbox.y * height)
    x2 = int((display_bbox.x + display_bbox.w) * width)
    y2 = int((display_bbox.y + display_bbox.h) * height)
    return (
        max(0, min(width - 1, x1)),
        max(0, min(height - 1, y1)),
        max(1, min(width, x2)),
        max(1, min(height, y2)),
    )


def _improvement_label(risk_type: str) -> str:
    labels = {
        "genkan_step": "段差対策",
        "large_step": "段差対策",
        "stairs": "手すり候補",
        "hallway_cord": "コード整理",
        "cluttered_path": "片付け",
        "loose_mat": "マット固定",
        "bathroom_slip": "滑り止め",
        "bathtub_stepover": "またぎ対策",
        "toilet_transfer": "手すり候補",
        "missing_handrail": "手すり候補",
        "poor_lighting": "照明追加",
        "kitchen_slip": "滑り止め",
        # New checklist types
        "toilet_missing_handrail": "手すり候補",
        "toilet_missing_emergency_call": "緊急呼出相談",
        "toilet_transfer_support": "手すり候補",
        "toilet_slip": "滑り止め",
        "bathroom_missing_handrail": "手すり候補",
        "bathroom_missing_non_slip": "滑り止め",
        "bathroom_missing_transfer_support": "手すり候補",
        "bathroom_missing_emergency_call": "緊急呼出相談",
        "bathroom_no_shower_chair": "動線確保",
        "genkan_missing_support": "手すり候補",
        "genkan_invisible_step": "段差対策",
        "hallway_narrow_path": "動線確保",
        "bedroom_blocked_path": "動線確保",
        "bedroom_missing_support": "手すり候補",
        "kitchen_cluttered_floor": "片付け",
        "kitchen_narrow_path": "動線確保",
        "kitchen_unreachable_storage": "収納見直し",
    }
    return labels.get(risk_type, "改善案")


def _improvement_color(risk_type: str) -> tuple[int, int, int]:
    if risk_type in {
        "bathroom_slip", "kitchen_slip", "toilet_slip",
        "bathroom_missing_non_slip", "loose_mat"
    }:
        return BLUE
    if risk_type in {"poor_lighting", "toilet_missing_emergency_call", "bathroom_missing_emergency_call"}:
        return YELLOW
    return GREEN


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    fill: tuple[int, int, int, int],
    width: int,
) -> None:
    draw.line((start, end), fill=fill, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = max(10, width * 3)
    left = (
        int(end[0] - length * math.cos(angle - math.pi / 6)),
        int(end[1] - length * math.sin(angle - math.pi / 6)),
    )
    right = (
        int(end[0] - length * math.cos(angle + math.pi / 6)),
        int(end[1] - length * math.sin(angle + math.pi / 6)),
    )
    draw.polygon((end, left, right), fill=fill)


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
