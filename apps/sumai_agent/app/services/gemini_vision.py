from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app.config import settings
from app.errors import GeminiUnavailableError
from app.models import BoundingBox, RiskFinding, RoomType, VisionResult


logger = logging.getLogger("sumai.gemini_vision")

VALID_ROOMS: set[str] = {"genkan", "hallway", "bathroom", "toilet", "bedroom", "kitchen", "auto"}


VISION_PROMPT = """You are a Japanese elderly home safety risk assessor.
Analyze one photo for general elderly fall/slip/trip risks visible in the image.
Do not ask user profile questions.

Safety Boundary Guidelines:
1. If the photo is NOT a home/residential interior (e.g. offices, gyms, public spaces, streets, landscapes, cars, documents, food, people-only closeups, or other unrelated scenes), set is_home_environment to false and return no findings.
2. If no visible elderly fall/slip/trip risk is present in a home environment, return no findings (findings=[]).
3. Do not invent risk just because the user asks for analysis.
4. Do not mark normal furniture as a risk unless it visibly blocks walking, transfer, standing, bathing, toilet use, or floor movement.
5. Correct the room_type if the image clearly shows another room than room_hint.

Output strict JSON only using this shape:
{
  "is_home_environment": true/false,
  "not_applicable_reason_ja": "string or null",
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
        analysis_id: str = "",
    ) -> tuple[VisionResult, str]:
        """Analyze image. Returns (VisionResult, mode) where mode is 'mock' or 'gemini'."""
        normalized_room = normalize_room_hint(room_hint)

        if settings.require_real_gemini:
            if not settings.gemini_api_key:
                logger.error("strict_mode_gemini_key_missing", extra={"analysis_id": analysis_id})
                raise GeminiUnavailableError("Real Gemini analysis is required but GEMINI_API_KEY is not set.")
            return await self._analyze_with_gemini_strict(
                image_png=image_png,
                room_hint=normalized_room,
                analysis_id=analysis_id,
            )

        if force_mock or settings.mock_mode or not settings.gemini_api_key:
            mode = "mock"
            reason = ""
            if not force_mock and not settings.mock_mode and not settings.gemini_api_key:
                reason = "GEMINI_API_KEY not set"
            logger.info(
                "vision_start",
                extra={
                    "analysis_id": analysis_id,
                    "mode": mode,
                    "model": settings.gemini_model,
                    "room_hint": normalized_room,
                    "reason": reason,
                },
            )
            return mock_vision_result(normalized_room), mode

        return await self._analyze_with_gemini(
            image_png=image_png,
            room_hint=normalized_room,
            analysis_id=analysis_id,
        )

    async def _analyze_with_gemini_strict(
        self,
        image_png: bytes,
        room_hint: RoomType,
        analysis_id: str,
    ) -> tuple[VisionResult, str]:
        logger.info(
            "vision_start_strict",
            extra={
                "analysis_id": analysis_id,
                "mode": "gemini",
                "model": settings.gemini_model,
                "room_hint": room_hint,
            },
        )
        start_time = time.monotonic()
        try:
            async with asyncio.timeout(settings.analysis_timeout):
                result = await self._call_gemini(image_png, room_hint)

            latency_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "vision_complete_strict",
                extra={
                    "analysis_id": analysis_id,
                    "mode": "gemini",
                    "model": settings.gemini_model,
                    "finding_count": len(result.findings),
                    "latency_ms": latency_ms,
                },
            )
            return result, "gemini"
        except Exception as exc:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "vision_failed_strict",
                extra={
                    "analysis_id": analysis_id,
                    "error": str(exc),
                    "latency_ms": latency_ms,
                },
            )
            raise GeminiUnavailableError(f"Real Gemini analysis failed: {str(exc)}")

    async def _analyze_with_gemini(
        self,
        image_png: bytes,
        room_hint: RoomType,
        analysis_id: str,
    ) -> tuple[VisionResult, str]:
        logger.info(
            "vision_start",
            extra={
                "analysis_id": analysis_id,
                "mode": "gemini",
                "model": settings.gemini_model,
                "room_hint": room_hint,
            },
        )

        start_time = time.monotonic()
        fallback_reason = ""

        try:
            async with asyncio.timeout(settings.analysis_timeout):
                result = await self._call_gemini(image_png, room_hint)

            latency_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "vision_complete",
                extra={
                    "analysis_id": analysis_id,
                    "mode": "gemini",
                    "model": settings.gemini_model,
                    "finding_count": len(result.findings),
                    "latency_ms": latency_ms,
                },
            )
            return result, "gemini"

        except TimeoutError:
            fallback_reason = "gemini_timeout"
        except Exception as exc:
            fallback_reason = f"gemini_error: {type(exc).__name__}: {str(exc)[:200]}"

        latency_ms = int((time.monotonic() - start_time) * 1000)
        logger.warning(
            "vision_fallback_to_mock",
            extra={
                "analysis_id": analysis_id,
                "mode": "gemini_fallback",
                "fallback_reason": fallback_reason,
                "latency_ms": latency_ms,
            },
        )
        return mock_vision_result(room_hint), f"gemini_fallback({fallback_reason})"

    async def _call_gemini(self, image_png: bytes, room_hint: RoomType) -> VisionResult:
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
    return VisionResult(room_type=room_hint, findings=findings, is_home_environment=True, not_applicable_reason_ja=None)


def parse_vision_json(raw_json: str, fallback_room: RoomType) -> VisionResult:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        logger.warning("gemini_json_decode_error", extra={"raw_length": len(raw_json)})
        return mock_vision_result(fallback_room)

    if not isinstance(data, dict):
        logger.warning("gemini_unexpected_json_type", extra={"type": type(data).__name__})
        return mock_vision_result(fallback_room)

    is_home = bool(data.get("is_home_environment", True))
    not_applicable_reason = data.get("not_applicable_reason_ja")
    if not_applicable_reason:
        not_applicable_reason = str(not_applicable_reason)

    if not is_home:
        return VisionResult(
            room_type="auto",
            findings=[],
            is_home_environment=False,
            not_applicable_reason_ja=not_applicable_reason or "住宅内の安全確認対象ではない可能性があります。"
        )

    room = normalize_room_hint(str(data.get("room_type") or fallback_room))
    findings: list[RiskFinding] = []
    for index, item in enumerate(data.get("findings") or [], start=1):
        if not isinstance(item, dict):
            continue
        try:
            findings.append(_finding_from_raw(index, item))
        except Exception as exc:
            logger.warning("gemini_finding_parse_error", extra={"index": index, "error": str(exc)[:200]})
            continue
    return VisionResult(room_type=room, findings=findings, is_home_environment=True, not_applicable_reason_ja=None)


def _finding_from_raw(index: int, item: dict[str, Any]) -> RiskFinding:
    raw_bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
    normalized_bbox = _normalize_bbox(raw_bbox)
    needs_confirmation = bool(item.get("needs_human_confirmation", False))

    # Mark for human confirmation if bbox was invalid/missing
    if not raw_bbox or normalized_bbox.get("_was_clamped"):
        needs_confirmation = True

    return RiskFinding(
        id=f"R{index}",
        risk_type=str(item.get("risk_type") or "visible_risk"),
        label_ja=str(item.get("label_ja") or "見えるリスク"),
        description_ja=str(item.get("description_ja") or "写真内に安全上の注意点が見えます。"),
        severity=_clamp_int(item.get("severity"), 1, 5, default=3),
        confidence=_clamp_float(item.get("confidence"), 0.0, 1.0, default=0.6),
        bbox=BoundingBox(
            x=normalized_bbox["x"],
            y=normalized_bbox["y"],
            w=normalized_bbox["w"],
            h=normalized_bbox["h"],
        ),
        evidence_ja=str(item.get("evidence_ja") or "写真内で確認できる範囲の所見です。"),
        basis_label_ja="",
        basis_summary_ja="",
        needs_human_confirmation=needs_confirmation,
    )


def _normalize_bbox(raw_bbox: dict[str, Any]) -> dict[str, Any]:
    """Normalize bbox values to 0-1 range.

    If values look like 0-1000 normalized coordinates (any value > 1.0),
    convert them to 0-1 by dividing by 1000.
    Invalid values are clamped to safe defaults.
    """
    if not raw_bbox:
        return {"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.3, "_was_clamped": True}

    x = _to_float(raw_bbox.get("x"), 0.1)
    y = _to_float(raw_bbox.get("y"), 0.1)
    w = _to_float(raw_bbox.get("w"), 0.4)
    h = _to_float(raw_bbox.get("h"), 0.3)

    was_clamped = False

    # Check if values look like 0-1000 range (any value > 1.0 but <= 1000)
    values = [x, y, w, h]
    if any(v > 1.0 for v in values) and all(0.0 <= v <= 1000.0 for v in values):
        x /= 1000.0
        y /= 1000.0
        w /= 1000.0
        h /= 1000.0
        logger.info("bbox_normalized_from_1000_range", extra={"original": values})

    # Clamp all values to valid 0-1 range
    for name, val in [("x", x), ("y", y), ("w", w), ("h", h)]:
        if val < 0.0 or val > 1.0:
            was_clamped = True

    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    w = max(0.0, min(1.0, w))
    h = max(0.0, min(1.0, h))

    # Ensure minimum visible size
    if w < 0.01:
        w = 0.4
        was_clamped = True
    if h < 0.01:
        h = 0.3
        was_clamped = True

    # Ensure box doesn't extend past image
    if x + w > 1.0:
        w = 1.0 - x
    if y + h > 1.0:
        h = 1.0 - y

    return {"x": x, "y": y, "w": w, "h": h, "_was_clamped": was_clamped}


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
