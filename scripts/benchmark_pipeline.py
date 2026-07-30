#!/usr/bin/env python3
"""Bounded, local evaluation runner for SumaiGuard response and risk contracts."""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import stat
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import yaml
from PIL import Image, UnidentifiedImageError


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_IMAGE_ROOT = REPO_ROOT / "apps" / "sumai_web" / "assets" / "samples"
SAMPLE_IMAGE_COMPONENTS = ("apps", "sumai_web", "assets", "samples")
_trusted_root_stat = REPO_ROOT.stat()
TRUSTED_REPO_ROOT_ID = (_trusted_root_stat.st_dev, _trusted_root_stat.st_ino)
IMAGE_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
ROOM_HINTS = {"genkan", "hallway", "bathroom", "toilet", "bedroom", "kitchen", "auto"}
RISK_LEVELS = {"low", "medium", "high"}
ACTION_TIER_KEYS = {"family_no_cost", "care_manager_purchase", "contractor_construction"}
ACTION_TIERS = {"FAMILY_NO_COST", "CARE_MANAGER_PURCHASE", "CONTRACTOR_CONSTRUCTION"}
COST_LEVELS = {"ZERO", "LOW", "MEDIUM", "HIGH"}
STAGE_TIMING_KEYS = {
    "intake", "memo_lookup", "vision", "ontology", "render", "report", "serialize", "total",
}
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
ONTOLOGY_CONTRACT_PATH = (
    REPO_ROOT
    / "apps"
    / "sumai_agent"
    / "app"
    / "knowledge_base"
    / "room_checklists.yaml"
)
EXPECTED_PREPROCESS_VERSION = "1.0.0"
FINDING_FIELDS = {
    "id",
    "risk_type",
    "label_ja",
    "description_ja",
    "severity",
    "confidence",
    "bbox",
    "display_bbox",
    "evidence_source_ids",
    "evidence_ja",
    "basis_label_ja",
    "basis_summary_ja",
    "needs_human_confirmation",
    "ontology_key",
    "ontology_rule_kind",
}
ACTION_FIELDS = {
    "id",
    "risk_id",
    "tier",
    "title_ja",
    "description_ja",
    "why_ja",
    "cost_level",
    "requires_professional",
    "disclaimer_ja",
}


class BenchmarkError(ValueError):
    """A stable, non-sensitive benchmark failure code."""


def _load_ontology_contract(
    path: Path,
) -> tuple[
    str,
    str,
    str,
    frozenset[tuple[str, str, str]],
    frozenset[tuple[str, str]],
    tuple[str, ...],
]:
    """Load public versions and room-scoped visible identities or fail closed."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise BenchmarkError("invalid_ontology_contract") from None
    if not isinstance(document, dict):
        raise BenchmarkError("invalid_ontology_contract")

    action_policy = document.get("action_policy")
    family_policy = (
        action_policy.get("family")
        if isinstance(action_policy, dict)
        else None
    )
    forbidden_words = (
        family_policy.get("forbidden_words")
        if isinstance(family_policy, dict)
        else None
    )
    if (
        not isinstance(forbidden_words, list)
        or not forbidden_words
        or not all(
            isinstance(word, str) and word.strip()
            for word in forbidden_words
        )
        or len(set(forbidden_words)) != len(forbidden_words)
    ):
        raise BenchmarkError("invalid_ontology_contract")

    versions: list[str] = []
    for field in (
        "schema_version",
        "ontology_version",
        "inference_config_version",
    ):
        value = document.get(field)
        if not isinstance(value, str) or not value.strip():
            raise BenchmarkError("invalid_ontology_contract")
        versions.append(value)

    rooms = document.get("rooms")
    expected_rooms = ROOM_HINTS - {"auto"}
    if not isinstance(rooms, dict) or set(rooms) != expected_rooms:
        raise BenchmarkError("invalid_ontology_contract")

    identities: set[tuple[str, str, str]] = set()
    confirmation_identities: set[tuple[str, str]] = set()
    for room_name, room_document in rooms.items():
        if not isinstance(room_document, dict):
            raise BenchmarkError("invalid_ontology_contract")
        visible_hazards = room_document.get("visible_hazards")
        if not isinstance(visible_hazards, list) or not visible_hazards:
            raise BenchmarkError("invalid_ontology_contract")
        room_keys: set[str] = set()
        for rule in visible_hazards:
            if not isinstance(rule, dict):
                raise BenchmarkError("invalid_ontology_contract")
            ontology_key = rule.get("key")
            risk_type = rule.get("risk_type")
            if (
                not isinstance(ontology_key, str)
                or not ontology_key.strip()
                or ontology_key in room_keys
                or not isinstance(risk_type, str)
                or not risk_type.strip()
            ):
                raise BenchmarkError("invalid_ontology_contract")
            room_keys.add(ontology_key)
            identities.add((room_name, ontology_key, risk_type))
        expected_features = room_document.get("expected_features")
        if not isinstance(expected_features, list):
            raise BenchmarkError("invalid_ontology_contract")
        expected_keys: set[str] = set()
        for rule in expected_features:
            if not isinstance(rule, dict):
                raise BenchmarkError("invalid_ontology_contract")
            feature_key = rule.get("key")
            if (
                not isinstance(feature_key, str)
                or not feature_key.strip()
                or feature_key in expected_keys
            ):
                raise BenchmarkError("invalid_ontology_contract")
            expected_keys.add(feature_key)
            confirmation_identities.add((room_name, feature_key))
    if not identities:
        raise BenchmarkError("invalid_ontology_contract")

    return (
        versions[0],
        versions[1],
        versions[2],
        frozenset(identities),
        frozenset(confirmation_identities),
        tuple(forbidden_words),
    )


(
    EXPECTED_SCHEMA_VERSION,
    EXPECTED_ONTOLOGY_VERSION,
    EXPECTED_INFERENCE_CONFIG_VERSION,
    VISIBLE_FINDING_IDENTITIES,
    EXPECTED_CONFIRMATION_IDENTITIES,
    FAMILY_FORBIDDEN_WORDS,
) = _load_ontology_contract(ONTOLOGY_CONTRACT_PATH)


def percentile(samples: list[float | int], quantile: float) -> float | int:
    """Nearest-rank percentile; q=0 is minimum and q=1 is maximum."""
    if not samples or not 0 <= quantile <= 1:
        raise ValueError("invalid_percentile_input")
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in samples):
        raise ValueError("invalid_percentile_input")
    ordered = sorted(samples)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def precision_recall_f1(predicted: set[str], expected: set[str]) -> dict[str, float | int]:
    """Set metrics, with predicted first and expected second."""
    tp, fp, fn = len(predicted & expected), len(predicted - expected), len(expected - predicted)
    precision = 1.0 if not predicted and not expected else (tp / (tp + fp) if predicted else 0.0)
    recall = 1.0 if not expected else tp / (tp + fn)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def validate_repeat(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 50:
        raise ValueError("invalid_repeat")
    return value


def resolve_image_path(relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("unsafe_image_path")
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.parts[:-1] != SAMPLE_IMAGE_COMPONENTS:
        raise ValueError("unsafe_image_path")
    if not candidate.name or candidate.suffix.lower() not in IMAGE_MEDIA_TYPES:
        raise ValueError("unsafe_image_path")
    return candidate


def read_approved_image(image_path: Path) -> bytes:
    """Read an allowed relative image through trusted dir fds without following links."""
    relative = resolve_image_path(str(image_path))
    descriptor = _open_approved_image_fd(relative)
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as file_handle:
            descriptor = -1
            data = file_handle.read()
    finally:
        if descriptor != -1:
            os.close(descriptor)
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValueError("invalid_image_content") from None
    return data


def _open_approved_image_fd(relative: Path) -> int:
    """Open the root and every allowed component with no-follow semantics or fail closed."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None or os.open not in os.supports_dir_fd:
        raise ValueError("unsafe_image_path")
    current = -1
    try:
        current = os.open(str(REPO_ROOT), os.O_RDONLY | directory | nofollow)
        root_stat = os.fstat(current)
        if not stat.S_ISDIR(root_stat.st_mode) or (root_stat.st_dev, root_stat.st_ino) != TRUSTED_REPO_ROOT_ID:
            raise ValueError("unsafe_image_path")
        components = (*SAMPLE_IMAGE_COMPONENTS, relative.name)
        for index, component in enumerate(components):
            is_final = index == len(components) - 1
            flags = os.O_RDONLY | nofollow | (0 if is_final else directory)
            next_fd = os.open(component, flags, dir_fd=current)
            os.close(current)
            current = next_fd
        opened = os.fstat(current)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError("unsafe_image_path")
        return current
    except (OSError, ValueError):
        if current != -1:
            os.close(current)
        raise ValueError("unsafe_image_path") from None


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise ValueError("invalid_manifest") from None
    if not isinstance(loaded, dict) or set(loaded) != {"version", "classification", "cases"}:
        raise ValueError("invalid_manifest")
    if not isinstance(loaded["version"], str) or loaded["classification"] not in {"synthetic", "reviewed"}:
        raise ValueError("invalid_manifest")
    cases = loaded["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("invalid_manifest")
    ids: set[str] = set()
    checked: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "image", "room_hint", "expected_risk_types"}:
            raise ValueError("invalid_manifest")
        case_id = case["id"]
        image = case["image"]
        room_hint = case["room_hint"]
        expected = case["expected_risk_types"]
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError("invalid_manifest")
        if not isinstance(image, str) or not isinstance(room_hint, str) or room_hint not in ROOM_HINTS:
            raise ValueError("invalid_manifest")
        if not isinstance(expected, list) or not all(isinstance(risk, str) and risk for risk in expected):
            raise ValueError("invalid_manifest")
        if len(set(expected)) != len(expected):
            raise ValueError("invalid_manifest")
        relative_image = resolve_image_path(image)
        read_approved_image(relative_image)
        ids.add(case_id)
        checked.append({"id": case_id, "image": str(relative_image), "room_hint": room_hint, "expected_risk_types": expected})
    return {"version": loaded["version"], "classification": loaded["classification"], "cases": checked}


def validate_response_schema(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    analysis_id = payload.get("analysis_id")
    if not isinstance(analysis_id, str) or not analysis_id.strip():
        return False
    if payload.get("room_type") not in ROOM_HINTS or payload.get("overall_risk_level") not in RISK_LEVELS:
        return False
    if not _is_public_response_text(payload):
        return False
    if any(
        payload.get(field) != expected
        for field, expected in {
            "schema_version": EXPECTED_SCHEMA_VERSION,
            "ontology_version": EXPECTED_ONTOLOGY_VERSION,
            "preprocess_version": EXPECTED_PREPROCESS_VERSION,
            "inference_config_version": EXPECTED_INFERENCE_CONFIG_VERSION,
        }.items()
    ):
        return False
    if not HEX_64.fullmatch(str(payload.get("result_key", ""))):
        return False
    if not HEX_64.fullmatch(str(payload.get("semantic_hash", ""))):
        return False
    findings = payload.get("findings")
    if not isinstance(findings, list) or not all(_valid_finding(item) for item in findings):
        return False
    room_type = payload.get("room_type")
    if any(
        (room_type, finding["ontology_key"], finding["risk_type"])
        not in VISIBLE_FINDING_IDENTITIES
        for finding in findings
    ):
        return False
    confirmation_items = payload.get("confirmation_items")
    if (
        not isinstance(confirmation_items, list)
        or not all(_valid_confirmation_item(item) for item in confirmation_items)
    ):
        return False
    if any(
        (room_type, item["feature_key"])
        not in EXPECTED_CONFIRMATION_IDENTITIES
        for item in confirmation_items
    ):
        return False
    if payload.get("overall_risk_level") != _risk_level_for_findings(findings):
        return False
    if payload["is_not_applicable"]:
        reason = payload.get("not_applicable_reason_ja")
        if (
            payload.get("room_type") != "auto"
            or payload.get("overall_risk_level") != "low"
            or not isinstance(reason, str)
            or not reason.strip()
            or findings
            or confirmation_items
        ):
            return False
        if payload.get("action_plan") != {
            "family_no_cost": [],
            "care_manager_purchase": [],
            "contractor_construction": [],
        }:
            return False
    elif (
        payload.get("is_home_environment") is not True
        or payload.get("room_type") == "auto"
        or payload.get("not_applicable_reason_ja") is not None
    ):
        return False
    finding_ids = [finding["id"] for finding in findings]
    confirmation_ids = [item["id"] for item in confirmation_items]
    confirmation_keys = [item["feature_key"] for item in confirmation_items]
    if (
        finding_ids
        != [f"R{index}" for index in range(1, len(finding_ids) + 1)]
        or confirmation_ids
        != [f"C{index}" for index in range(1, len(confirmation_ids) + 1)]
        or len(set(confirmation_keys)) != len(confirmation_keys)
        or not _valid_action_plan(payload.get("action_plan"), set(finding_ids))
    ):
        return False
    stages = payload.get("stage_timings_ms")
    return isinstance(stages, dict) and set(stages) == STAGE_TIMING_KEYS and all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in stages.values()
    )


def _is_public_response_text(payload: dict[str, object]) -> bool:
    string_fields = {
        "annotated_image_base64", "improvement_image_base64", "risk_summary_markdown",
        "confirmation_items_markdown", "family_actions_markdown",
        "care_manager_actions_markdown", "contractor_actions_markdown",
        "disclaimer_ja", "mode", "model", "schema_version", "ontology_version",
        "preprocess_version", "inference_config_version",
    }
    reason = payload.get("not_applicable_reason_ja")
    confirmation_markdown = payload.get("confirmation_items_markdown")
    return (
        "not_applicable_reason_ja" in payload
        and (reason is None or isinstance(reason, str))
        and all(isinstance(payload.get(field), str) for field in string_fields)
        and isinstance(confirmation_markdown, str)
        and bool(confirmation_markdown.strip())
        and isinstance(payload.get("is_home_environment"), bool)
        and isinstance(payload.get("is_not_applicable"), bool)
    )


def _valid_finding(item: object) -> bool:
    if not isinstance(item, dict) or set(item) != FINDING_FIELDS:
        return False
    text_fields = {
        "id",
        "risk_type",
        "label_ja",
        "description_ja",
        "evidence_ja",
        "basis_label_ja",
        "basis_summary_ja",
        "ontology_key",
    }
    if not all(isinstance(item.get(field), str) and item[field].strip() for field in text_fields):
        return False
    if item.get("ontology_rule_kind") != "visible_hazard":
        return False
    severity, confidence = item.get("severity"), item.get("confidence")
    if not isinstance(severity, int) or isinstance(severity, bool) or severity not in range(1, 6):
        return False
    if not _unit_number(confidence) or not _valid_bbox(item.get("bbox")):
        return False
    if item["display_bbox"] is not None and not _valid_bbox(item["display_bbox"]):
        return False
    return isinstance(item.get("evidence_source_ids"), list) and all(
        isinstance(source, str) and source for source in item["evidence_source_ids"]
    ) and isinstance(item.get("needs_human_confirmation"), bool)


def _valid_confirmation_item(item: object) -> bool:
    if not isinstance(item, dict) or set(item) != {
        "id",
        "feature_key",
        "label_ja",
        "description_ja",
        "confidence",
        "evidence_source_ids",
        "basis_label_ja",
        "basis_summary_ja",
        "needs_human_confirmation",
    }:
        return False
    text_fields = {
        "id",
        "feature_key",
        "label_ja",
        "description_ja",
        "basis_label_ja",
        "basis_summary_ja",
    }
    return (
        all(
            isinstance(item.get(field), str) and item[field].strip()
            for field in text_fields
        )
        and _unit_number(item.get("confidence"))
        and isinstance(item.get("evidence_source_ids"), list)
        and all(
            isinstance(source, str) and source
            for source in item["evidence_source_ids"]
        )
        and item.get("needs_human_confirmation") is True
    )


def _unit_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def _risk_level_for_findings(findings: list[dict[str, object]]) -> str:
    if not findings:
        return "low"
    max_severity = max(int(finding["severity"]) for finding in findings)
    if max_severity >= 4:
        return "high"
    if max_severity >= 2:
        return "medium"
    return "low"


def _valid_bbox(value: object) -> bool:
    if (
        not isinstance(value, dict)
        or set(value) != {"x", "y", "w", "h"}
        or not all(_unit_number(coordinate) for coordinate in value.values())
    ):
        return False
    x, y, width, height = value["x"], value["y"], value["w"], value["h"]
    return (
        width > 0
        and height > 0
        and x + width <= 1.0 + 1e-9
        and y + height <= 1.0 + 1e-9
    )


def _valid_action_plan(value: object, finding_ids: set[str]) -> bool:
    if not isinstance(value, dict) or set(value) != ACTION_TIER_KEYS:
        return False
    policies = {
        "family_no_cost": ("FAMILY_NO_COST", False, "ZERO"),
        "care_manager_purchase": ("CARE_MANAGER_PURCHASE", True, "LOW"),
        "contractor_construction": ("CONTRACTOR_CONSTRUCTION", True, "HIGH"),
    }
    action_ids: set[str] = set()
    for list_name, (tier, requires_professional, cost_level) in policies.items():
        actions = value[list_name]
        if not isinstance(actions, list):
            return False
        for action in actions:
            if not _valid_action(action) or action["id"] in action_ids or action["risk_id"] not in finding_ids:
                return False
            if action["tier"] != tier or action["requires_professional"] is not requires_professional or action["cost_level"] != cost_level:
                return False
            if list_name == "family_no_cost":
                text = " ".join(
                    str(action[field])
                    for field in ("title_ja", "description_ja", "why_ja")
                )
                if any(word in text for word in FAMILY_FORBIDDEN_WORDS):
                    return False
            action_ids.add(action["id"])
    return True


def _valid_action(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != ACTION_FIELDS:
        return False
    text_fields = {"id", "risk_id", "title_ja", "description_ja", "why_ja", "disclaimer_ja"}
    return (
        all(isinstance(value.get(field), str) and value[field].strip() for field in text_fields)
        and value.get("tier") in ACTION_TIERS
        and value.get("cost_level") in COST_LEVELS
        and isinstance(value.get("requires_professional"), bool)
    )


def _latency_summary(samples: list[float | int]) -> dict[str, float | int]:
    return {"p50": percentile(samples, 0.5), "p95": percentile(samples, 0.95), "max": max(samples)}


def _real_status_is_strict(response: Any) -> bool:
    try:
        data = response.json()
    except (ValueError, TypeError):
        return False
    return response.status_code == 200 and isinstance(data, dict) and all(
        data.get(key) is value
        for key, value in {
            "require_real_gemini": True, "has_gemini_api_key": True,
            "mock_mode": False, "mock_allowed": False,
        }.items()
    )


def run_benchmark(
    manifest: dict[str, Any], *, repeat: int, base_url: str, real: bool, timeout_seconds: float,
    client_factory: Callable[..., Any] = httpx.Client,
) -> dict[str, Any]:
    validate_repeat(repeat)
    if not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 120:
        raise ValueError("invalid_timeout")
    base_url = base_url.rstrip("/")
    wall_samples: list[float] = []
    application_samples: list[int] = []
    stages: dict[str, list[int]] = {key: [] for key in sorted(STAGE_TIMING_KEYS)}
    aggregate = {"tp": 0, "fp": 0, "fn": 0}
    schema_valid_count = 0
    scored_applicable_response_count = 0
    abstained_not_applicable_response_count = 0
    with client_factory(timeout=httpx.Timeout(timeout_seconds)) as client:
        if real and not _real_status_is_strict(client.get(f"{base_url}/status")):
            raise BenchmarkError("real_status_gate_failed")
        for _ in range(repeat):
            for case in manifest["cases"]:
                image_path = resolve_image_path(case["image"])
                started = time.monotonic()
                image_bytes = read_approved_image(image_path)
                response = client.post(
                    f"{base_url}/analyze",
                    data={"room_hint": case["room_hint"], "mock": "false" if real else "true"},
                    files={"image": (image_path.name, image_bytes, IMAGE_MEDIA_TYPES[image_path.suffix.lower()])},
                )
                wall_samples.append(round((time.monotonic() - started) * 1000, 3))
                try:
                    payload = response.json()
                except (ValueError, TypeError):
                    continue
                if response.status_code != 200 or not validate_response_schema(payload):
                    continue
                schema_valid_count += 1
                if payload["is_not_applicable"]:
                    abstained_not_applicable_response_count += 1
                else:
                    scored_applicable_response_count += 1
                    predicted = {finding["risk_type"] for finding in payload["findings"]}
                    metrics = precision_recall_f1(predicted, set(case["expected_risk_types"]))
                    for key in aggregate:
                        aggregate[key] += int(metrics[key])
                timing = payload["stage_timings_ms"]
                application_samples.append(timing["total"])
                for key, values in stages.items():
                    values.append(timing[key])
    request_count = len(manifest["cases"]) * repeat
    tp, fp, fn = aggregate["tp"], aggregate["fp"], aggregate["fn"]
    if scored_applicable_response_count == 0:
        available, precision, recall, f1 = False, None, None, None
        reason = (
            "all_schema_valid_responses_not_applicable"
            if schema_valid_count and abstained_not_applicable_response_count == schema_valid_count
            else "no_schema_valid_applicable_responses"
        )
    elif tp == fp == fn == 0:
        available, precision, recall, f1, reason = True, 1.0, 1.0, 1.0, None
    else:
        available, reason = True, None
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    latency = {"client_wall": _latency_summary(wall_samples)}
    if application_samples:
        latency["application_total"] = _latency_summary(application_samples)
        latency["stages"] = {key: _latency_summary(values) for key, values in stages.items()}
    else:
        latency["application_total"] = {"p50": None, "p95": None, "max": None}
        latency["stages"] = {key: {"p50": None, "p95": None, "max": None} for key in stages}
    return {
        "manifest_version": manifest["version"], "dataset_classification": manifest["classification"],
        "real_mode": real, "case_count": len(manifest["cases"]), "repeat": repeat,
        "request_count": request_count, "schema_valid_count": schema_valid_count,
        "schema_valid_rate": schema_valid_count / request_count if request_count else 0.0,
        "scored_applicable_response_count": scored_applicable_response_count,
        "scored_applicable_response_coverage": scored_applicable_response_count / request_count if request_count else 0.0,
        "abstained_not_applicable_response_count": abstained_not_applicable_response_count,
        "risk_metrics": {
            "available": available, "precision": precision, "recall": recall, "f1": f1,
            "reason": reason, **aggregate,
        },
        "latency_ms": latency,
        "limitations": _limitations(manifest["classification"], real),
    }


def _limitations(classification: str, real: bool) -> list[str]:
    evidence = (
        "synthetic manifest checks deterministic pipeline behavior, not real-world recognition evidence"
        if classification == "synthetic"
        else "reviewed manifest labels are bounded evaluation evidence, not independently verified recognition accuracy"
    )
    limitations = [
        evidence,
        "application_total is server stage timing, not HTTP end-to-end latency",
        "invalid responses are excluded from risk metrics and counted in schema_valid_rate",
        "schema-valid not-applicable responses are abstentions: excluded from risk metrics and counted separately",
    ]
    if not real:
        limitations.append("mock mode cannot measure real model recognition")
    return limitations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded SumaiGuard benchmark.")
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / "evaluation" / "goldset_manifest.example.yaml")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        summary = run_benchmark(
            load_manifest(args.manifest), repeat=args.repeat, base_url=args.base_url,
            real=args.real, timeout_seconds=args.timeout_seconds,
        )
    except (BenchmarkError, ValueError, httpx.HTTPError):
        print("benchmark_failed", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
