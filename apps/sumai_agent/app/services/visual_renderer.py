from __future__ import annotations

import base64
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.models import RiskFinding


RED = (220, 38, 38)
WHITE = (255, 255, 255)
GREEN = (22, 163, 74)
BLUE = (14, 116, 144)
YELLOW = (245, 158, 11)
BLACK = (17, 24, 39)
WATERMARK = "コミュニケーション用イメージ｜施工図ではありません"


class VisualRenderer:
    def render(self, image: Image.Image, findings: list[RiskFinding]) -> tuple[str, str]:
        annotated = self._annotated_image(image, findings)
        improvement = self._improvement_image(image, findings, annotated)
        return _to_base64_png(annotated), _to_base64_png(improvement)

    def _annotated_image(self, image: Image.Image, findings: list[RiskFinding]) -> Image.Image:
        canvas = image.convert("RGB").copy()
        draw = ImageDraw.Draw(canvas)
        width, height = canvas.size
        line_width = max(5, width // 140)
        label_font = _load_font(max(18, width // 32), bold=True)

        for finding in findings:
            x1, y1, x2, y2 = _bbox_pixels(finding, width, height)
            draw.rectangle((x1, y1, x2, y2), outline=RED, width=line_width)
            label = "注意"
            text_bbox = draw.textbbox((0, 0), label, font=label_font)
            label_w = text_bbox[2] - text_bbox[0] + 18
            label_h = text_bbox[3] - text_bbox[1] + 14
            label_x = max(0, x1)
            label_y = max(0, y1 - label_h)
            draw.rectangle((label_x, label_y, label_x + label_w, label_y + label_h), fill=RED)
            draw.text((label_x + 9, label_y + 5), label, fill=WHITE, font=label_font)

        return canvas

    def _improvement_image(
        self,
        image: Image.Image,
        findings: list[RiskFinding],
        annotated: Image.Image,
    ) -> Image.Image:
        canvas = image.convert("RGB").copy()
        width, height = canvas.size
        footer_h = max(36, height // 16)
        output = Image.new("RGB", (width, height + footer_h), (248, 250, 252))
        output.paste(canvas, (0, 0))

        draw = ImageDraw.Draw(output, "RGBA")
        label_font = _load_font(max(16, width // 42), bold=True)
        small_font = _load_font(max(12, width // 54))

        self._draw_improvement_overlays(draw, findings, width, height, 0, label_font)

        footer_y = height
        draw.rectangle((0, footer_y, width, footer_y + footer_h), fill=(255, 255, 255, 235))
        _safe_text(draw, (16, footer_y + 8), WATERMARK, fill=(71, 85, 105), font=small_font)
        return output

    def _draw_improvement_overlays(
        self,
        draw: ImageDraw.ImageDraw,
        findings: list[RiskFinding],
        width: int,
        height: int,
        header_h: int,
        font: ImageFont.ImageFont,
    ) -> None:
        right_offset = 0
        for index, finding in enumerate(findings):
            x1, y1, x2, y2 = _bbox_pixels(finding, width, height)
            x1 += right_offset
            x2 += right_offset
            y1 += header_h
            y2 += header_h

            label = _improvement_label(finding.risk_type)
            color = _improvement_color(finding.risk_type)
            draw.rounded_rectangle((x1, y1, x2, y2), radius=10, fill=color + (54,), outline=color + (230,), width=4)

            label_x = min(right_offset + width - 180, max(right_offset + 18, x2 + 18))
            label_y = min(header_h + height - 62, max(header_h + 16, y1 + index * 6))
            _draw_arrow(draw, (x2, (y1 + y2) // 2), (label_x, label_y + 18), color + (230,), width=4)
            draw.rounded_rectangle((label_x, label_y, label_x + 158, label_y + 42), radius=8, fill=(255, 255, 255, 235), outline=color + (230,), width=2)
            _safe_text(draw, (label_x + 10, label_y + 10), label, fill=BLACK, font=font)

        if not findings:
            draw.rounded_rectangle(
                (right_offset + 36, header_h + height * 0.58, right_offset + width - 36, header_h + height * 0.82),
                radius=14,
                fill=GREEN + (42,),
                outline=GREEN + (220,),
                width=4,
            )
            _safe_text(draw, (right_offset + 56, header_h + int(height * 0.64)), "動線確保", fill=BLACK, font=font)



def _bbox_pixels(finding: RiskFinding, width: int, height: int) -> tuple[int, int, int, int]:
    x1 = int(finding.bbox.x * width)
    y1 = int(finding.bbox.y * height)
    x2 = int((finding.bbox.x + finding.bbox.w) * width)
    y2 = int((finding.bbox.y + finding.bbox.h) * height)
    return (
        max(0, min(width - 1, x1)),
        max(0, min(height - 1, y1)),
        max(1, min(width, x2)),
        max(1, min(height, y2)),
    )


def _improvement_label(risk_type: str) -> str:
    labels = {
        "genkan_step": "手すり候補",
        "large_step": "段差対策",
        "stairs": "手すり候補",
        "hallway_cord": "コード整理",
        "cluttered_path": "片付け",
        "loose_mat": "マット固定",
        "bathroom_slip": "滑り止め",
        "bathtub_stepover": "手すり候補",
        "toilet_transfer": "手すり候補",
        "missing_handrail": "手すり候補",
        "poor_lighting": "照明追加",
        "kitchen_slip": "滑り止め",
    }
    return labels.get(risk_type, "改善案")


def _improvement_color(risk_type: str) -> tuple[int, int, int]:
    if risk_type in {"bathroom_slip", "kitchen_slip"}:
        return BLUE
    if risk_type in {"poor_lighting"}:
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
