from __future__ import annotations

import hashlib
import json
from typing import Any

from PIL import Image

from app.models import BoundingBox, RiskFinding


def canonical_pixel_digest(image: Image.Image) -> str:
    """Hash normalized RGB pixels, independent of image container metadata."""
    normalized = image.convert("RGB")
    width, height = normalized.size
    payload = (
        normalized.mode.encode("ascii")
        + width.to_bytes(4, byteorder="big")
        + height.to_bytes(4, byteorder="big")
        + normalized.tobytes()
    )
    return hashlib.sha256(payload).hexdigest()


def result_key(
    pixel_digest: str,
    room_hint: str,
    preprocess_version: str,
    ontology_version: str,
    model: str,
    inference_config_version: str,
    execution_mode: str = "default",
) -> str:
    canonical_inputs = {
        "execution_mode": execution_mode,
        "inference_config_version": inference_config_version,
        "model": model,
        "ontology_version": ontology_version,
        "pixel_digest": pixel_digest,
        "preprocess_version": preprocess_version,
        "room_hint": room_hint,
    }
    encoded = json.dumps(
        canonical_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonicalize_findings(findings: list[RiskFinding]) -> list[RiskFinding]:
    """Return copied, stably ordered findings with normalized evidence coordinates."""
    copied = [finding.model_copy(deep=True) for finding in findings]
    normalized: list[RiskFinding] = []
    for finding in copied:
        # Evidence is factual output: preserve its coordinates and extent.  Only
        # canonicalize signed zero, which has no geometric meaning.
        updates: dict[str, BoundingBox | None] = {"bbox": _canonical_bbox(finding.bbox)}
        if finding.display_bbox is not None:
            updates["display_bbox"] = _canonical_bbox(finding.display_bbox)
        normalized.append(finding.model_copy(update=updates))

    def sort_key(finding: RiskFinding) -> tuple[Any, ...]:
        bbox = finding.bbox
        # Rounded evidence coordinates group near-identical boxes for ordering;
        # the complete, unrounded finding below is the final deterministic tie-breaker.
        rounded_bbox = tuple(round(value, 3) for value in (bbox.x, bbox.y, bbox.w, bbox.h))
        # display_bbox is presentation-only for semantic hashing, but it must
        # participate in sorting so canonical output does not depend on input order.
        full_dump = normalize_signed_zero(finding.model_dump(mode="json", exclude={"id"}))
        return (
            -finding.severity,
            finding.risk_type,
            *rounded_bbox,
            -finding.confidence,
            finding.label_ja,
            json.dumps(full_dump, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )

    return [
        finding.model_copy(update={"id": f"R{index}"})
        for index, finding in enumerate(sorted(normalized, key=sort_key), start=1)
    ]


def _canonical_bbox(bbox: BoundingBox) -> BoundingBox:
    """Keep evidence geometry intact while making signed zero canonical."""
    return BoundingBox(
        x=0.0 if bbox.x == 0.0 else bbox.x,
        y=0.0 if bbox.y == 0.0 else bbox.y,
        w=0.0 if bbox.w == 0.0 else bbox.w,
        h=0.0 if bbox.h == 0.0 else bbox.h,
    )


def normalize_signed_zero(payload: Any) -> Any:
    """Recursively canonicalize -0.0 so semantically equal JSON hashes equally."""
    if isinstance(payload, float):
        return 0.0 if payload == 0.0 else payload
    if isinstance(payload, list):
        return [normalize_signed_zero(item) for item in payload]
    if isinstance(payload, tuple):
        return [normalize_signed_zero(item) for item in payload]
    if isinstance(payload, dict):
        return {key: normalize_signed_zero(value) for key, value in payload.items()}
    return payload


def semantic_hash(payload: object) -> str:
    canonical_json = json.dumps(
        normalize_signed_zero(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
