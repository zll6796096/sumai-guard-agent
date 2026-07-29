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
    values = (
        pixel_digest,
        room_hint,
        preprocess_version,
        ontology_version,
        model,
        inference_config_version,
        execution_mode,
    )
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


def canonicalize_findings(findings: list[RiskFinding]) -> list[RiskFinding]:
    """Return copied, stably ordered findings with normalized evidence coordinates."""
    copied = [finding.model_copy(deep=True) for finding in findings]
    normalized: list[RiskFinding] = []
    for finding in copied:
        evidence_bbox = _rounded_evidence_bbox(finding.bbox)
        normalized.append(finding.model_copy(update={"bbox": evidence_bbox}))

    def sort_key(finding: RiskFinding) -> tuple[Any, ...]:
        bbox = finding.bbox
        # display_bbox is presentation-only for semantic hashing, but it must
        # participate in sorting so canonical output does not depend on input order.
        semantic_dump = finding.model_dump(mode="json", exclude={"id"})
        return (
            -finding.severity,
            finding.risk_type,
            bbox.x,
            bbox.y,
            bbox.w,
            bbox.h,
            -finding.confidence,
            finding.label_ja,
            json.dumps(semantic_dump, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )

    return [
        finding.model_copy(update={"id": f"R{index}"})
        for index, finding in enumerate(sorted(normalized, key=sort_key), start=1)
    ]


def _rounded_evidence_bbox(bbox: BoundingBox) -> BoundingBox:
    """Round coordinates without moving a previously in-bounds box out of frame."""
    x = round(bbox.x, 3)
    y = round(bbox.y, 3)
    w = min(round(bbox.w, 3), round(1.0 - x, 3))
    h = min(round(bbox.h, 3), round(1.0 - y, 3))
    return BoundingBox(x=x, y=y, w=max(0.0, w), h=max(0.0, h))


def semantic_hash(payload: object) -> str:
    canonical_json = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
