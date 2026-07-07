from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.models import BoundingBox, RiskFinding, RoomType, VisionResult


VALID_ROOMS: set[str] = {"genkan", "hallway", "bathroom", "toilet", "bedroom", "kitchen", "auto"}


VISION_PROMPT = """You are a Japanese elderly home safety risk assessor.
Analyze one home photo for general elderly fall/slip/trip risks.
Do not ask user profile questions.
Only identify risks visible in the image.
If room_hint is provided, use it as weak context, but correct it if the image clearly shows another room.
Detect risks such as:
- 玄関段差
- 廊下の電源コード
- 床の物・動線阻害
- マット・敷物のつまずき
- 浴室床の滑り
- 浴槽またぎ
- トイレ立ち座り
- 手すり不足
- 照明不足
- キッチン床の滑り
Output strict JSON only using this shape:
{
  "room_type": "genkan|hallway|bathroom|toilet|bedroom|kitchen|auto",
  "findings": [
    {
      "risk_type": "string",
      "label_ja": "string",
      "description_ja": "string",
      "severity": 1,
      "confidence": 0.0,
      "bbox": {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0},
      "evidence_ja": "string",
      "needs_human_confirmation": false
    }
  ]
}
Each finding must include normalized bbox x,y,w,h from 0 to 1.
Do not say "違反". Say "リスクがあります", "該当する可能性があります", or "専門確認が必要です".
Do not claim exact measurements.
Do not invent objects not visible in the photo.
Do not produce final renovation, medical, insurance, or construction judgment.
"""


class GeminiVisionService:
    async def analyze(
        self,
        image_png: bytes,
        room_hint: str = "auto",
        force_mock: bool = False,
    ) -> VisionResult:
        normalized_room = normalize_room_hint(room_hint)
        if force_mock or settings.mock_mode or not settings.gemini_api_key:
            return mock_vision_result(normalized_room)

        return await self._analyze_with_gemini(image_png=image_png, room_hint=normalized_room)

    async def _analyze_with_gemini(self, image_png: bytes, room_hint: RoomType) -> VisionResult:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = f"{VISION_PROMPT}\nroom_hint: {room_hint}\nReturn JSON only."
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                prompt,
                types.Part.from_bytes(data=image_png, mime_type="image/png"),
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return parse_vision_json(response.text or "{}", fallback_room=room_hint)


def normalize_room_hint(room_hint: str | None) -> RoomType:
    if not room_hint:
        return "auto"
    value = room_hint.strip().lower()
    if value in VALID_ROOMS:
        return value  # type: ignore[return-value]
    return "auto"


def mock_vision_result(room_hint: RoomType) -> VisionResult:
    fixtures: dict[str, list[dict[str, Any]]] = {
        "genkan": [
            {
                "risk_type": "genkan_step",
                "label_ja": "玄関上がり框・段差",
                "description_ja": "玄関の上がり框に段差があり、足を上げる動作でつまずくリスクがあります。",
                "severity": 4,
                "confidence": 0.88,
                "bbox": {"x": 0.12, "y": 0.55, "w": 0.68, "h": 0.22},
                "evidence_ja": "床面の高さが切り替わる境目が見えます。",
            },
            {
                "risk_type": "loose_mat",
                "label_ja": "玄関マットのつまずき",
                "description_ja": "マット端部に足が引っかかる可能性があります。",
                "severity": 3,
                "confidence": 0.72,
                "bbox": {"x": 0.22, "y": 0.72, "w": 0.34, "h": 0.16},
                "evidence_ja": "通路上に敷物状の領域が見えます。",
            },
        ],
        "hallway": [
            {
                "risk_type": "hallway_cord",
                "label_ja": "廊下の電源コード",
                "description_ja": "動線を横切るコードがあり、足を引っかけるリスクがあります。",
                "severity": 3,
                "confidence": 0.82,
                "bbox": {"x": 0.16, "y": 0.62, "w": 0.58, "h": 0.1},
                "evidence_ja": "床面の通路部分に細い線状の物が見えます。",
            },
            {
                "risk_type": "poor_lighting",
                "label_ja": "照明不足の可能性",
                "description_ja": "足元が暗く、段差や物に気づきにくい可能性があります。",
                "severity": 2,
                "confidence": 0.51,
                "bbox": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.45},
                "evidence_ja": "写真全体の足元付近が暗く見えます。",
            },
        ],
        "bathroom": [
            {
                "risk_type": "bathroom_slip",
                "label_ja": "浴室床の滑り",
                "description_ja": "濡れやすい床面で滑るリスクがあります。",
                "severity": 4,
                "confidence": 0.86,
                "bbox": {"x": 0.08, "y": 0.55, "w": 0.72, "h": 0.32},
                "evidence_ja": "浴室の床面と思われる領域が広く見えます。",
            },
            {
                "risk_type": "bathtub_stepover",
                "label_ja": "浴槽またぎ",
                "description_ja": "浴槽をまたぐ動作でバランスを崩す可能性があります。",
                "severity": 4,
                "confidence": 0.79,
                "bbox": {"x": 0.5, "y": 0.28, "w": 0.34, "h": 0.44},
                "evidence_ja": "浴槽の縁と思われる高低差が見えます。",
            },
        ],
        "toilet": [
            {
                "risk_type": "toilet_transfer",
                "label_ja": "トイレ立ち座り",
                "description_ja": "便器周辺で立ち座り時に支えが不足する可能性があります。",
                "severity": 4,
                "confidence": 0.8,
                "bbox": {"x": 0.32, "y": 0.32, "w": 0.38, "h": 0.5},
                "evidence_ja": "便器周辺の立ち座りスペースが見えます。",
            }
        ],
        "bedroom": [
            {
                "risk_type": "cluttered_path",
                "label_ja": "ベッド横の動線上の物",
                "description_ja": "夜間の移動経路に物があり、つまずくリスクがあります。",
                "severity": 3,
                "confidence": 0.76,
                "bbox": {"x": 0.18, "y": 0.58, "w": 0.5, "h": 0.25},
                "evidence_ja": "床の通路部分に複数の物が見えます。",
            },
            {
                "risk_type": "poor_lighting",
                "label_ja": "夜間照明不足の可能性",
                "description_ja": "夜間トイレまでの足元確認がしづらい可能性があります。",
                "severity": 2,
                "confidence": 0.5,
                "bbox": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.45},
                "evidence_ja": "足元を照らす照明が写真内で確認しにくいです。",
            },
        ],
        "kitchen": [
            {
                "risk_type": "kitchen_slip",
                "label_ja": "キッチン床の滑り",
                "description_ja": "水や油が落ちやすい床で滑るリスクがあります。",
                "severity": 3,
                "confidence": 0.74,
                "bbox": {"x": 0.16, "y": 0.58, "w": 0.58, "h": 0.28},
                "evidence_ja": "調理動線の床面が見えます。",
            }
        ],
        "auto": [
            {
                "risk_type": "cluttered_path",
                "label_ja": "動線上の物",
                "description_ja": "通路上の物により、つまずきやすくなる可能性があります。",
                "severity": 3,
                "confidence": 0.7,
                "bbox": {"x": 0.22, "y": 0.58, "w": 0.48, "h": 0.24},
                "evidence_ja": "床の移動経路上に物があるように見えます。",
            }
        ],
    }
    raw_findings = fixtures.get(room_hint, fixtures["auto"])
    findings = [_finding_from_raw(index, item) for index, item in enumerate(raw_findings, start=1)]
    return VisionResult(room_type=room_hint, findings=findings)


def parse_vision_json(raw_json: str, fallback_room: RoomType) -> VisionResult:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return mock_vision_result(fallback_room)

    room = normalize_room_hint(str(data.get("room_type") or fallback_room))
    findings: list[RiskFinding] = []
    for index, item in enumerate(data.get("findings") or [], start=1):
        if not isinstance(item, dict):
            continue
        try:
            findings.append(_finding_from_raw(index, item))
        except Exception:
            continue
    return VisionResult(room_type=room, findings=findings)


def _finding_from_raw(index: int, item: dict[str, Any]) -> RiskFinding:
    bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
    return RiskFinding(
        id=f"R{index}",
        risk_type=str(item.get("risk_type") or "visible_risk"),
        label_ja=str(item.get("label_ja") or "見えるリスク"),
        description_ja=str(item.get("description_ja") or "写真内に安全上の注意点が見えます。"),
        severity=_clamp_int(item.get("severity"), 1, 5, default=3),
        confidence=_clamp_float(item.get("confidence"), 0.0, 1.0, default=0.6),
        bbox=BoundingBox(
            x=_clamp_float(bbox.get("x"), 0.0, 1.0, default=0.1),
            y=_clamp_float(bbox.get("y"), 0.0, 1.0, default=0.1),
            w=_clamp_float(bbox.get("w"), 0.0, 1.0, default=0.4),
            h=_clamp_float(bbox.get("h"), 0.0, 1.0, default=0.3),
        ),
        evidence_ja=str(item.get("evidence_ja") or "写真内で確認できる範囲の所見です。"),
        basis_label_ja="",
        basis_summary_ja="",
        needs_human_confirmation=bool(item.get("needs_human_confirmation", False)),
    )


def _clamp_float(value: Any, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))
