#!/usr/bin/env python3
"""Bounded, local evaluation runner for SumaiGuard response and risk contracts."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOM_HINTS = {"genkan", "hallway", "bathroom", "toilet", "bedroom", "kitchen", "auto"}
STAGE_TIMING_KEYS = {
    "intake", "memo_lookup", "vision", "ontology", "render", "report", "serialize", "total",
}
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class BenchmarkError(ValueError):
    """A stable, non-sensitive benchmark failure code."""


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
    if not isinstance(relative_path, str) or not relative_path or Path(relative_path).is_absolute():
        raise ValueError("unsafe_image_path")
    candidate = REPO_ROOT / relative_path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve())
    except (OSError, ValueError):
        raise ValueError("unsafe_image_path") from None
    if not resolved.is_file():
        raise ValueError("unsafe_image_path")
    return resolved


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
        resolve_image_path(image)
        ids.add(case_id)
        checked.append({"id": case_id, "image": image, "room_hint": room_hint, "expected_risk_types": expected})
    return {"version": loaded["version"], "classification": loaded["classification"], "cases": checked}


def validate_response_schema(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    if not isinstance(payload.get("analysis_id"), str) or not isinstance(payload.get("room_type"), str):
        return False
    if not isinstance(payload.get("action_plan"), dict) or not HEX_64.fullmatch(str(payload.get("result_key", ""))):
        return False
    if not HEX_64.fullmatch(str(payload.get("semantic_hash", ""))):
        return False
    findings = payload.get("findings")
    if not isinstance(findings, list) or not all(isinstance(item, dict) and isinstance(item.get("risk_type"), str) for item in findings):
        return False
    stages = payload.get("stage_timings_ms")
    return isinstance(stages, dict) and set(stages) == STAGE_TIMING_KEYS and all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in stages.values()
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
    with client_factory(timeout=httpx.Timeout(timeout_seconds)) as client:
        if real and not _real_status_is_strict(client.get(f"{base_url}/status")):
            raise BenchmarkError("real_status_gate_failed")
        for _ in range(repeat):
            for case in manifest["cases"]:
                image_path = resolve_image_path(case["image"])
                started = time.monotonic()
                with image_path.open("rb") as image_file:
                    response = client.post(
                        f"{base_url}/analyze",
                        data={"room_hint": case["room_hint"], "mock": "false" if real else "true"},
                        files={"image": (image_path.name, image_file.read(), "image/png")},
                    )
                wall_samples.append(round((time.monotonic() - started) * 1000, 3))
                try:
                    payload = response.json()
                except (ValueError, TypeError):
                    continue
                if response.status_code != 200 or not validate_response_schema(payload):
                    continue
                schema_valid_count += 1
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
        "risk_metrics": {"precision": precision, "recall": recall, "f1": f1, **aggregate},
        "latency_ms": latency,
        "limitations": [
            "synthetic manifest checks deterministic pipeline behavior, not real-world recognition evidence",
            "application_total is server stage timing, not HTTP end-to-end latency",
            "invalid responses are excluded from risk metrics and counted in schema_valid_rate",
        ],
    }


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
