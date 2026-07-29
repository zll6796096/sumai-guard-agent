from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Any, NoReturn

from app.config import settings
from app.errors import GeminiUnavailableError
from app.models import (
    BoundingBox,
    RiskFinding,
    RoomType,
    VisionFacts,
    VisionResult,
    MissingSafetyFeature,
)
from app.ontology import OntologyRepository


logger = logging.getLogger("sumai.gemini_vision")

ONTOLOGY = OntologyRepository.load_default()
VALID_ROOMS: set[str] = {*ONTOLOGY.room_names, "auto"}
CHECKLIST_EXPECTED_FEATURE_KEYS: frozenset[str] = frozenset(ONTOLOGY.expected_feature_keys)
CHECKLIST_VISIBLE_OBSERVATION_KEYS: frozenset[str] = frozenset(
    ONTOLOGY.visible_observation_keys
)
CHECKLIST_VISIBLE_RISK_TYPES: frozenset[str] = frozenset(
    item["risk_type"]
    for room in ONTOLOGY.room_names
    for item in (ONTOLOGY.room(room) or {}).get("visible_hazards", [])
)
VALID_OBSERVATION_KEYS: frozenset[str] = (
    CHECKLIST_EXPECTED_FEATURE_KEYS | CHECKLIST_VISIBLE_OBSERVATION_KEYS
)


def _bbox_response_json_schema() -> dict[str, Any]:
    coordinate = {"type": "number", "minimum": 0, "maximum": 1}
    positive_extent = {"type": "number", "minimum": 0.000001, "maximum": 1}
    return {
        "type": "object",
        "properties": {
            "x": coordinate,
            "y": coordinate,
            "w": positive_extent,
            "h": positive_extent,
        },
        "required": ["x", "y", "w", "h"],
        "additionalProperties": False,
    }


GEMINI_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_home_environment": {"type": "boolean"},
        "room_type": {"type": "string", "enum": sorted(VALID_ROOMS)},
        "observations": {
            "type": "object",
            "properties": {
                key: {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
                for key in sorted(VALID_OBSERVATION_KEYS)
            },
            # Empty and partial observations are intentionally valid when the
            # photo does not show enough of the relevant room area.
            "additionalProperties": False,
        },
        "visible_hazards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "risk_type": {
                        "type": "string",
                        "enum": sorted(CHECKLIST_VISIBLE_RISK_TYPES),
                    },
                    "label_ja": {"type": "string"},
                    "description_ja": {"type": "string"},
                    "severity": {"type": "integer", "minimum": 1, "maximum": 5},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "bbox": _bbox_response_json_schema(),
                    "evidence_ja": {"type": "string"},
                },
                "required": [
                    "risk_type",
                    "label_ja",
                    "description_ja",
                    "severity",
                    "confidence",
                    "bbox",
                    "evidence_ja",
                ],
                "additionalProperties": False,
            },
        },
        "missing_safety_features": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "feature_key": {
                        "type": "string",
                        "enum": sorted(CHECKLIST_EXPECTED_FEATURE_KEYS),
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "bbox": _bbox_response_json_schema(),
                    "evidence_ja": {"type": "string"},
                },
                "required": ["feature_key", "confidence", "bbox", "evidence_ja"],
                "additionalProperties": False,
            },
        },
        "not_applicable_reason_ja": {
            "anyOf": [{"type": "string"}, {"type": "null"}]
        },
    },
    "required": [
        "is_home_environment",
        "room_type",
        "observations",
        "visible_hazards",
        "missing_safety_features",
    ],
    "additionalProperties": False,
}


_FACTS_ROOM_TYPES = [*ONTOLOGY.room_names, "unknown"]
_FACTS_VISIBLE_REGIONS = list(ONTOLOGY.visible_region_keys)
_FACTS_REQUIRED_FIELDS = [
    "environment",
    "room_type",
    "visible_regions",
    "entities",
    "feature_observations",
    "relationships",
    "not_applicable_reason_code",
]


GEMINI_FACTS_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "environment": {"type": "string", "enum": ["home", "non_home", "uncertain"]},
        "room_type": {"type": "string", "enum": _FACTS_ROOM_TYPES},
        "visible_regions": {
            "type": "array",
            "items": {"type": "string", "enum": _FACTS_VISIBLE_REGIONS},
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "minLength": 1, "maxLength": 32},
                    "ontology_key": {
                        "type": "string",
                        "enum": sorted(ONTOLOGY.visible_observation_keys),
                    },
                    "bbox": _bbox_response_json_schema(),
                    "visibility": {"type": "string", "enum": ["clear", "partial", "uncertain"]},
                    "model_score": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["ref", "ontology_key", "bbox", "visibility", "model_score"],
                "additionalProperties": False,
            },
        },
        "feature_observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "feature_key": {
                        "type": "string",
                        "enum": sorted(ONTOLOGY.expected_feature_keys),
                    },
                    "state": {
                        "type": "string",
                        "enum": ["present", "absent_with_full_coverage", "cannot_determine"],
                    },
                    "evidence_bbox": {
                        "anyOf": [_bbox_response_json_schema(), {"type": "null"}]
                    },
                    "model_score": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["feature_key", "state", "evidence_bbox", "model_score"],
                "additionalProperties": False,
            },
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "predicate": {"type": "string", "enum": sorted(ONTOLOGY.relationships)},
                    "object": {"type": "string"},
                },
                "required": ["subject", "predicate", "object"],
                "additionalProperties": False,
            },
        },
        "not_applicable_reason_code": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": _FACTS_REQUIRED_FIELDS,
    "additionalProperties": False,
}


VISION_PROMPT = f"""Extract only minimal visual evidence from one photo of a possible home.
Return facts that are directly visible; do not assess risk, severity, action tiers, Japanese reports,
recommendations, legal compliance, care needs, or construction. Do not ask user profile questions.

Environment and coverage rules:
1. Use environment=non_home for clearly non-residential or unrelated scenes. Use uncertain when the
   photo does not establish a home environment. Do not invent a reason code.
2. Correct room_type only when the room is visible; otherwise use unknown.
3. Emit entities only for directly visible objects or conditions using the supplied ontology keys.
   Give each a tight bbox entirely inside the image; x + w and y + h must be at most 1.
4. A feature can be absent_with_full_coverage only when its relevant region is completely visible.
   Use cannot_determine for cropped, obscured, or ambiguous areas. Never infer an absence from a
   missing or out-of-frame region.
5. Relationships must use supplied ontology predicates and refer to visible entity refs or named
   visible regions. Allowed visible regions: {", ".join(_FACTS_VISIBLE_REGIONS)}. Do not invent objects or relationships.
"""


def _raise_facts_error(reason: str, *, raw_length: int | None = None) -> NoReturn:
    extra: dict[str, object] = {"reason": reason}
    if raw_length is not None:
        extra["raw_length"] = raw_length
    logger.warning("gemini_facts_validation_error", extra=extra)
    raise ValueError("Gemini facts response is invalid.")


def _validate_facts_bbox(field: str, bbox: BoundingBox) -> None:
    if bbox.w <= 0 or bbox.h <= 0:
        _raise_facts_error(f"{field}_non_positive_extent")
    if bbox.x + bbox.w > 1 or bbox.y + bbox.h > 1:
        _raise_facts_error(f"{field}_outside_image")


def parse_vision_facts_json(raw_json: str) -> VisionFacts:
    """Parse constrained provider output without logging raw visual/provider payloads."""
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        _raise_facts_error("json_decode", raw_length=len(raw_json))

    if not isinstance(data, dict):
        _raise_facts_error("non_object", raw_length=len(raw_json))
    if any(field not in data for field in _FACTS_REQUIRED_FIELDS):
        _raise_facts_error("missing_top_level_field", raw_length=len(raw_json))

    try:
        facts = VisionFacts.model_validate(data, strict=True)
    except Exception:
        _raise_facts_error("pydantic_validation", raw_length=len(raw_json))

    for entity in facts.entities:
        if entity.ontology_key not in ONTOLOGY.visible_observation_keys:
            _raise_facts_error("unknown_entity_ontology_key")
        _validate_facts_bbox("entity_bbox", entity.bbox)
    entity_refs = [entity.ref for entity in facts.entities]
    if len(entity_refs) != len(set(entity_refs)):
        _raise_facts_error("duplicate_entity_ref")
    for feature in facts.feature_observations:
        if feature.feature_key not in ONTOLOGY.expected_feature_keys:
            _raise_facts_error("unknown_feature_ontology_key")
        if feature.evidence_bbox is not None:
            _validate_facts_bbox("feature_evidence_bbox", feature.evidence_bbox)
    feature_keys = [feature.feature_key for feature in facts.feature_observations]
    if len(feature_keys) != len(set(feature_keys)):
        _raise_facts_error("duplicate_feature_observation")
    if any(region not in ONTOLOGY.visible_region_keys for region in facts.visible_regions):
        _raise_facts_error("unknown_visible_region")
    valid_relationship_objects = set(entity_refs) | set(facts.visible_regions)
    for relationship in facts.relationships:
        if relationship.predicate not in ONTOLOGY.relationships:
            _raise_facts_error("unknown_relationship_predicate")
        if relationship.subject not in entity_refs:
            _raise_facts_error("dangling_relationship_subject")
        if relationship.object not in valid_relationship_objects:
            _raise_facts_error("dangling_relationship_object")
    return facts


def _gemini_failure_reason(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "gemini_timeout"
    if isinstance(exc, ValueError):
        return "invalid_response"
    return "provider_error"


class GeminiVisionService:
    async def analyze(
        self,
        image_png: bytes,
        room_hint: str = "auto",
        force_mock: bool = False,
        analysis_id: str = "",
    ) -> tuple[VisionFacts, str]:
        """Analyze image. Returns minimal visual facts and an execution mode."""
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
            return mock_vision_facts(normalized_room), mode

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
    ) -> tuple[VisionFacts, str]:
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
                    "entity_count": len(getattr(result, "entities", [])),
                    "feature_count": len(getattr(result, "feature_observations", [])),
                    "latency_ms": latency_ms,
                },
            )
            return result, "gemini"
        except Exception as exc:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            fallback_reason = _gemini_failure_reason(exc)
            logger.error(
                "vision_failed_strict",
                extra={
                    "analysis_id": analysis_id,
                    "fallback_reason": fallback_reason,
                    "latency_ms": latency_ms,
                },
            )
            raise GeminiUnavailableError("Real Gemini analysis failed.") from None

    async def _analyze_with_gemini(
        self,
        image_png: bytes,
        room_hint: RoomType,
        analysis_id: str,
    ) -> tuple[VisionFacts, str]:
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
                    "entity_count": len(getattr(result, "entities", [])),
                    "feature_count": len(getattr(result, "feature_observations", [])),
                    "latency_ms": latency_ms,
                },
            )
            return result, "gemini"

        except Exception as exc:
            fallback_reason = _gemini_failure_reason(exc)

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
        return mock_vision_facts(room_hint), f"gemini_fallback({fallback_reason})"

    async def _call_gemini(self, image_png: bytes, room_hint: RoomType) -> VisionFacts:
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
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=GEMINI_FACTS_JSON_SCHEMA,
            ),
        )
        return parse_vision_facts_json(response.text or "")


def normalize_room_hint(room_hint: str | None) -> RoomType:
    if not room_hint:
        return "auto"
    value = room_hint.strip().lower()
    if value in VALID_ROOMS:
        return value  # type: ignore[return-value]
    return "auto"


def mock_vision_facts(room_hint: RoomType) -> VisionFacts:
    """Deterministic evidence-only fixture used by mock and non-strict fallback paths."""
    room = room_hint if room_hint != "auto" else "toilet"
    entity_by_room = {
        "genkan": "genkan_step",
        "hallway": "hallway_cord",
        "bathroom": "wet_floor",
        "toilet": "has_floor_clutter",
        "bedroom": "cluttered_path",
        "kitchen": "kitchen_slip",
    }
    relationship_by_room = {
        "genkan": ("located_in", "floor"),
        "hallway": ("intersects", "walking_path"),
        "bathroom": ("located_in", "floor"),
        "toilet": ("obstructs", "walking_path"),
        "bedroom": ("obstructs", "walking_path"),
        "kitchen": ("located_in", "floor"),
    }
    feature_by_room = {
        "genkan": "has_handrail_or_support",
        "hallway": "clear_path",
        "bathroom": "has_handrail",
        "toilet": "has_handrail",
        "bedroom": "stable_bedside_support",
        "kitchen": "clear_floor",
    }
    entity_key = entity_by_room[room]
    return VisionFacts(
        environment="home",
        room_type=room,
        visible_regions=["floor", "walking_path"],
        entities=[
            {
                "ref": "mock-entity-1",
                "ontology_key": entity_key,
                "bbox": {"x": 0.16, "y": 0.58, "w": 0.58, "h": 0.2},
                "visibility": "clear",
                "model_score": 0.82,
            }
        ],
        feature_observations=[
            {
                "feature_key": feature_by_room[room],
                "state": "cannot_determine",
                "evidence_bbox": None,
                "model_score": 0.5,
            }
        ],
        relationships=[
            {
                "subject": "mock-entity-1",
                "predicate": relationship_by_room[room][0],
                "object": relationship_by_room[room][1],
            }
        ],
        not_applicable_reason_code=None,
    )


def mock_vision_result(room_hint: RoomType) -> VisionResult:
    room = room_hint if room_hint != "auto" else "toilet"

    obs_fixtures: dict[str, dict[str, bool | None]] = {
        "genkan": {
            "has_handrail_or_support": False,
            "step_visible_marking": False,
            "poor_lighting": False,
            "has_floor_clutter": True,
        },
        "hallway": {
            "clear_path": False,
            "sufficient_lighting": True,
            "has_floor_clutter": True,
            "has_loose_mat": True,
        },
        "bathroom": {
            "has_handrail": False,
            "has_non_slip_floor_or_mat": False,
            "has_bath_transfer_support": False,
            "wet_floor": True,
            "bathtub_stepover": True,
        },
        "toilet": {
            "has_handrail": False,
            "has_emergency_call_button": False,
            "has_floor_clutter": True,
            "looks_slippery_floor": True,
        },
        "bedroom": {
            "clear_path_from_bed": False,
            "stable_bedside_support": False,
            "has_floor_clutter": True,
            "poor_lighting": True,
        },
        "kitchen": {
            "clear_floor": False,
            "kitchen_slip": True,
            "has_loose_mat": True,
        }
    }

    hazards_fixtures: dict[str, list[dict[str, Any]]] = {
        "genkan": [
            {
                "risk_type": "genkan_step",
                "label_ja": "玄関上がり框・段差",
                "description_ja": "玄関の上がり框に段差があり、足を上げる動作でつまずくリスクがあります。",
                "severity": 4,
                "confidence": 0.88,
                "bbox": {"x": 0.12, "y": 0.55, "w": 0.68, "h": 0.22},
                "evidence_ja": "床面の高さが切り替わる境目が見えます。",
            }
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
            }
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
            }
        ],
        "toilet": [
            {
                "risk_type": "cluttered_path",
                "label_ja": "床の物・動線阻害",
                "description_ja": "トイレの動線上に物が置かれており、つまずく原因になります。",
                "severity": 3,
                "confidence": 0.80,
                "bbox": {"x": 0.32, "y": 0.65, "w": 0.25, "h": 0.2},
                "evidence_ja": "通路の床にマットや小物が散乱しています。",
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
            }
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
        ]
    }

    missing_fixtures: dict[str, list[dict[str, Any]]] = {
        "genkan": [
            {
                "feature_key": "has_handrail_or_support",
                "confidence": 0.85,
                "bbox": {"x": 0.05, "y": 0.1, "w": 0.1, "h": 0.8},
                "evidence_ja": "玄関の壁面付近に手すりや支えが確認できません。"
            }
        ],
        "bathroom": [
            {
                "feature_key": "has_handrail",
                "confidence": 0.90,
                "bbox": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
                "evidence_ja": "浴室の壁面や浴槽付近に手すりが見つかりません。"
            },
            {
                "feature_key": "has_non_slip_floor_or_mat",
                "confidence": 0.80,
                "bbox": {"x": 0.2, "y": 0.6, "w": 0.6, "h": 0.3},
                "evidence_ja": "浴室の床に滑り止めマットなどの対策が見られません。"
            }
        ],
        "toilet": [
            {
                "feature_key": "has_handrail",
                "confidence": 0.85,
                "bbox": {"x": 0.1, "y": 0.2, "w": 0.15, "h": 0.6},
                "evidence_ja": "便器の側面に手すりなどの支持物が確認できません。"
            },
            {
                "feature_key": "has_emergency_call_button",
                "confidence": 0.75,
                "bbox": {"x": 0.8, "y": 0.3, "w": 0.15, "h": 0.2},
                "evidence_ja": "壁面に緊急時の呼び出しボタンが確認できません。"
            }
        ],
        "bedroom": [
            {
                "feature_key": "stable_bedside_support",
                "confidence": 0.80,
                "bbox": {"x": 0.05, "y": 0.3, "w": 0.1, "h": 0.5},
                "evidence_ja": "ベッドの周囲に立ち上がり用の手すりが見当たりません。"
            }
        ]
    }

    obs = obs_fixtures.get(room, {})
    raw_hazards = hazards_fixtures.get(room, [])
    raw_missing = missing_fixtures.get(room, [])

    visible_hazards = [
        RiskFinding(
            id=f"R{i}",
            risk_type=h["risk_type"],
            label_ja=h["label_ja"],
            description_ja=h["description_ja"],
            severity=h["severity"],
            confidence=h["confidence"],
            bbox=BoundingBox(**h["bbox"]),
            evidence_ja=h["evidence_ja"],
            basis_label_ja="",
            basis_summary_ja="",
            needs_human_confirmation=False
        )
        for i, h in enumerate(raw_hazards, start=1)
    ]

    missing_features = [
        MissingSafetyFeature(
            feature_key=m["feature_key"],
            confidence=m["confidence"],
            bbox=BoundingBox(**m["bbox"]),
            evidence_ja=m["evidence_ja"]
        )
        for m in raw_missing
    ]

    return VisionResult(
        room_type=room_hint,
        is_home_environment=True,
        observations=obs,
        visible_hazards=visible_hazards,
        missing_safety_features=missing_features,
        not_applicable_reason_ja=None
    )


def _raise_schema_error(field: str, expected: str) -> NoReturn:
    logger.warning(
        "gemini_schema_validation_error schema_field=%s schema_expected=%s",
        field,
        expected,
        extra={"field": field, "expected": expected},
    )
    raise ValueError(f"Gemini response field '{field}' must be {expected}.")


CANONICAL_REQUIRED_FIELDS = (
    "is_home_environment",
    "room_type",
    "observations",
    "visible_hazards",
    "missing_safety_features",
)
CANONICAL_MARKER_FIELDS = (
    "is_home_environment",
    "observations",
    "visible_hazards",
    "missing_safety_features",
    "not_applicable_reason_ja",
)
CANONICAL_HAZARD_FIELDS = (
    "risk_type",
    "label_ja",
    "description_ja",
    "severity",
    "confidence",
    "bbox",
    "evidence_ja",
)
CANONICAL_MISSING_FEATURE_FIELDS = (
    "feature_key",
    "confidence",
    "bbox",
    "evidence_ja",
)


def _canonical_number(field: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _raise_schema_error(field, "a number")
    try:
        numeric_value = float(value)
    except (OverflowError, TypeError, ValueError):
        _raise_schema_error(field, "a finite number")
    if not math.isfinite(numeric_value):
        _raise_schema_error(field, "a finite number")
    return numeric_value


def _validate_bbox_schema(field: str, bbox: object) -> None:
    if not isinstance(bbox, dict):
        _raise_schema_error(field, "an object")
    numeric_values: dict[str, float] = {}
    for coordinate in ("x", "y", "w", "h"):
        coordinate_field = f"{field}.{coordinate}"
        if coordinate not in bbox:
            _raise_schema_error(coordinate_field, "present")
        numeric_value = _canonical_number(coordinate_field, bbox[coordinate])
        numeric_values[coordinate] = numeric_value
        if not 0.0 <= numeric_value <= 1.0:
            _raise_schema_error(coordinate_field, "a finite number from 0 to 1")
        if coordinate in ("w", "h") and numeric_value <= 0.0:
            _raise_schema_error(coordinate_field, "greater than 0")

    if numeric_values["x"] + numeric_values["w"] > 1.0:
        _raise_schema_error(field, "fully inside the image width")
    if numeric_values["y"] + numeric_values["h"] > 1.0:
        _raise_schema_error(field, "fully inside the image height")


def _validate_canonical_item(
    collection: str,
    index: int,
    item: dict[str, Any],
    required_fields: tuple[str, ...],
) -> None:
    item_path = f"{collection}[{index}]"
    for field in required_fields:
        if field not in item:
            _raise_schema_error(f"{item_path}.{field}", "present")

    string_fields = (
        ("risk_type", "label_ja", "description_ja", "evidence_ja")
        if collection == "visible_hazards"
        else ("feature_key", "evidence_ja")
    )
    for field in string_fields:
        if not isinstance(item[field], str):
            _raise_schema_error(f"{item_path}.{field}", "a string")

    if collection == "visible_hazards":
        if item["risk_type"] not in CHECKLIST_VISIBLE_RISK_TYPES:
            _raise_schema_error(
                f"{item_path}.risk_type",
                "an exact supported checklist risk type",
            )
        if type(item["severity"]) is not int:
            _raise_schema_error(f"{item_path}.severity", "an integer")
        if not 1 <= item["severity"] <= 5:
            _raise_schema_error(f"{item_path}.severity", "from 1 to 5")
    elif item["feature_key"] not in CHECKLIST_EXPECTED_FEATURE_KEYS:
        _raise_schema_error(
            f"{item_path}.feature_key",
            "an exact supported checklist feature key",
        )

    confidence_field = f"{item_path}.confidence"
    confidence = _canonical_number(confidence_field, item["confidence"])
    if not 0.0 <= confidence <= 1.0:
        _raise_schema_error(
            confidence_field,
            "a finite number from 0 to 1",
        )

    _validate_bbox_schema(f"{item_path}.bbox", item["bbox"])


def _validate_top_level_schema(data: dict[str, Any]) -> None:
    if "is_home_environment" in data and type(data["is_home_environment"]) is not bool:
        _raise_schema_error("is_home_environment", "a boolean")

    if "room_type" in data and not isinstance(data["room_type"], str):
        _raise_schema_error("room_type", "a string")

    if "observations" in data and not isinstance(data["observations"], dict):
        _raise_schema_error("observations", "an object")

    for field in ("visible_hazards", "findings", "missing_safety_features"):
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, list):
            _raise_schema_error(field, "a list")
        if any(not isinstance(item, dict) for item in value):
            _raise_schema_error(field, "a list of objects")

    is_legacy = "findings" in data and not any(
        field in data for field in CANONICAL_MARKER_FIELDS
    )
    if is_legacy:
        if "room_type" not in data:
            _raise_schema_error("room_type", "present in a legacy response")
        return

    is_canonical = any(field in data for field in CANONICAL_MARKER_FIELDS)
    if is_canonical:
        if "room_type" in data and data["room_type"] not in VALID_ROOMS:
            _raise_schema_error("room_type", "an exact supported room value")
        if (
            "not_applicable_reason_ja" in data
            and data["not_applicable_reason_ja"] is not None
            and not isinstance(data["not_applicable_reason_ja"], str)
        ):
            _raise_schema_error("not_applicable_reason_ja", "a string or null")
        for observation, value in data.get("observations", {}).items():
            if observation not in VALID_OBSERVATION_KEYS:
                _raise_schema_error(
                    "observations.<invalid_key>",
                    "a supported prompt observation",
                )
            if value is not None and type(value) is not bool:
                _raise_schema_error(
                    f"observations.{observation}",
                    "a boolean or null",
                )
        for index, item in enumerate(data.get("visible_hazards", [])):
            _validate_canonical_item(
                "visible_hazards",
                index,
                item,
                CANONICAL_HAZARD_FIELDS,
            )
        for index, item in enumerate(data.get("missing_safety_features", [])):
            _validate_canonical_item(
                "missing_safety_features",
                index,
                item,
                CANONICAL_MISSING_FEATURE_FIELDS,
            )
        for field in CANONICAL_REQUIRED_FIELDS:
            if field not in data:
                _raise_schema_error(field, "present in a canonical response")
        return

    _raise_schema_error(
        "response",
        "a complete canonical response or legacy room_type/findings response",
    )


def parse_vision_json(raw_json: str, fallback_room: RoomType) -> VisionResult:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        logger.warning("gemini_json_decode_error", extra={"raw_length": len(raw_json)})
        raise ValueError("Gemini response is empty or not valid JSON.") from None

    if not isinstance(data, dict):
        logger.warning("gemini_unexpected_json_type", extra={"type": type(data).__name__})
        raise ValueError(
            f"Gemini response must be a JSON object, got {type(data).__name__}."
        )

    _validate_top_level_schema(data)

    is_home = data.get("is_home_environment", True)
    not_applicable_reason = data.get("not_applicable_reason_ja")

    if not is_home:
        return VisionResult(
            room_type="auto",
            is_home_environment=False,
            observations={},
            visible_hazards=[],
            missing_safety_features=[],
            not_applicable_reason_ja=not_applicable_reason or "住宅内の安全確認対象ではない可能性があります。"
        )

    room = normalize_room_hint(data.get("room_type") or fallback_room)
    observations = data.get("observations", {})

    visible_hazards: list[RiskFinding] = []
    raw_hazards = (
        data["visible_hazards"]
        if "visible_hazards" in data
        else data.get("findings", [])
    )
    for index, item in enumerate(raw_hazards, start=1):
        try:
            visible_hazards.append(_finding_from_raw(index, item))
        except Exception:
            logger.warning("gemini_hazard_parse_error", extra={"index": index})
            continue

    missing_safety_features: list[MissingSafetyFeature] = []
    for index, item in enumerate(data.get("missing_safety_features", []), start=1):
        if "feature_key" not in item:
            continue
        try:
            raw_bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
            normalized_bbox = _normalize_bbox(raw_bbox)
            missing_safety_features.append(
                MissingSafetyFeature(
                    feature_key=str(item.get("feature_key")),
                    confidence=_clamp_float(item.get("confidence"), 0.0, 1.0, default=0.60),
                    bbox=BoundingBox(
                        x=normalized_bbox["x"],
                        y=normalized_bbox["y"],
                        w=normalized_bbox["w"],
                        h=normalized_bbox["h"]
                    ),
                    evidence_ja=str(item.get("evidence_ja") or "写真内で確認できません。")
                )
            )
        except Exception:
            logger.warning("gemini_missing_parse_error", extra={"index": index})
            continue

    return VisionResult(
        room_type=room,
        is_home_environment=True,
        observations=observations,
        visible_hazards=visible_hazards,
        missing_safety_features=missing_safety_features,
        not_applicable_reason_ja=None
    )


def _finding_from_raw(index: int, item: dict[str, Any]) -> RiskFinding:
    raw_bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
    normalized_bbox = _normalize_bbox(raw_bbox)
    needs_confirmation = bool(item.get("needs_human_confirmation", False))

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
        evidence_ja=str(item.get("evidence_ja") or "写真内で確認できる範囲 of所見です。"),
        basis_label_ja="",
        basis_summary_ja="",
        needs_human_confirmation=needs_confirmation,
    )


def _normalize_bbox(raw_bbox: dict[str, Any]) -> dict[str, Any]:
    if not raw_bbox:
        return {"x": 0.1, "y": 0.1, "w": 0.4, "h": 0.3, "_was_clamped": True}

    x = _to_float(raw_bbox.get("x"), 0.1)
    y = _to_float(raw_bbox.get("y"), 0.1)
    w = _to_float(raw_bbox.get("w"), 0.4)
    h = _to_float(raw_bbox.get("h"), 0.3)

    was_clamped = False
    values = [x, y, w, h]
    if any(v > 1.0 for v in values) and all(0.0 <= v <= 1000.0 for v in values):
        x /= 1000.0
        y /= 1000.0
        w /= 1000.0
        h /= 1000.0

    for name, val in [("x", x), ("y", y), ("w", w), ("h", h)]:
        if val < 0.0 or val > 1.0:
            was_clamped = True

    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    w = max(0.0, min(1.0, w))
    h = max(0.0, min(1.0, h))

    if w < 0.01:
        w = 0.4
        was_clamped = True
    if h < 0.01:
        h = 0.3
        was_clamped = True

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
