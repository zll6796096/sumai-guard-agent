from __future__ import annotations

from copy import deepcopy
import importlib.util
import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "benchmark_pipeline.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("benchmark_pipeline", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_percentile_uses_nearest_rank_and_rejects_bad_samples() -> None:
    benchmark = _load_module()
    assert benchmark.percentile([1, 2, 3, 4], 0.50) == 2
    assert benchmark.percentile([1, 2, 3, 4], 0) == 1
    assert benchmark.percentile([1, 2, 3, 4], 1) == 4
    with pytest.raises(ValueError):
        benchmark.percentile([], 0.5)
    with pytest.raises(ValueError):
        benchmark.percentile([1, float("inf")], 0.5)


def test_precision_recall_f1_is_predicted_then_expected_with_empty_boundaries() -> None:
    benchmark = _load_module()
    assert benchmark.precision_recall_f1({"a", "b"}, {"b", "c"}) == {
        "precision": 0.5, "recall": 0.5, "f1": 0.5, "tp": 1, "fp": 1, "fn": 1,
    }
    assert benchmark.precision_recall_f1(set(), set()) == {
        "precision": 1.0, "recall": 1.0, "f1": 1.0, "tp": 0, "fp": 0, "fn": 0,
    }
    assert benchmark.precision_recall_f1(set(), {"a"})["precision"] == 0.0
    assert benchmark.precision_recall_f1(set(), {"a"})["recall"] == 0.0


def test_example_manifest_is_synthetic_and_uses_only_safe_relative_paths() -> None:
    benchmark = _load_module()
    manifest = benchmark.load_manifest(REPO_ROOT / "evaluation" / "goldset_manifest.example.yaml")
    assert manifest["classification"] == "synthetic"
    assert [case["expected_risk_types"] for case in manifest["cases"]] == [
        ["hallway_cord"], ["bathroom_slip"], ["genkan_step"],
    ]
    for case in manifest["cases"]:
        assert not case["image"].startswith("/")
        assert "/Users/" not in case["image"]
        assert "private" not in case["image"].lower()


@pytest.mark.parametrize("value", [0, 51])
def test_repeat_validation_rejects_out_of_bounds(value: int) -> None:
    benchmark = _load_module()
    with pytest.raises(ValueError):
        benchmark.validate_repeat(value)


@pytest.mark.parametrize("value", [1, 50])
def test_repeat_validation_accepts_bounded_values(value: int) -> None:
    benchmark = _load_module()
    assert benchmark.validate_repeat(value) == value


def test_manifest_rejects_path_traversal_and_symlink_escape(tmp_path: Path) -> None:
    benchmark = _load_module()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    escape = REPO_ROOT / "evaluation" / "benchmark_escape.png"
    escape.symlink_to(outside)
    try:
        with pytest.raises(ValueError):
            benchmark.resolve_image_path("../../outside.png")
        with pytest.raises(ValueError):
            benchmark.resolve_image_path(str(escape.relative_to(REPO_ROOT)))
    finally:
        escape.unlink(missing_ok=True)


def test_image_resolution_is_limited_to_sample_images_and_rejects_non_images() -> None:
    benchmark = _load_module()
    fake_image = benchmark.SAMPLE_IMAGE_ROOT / "benchmark_fake_text.png"
    fake_image.write_text("not an image", encoding="utf-8")
    try:
        with pytest.raises(ValueError):
            benchmark.resolve_image_path("scripts/benchmark_pipeline.py")
        with pytest.raises(ValueError):
            benchmark.resolve_image_path(".env")
        with pytest.raises(ValueError):
            benchmark.read_approved_image(fake_image)
    finally:
        fake_image.unlink(missing_ok=True)


def test_safe_image_read_detects_inode_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    benchmark = _load_module()
    target = benchmark.SAMPLE_IMAGE_ROOT / "benchmark_replace_target.png"
    replacement = benchmark.SAMPLE_IMAGE_ROOT / "benchmark_replace_source.png"
    sample = benchmark.SAMPLE_IMAGE_ROOT / "hallway_sample.png"
    target.write_bytes(sample.read_bytes())
    replacement.write_bytes(sample.read_bytes())
    real_open = os.open

    def replace_then_open(path: str | bytes | Path, flags: int, mode: int = 0o777) -> int:
        os.replace(replacement, target)
        return real_open(path, flags, mode)

    monkeypatch.setattr(benchmark.os, "open", replace_then_open)
    try:
        with pytest.raises(ValueError):
            benchmark.read_approved_image(target)
    finally:
        target.unlink(missing_ok=True)
        replacement.unlink(missing_ok=True)


def test_manifest_rejects_duplicate_expected_risks(tmp_path: Path) -> None:
    benchmark = _load_module()
    manifest = tmp_path / "duplicate.yaml"
    manifest.write_text(
        """version: \"1\"\nclassification: synthetic\ncases:\n  - id: duplicate\n    image: apps/sumai_web/assets/samples/hallway_sample.png\n    room_hint: hallway\n    expected_risk_types: [hallway_cord, hallway_cord]\n""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        benchmark.load_manifest(manifest)


def _valid_payload(*, findings: list[dict[str, object]] | None = None) -> dict[str, object]:
    finding = {
        "id": "R1", "risk_type": "hallway_cord", "label_ja": "コード",
        "description_ja": "通路上のコードです。", "severity": 3, "confidence": 0.8,
        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
        "evidence_source_ids": ["E1"], "evidence_ja": "床に見えます。",
        "basis_label_ja": "転倒予防", "basis_summary_ja": "通路を空けます。",
        "needs_human_confirmation": False,
    }
    action = {
        "id": "A1", "risk_id": "R1", "tier": "FAMILY_NO_COST", "title_ja": "整理",
        "description_ja": "コードを寄せます。", "why_ja": "つまずきを減らします。",
        "cost_level": "ZERO", "requires_professional": False, "disclaimer_ja": "確認してください。",
    }
    return {
        "analysis_id": "opaque-id", "room_type": "hallway", "overall_risk_level": "medium",
        "findings": [finding] if findings is None else findings,
        "action_plan": {
            "family_no_cost": [action], "care_manager_purchase": [], "contractor_construction": [],
        },
        "annotated_image_base64": "aGVsbG8=", "improvement_image_base64": "aGVsbG8=",
        "risk_summary_markdown": "summary", "family_actions_markdown": "family",
        "care_manager_actions_markdown": "care", "contractor_actions_markdown": "contractor",
        "disclaimer_ja": "POC", "mode": "mock", "is_home_environment": True, "model": "N/A",
        "result_key": "b" * 64, "semantic_hash": "a" * 64,
        "schema_version": "2.0.0", "ontology_version": "1.0.0",
        "preprocess_version": "1.0.0", "inference_config_version": "1.0.0",
        "stage_timings_ms": {
            "intake": 1, "memo_lookup": 0, "vision": 1, "ontology": 1,
            "render": 1, "report": 1, "serialize": 1, "total": 6,
        },
    }


def test_schema_helper_requires_public_shape_without_exposing_sensitive_values() -> None:
    benchmark = _load_module()
    payload = _valid_payload()
    assert benchmark.validate_response_schema(payload) is True
    for field, value in (
        ("analysis_id", "   "),
        ("room_type", "garage"),
    ):
        malformed = deepcopy(payload)
        malformed[field] = value
        assert benchmark.validate_response_schema(malformed) is False
    malformed = deepcopy(payload)
    malformed["findings"][0]["risk_type"] = ""  # type: ignore[index]
    assert benchmark.validate_response_schema(malformed) is False
    malformed = deepcopy(payload)
    malformed["action_plan"] = {}
    assert benchmark.validate_response_schema(malformed) is False
    malformed = deepcopy(payload)
    malformed["stage_timings_ms"]["total"] = True  # type: ignore[index]
    assert benchmark.validate_response_schema(malformed) is False
    payload["stage_timings_ms"].pop("total")  # type: ignore[index]
    assert benchmark.validate_response_schema(payload) is False


class _Response:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code, self._payload = status_code, payload

    def json(self) -> dict[str, object]:
        return self._payload


class _Client:
    def __init__(self, status_payload: dict[str, object]) -> None:
        self.status_payload, self.analyze_calls = status_payload, 0

    def get(self, _url: str) -> _Response:
        return _Response(200, self.status_payload)

    def post(self, _url: str, **_kwargs: object) -> _Response:
        self.analyze_calls += 1
        return _Response(500, {})

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_real_mode_requires_strict_status_provenance_before_analyze() -> None:
    benchmark = _load_module()
    client = _Client({
        "require_real_gemini": True, "has_gemini_api_key": False,
        "mock_mode": False, "mock_allowed": False,
    })
    with pytest.raises(benchmark.BenchmarkError, match="real_status_gate_failed"):
        benchmark.run_benchmark(
            {"version": "1", "classification": "synthetic", "cases": []},
            repeat=1, base_url="http://test", real=True, timeout_seconds=1,
            client_factory=lambda **_kwargs: client,
        )
    assert client.analyze_calls == 0


def test_real_mode_status_gate_rejects_truthy_non_boolean_values() -> None:
    benchmark = _load_module()
    client = _Client({
        "require_real_gemini": 1, "has_gemini_api_key": True,
        "mock_mode": False, "mock_allowed": False,
    })
    with pytest.raises(benchmark.BenchmarkError, match="real_status_gate_failed"):
        benchmark.run_benchmark(
            {"version": "1", "classification": "synthetic", "cases": []},
            repeat=1, base_url="http://test", real=True, timeout_seconds=1,
            client_factory=lambda **_kwargs: client,
        )
    assert client.analyze_calls == 0


class _ValidClient(_Client):
    def __init__(self) -> None:
        super().__init__({})
        self.post_kwargs: dict[str, object] = {}

    def post(self, _url: str, **kwargs: object) -> _Response:
        self.analyze_calls += 1
        self.post_kwargs = kwargs
        return _Response(200, _valid_payload())


def test_mock_runner_sends_mock_param_and_summary_omits_sensitive_response_values() -> None:
    benchmark = _load_module()
    client = _ValidClient()
    summary = benchmark.run_benchmark(
        {
            "version": "1", "classification": "synthetic",
            "cases": [{
                "id": "hallway", "image": "apps/sumai_web/assets/samples/hallway_sample.png",
                "room_hint": "hallway", "expected_risk_types": ["hallway_cord"],
            }],
        },
        repeat=1, base_url="http://test", real=False, timeout_seconds=1,
        client_factory=lambda **_kwargs: client,
    )
    assert client.post_kwargs["data"] == {"room_hint": "hallway", "mock": "true"}
    serialized = __import__("json").dumps(summary)
    for forbidden in ("analysis_id", "result_key", "semantic_hash", "base64", "a" * 64):
        assert forbidden not in serialized


def test_invalid_response_is_excluded_from_schema_and_risk_metrics() -> None:
    benchmark = _load_module()
    client = _ValidClient()
    original_post = client.post

    def invalid_post(url: str, **kwargs: object) -> _Response:
        response = original_post(url, **kwargs)
        response._payload["room_type"] = "garage"
        return response

    client.post = invalid_post  # type: ignore[method-assign]
    summary = benchmark.run_benchmark(
        {
            "version": "1", "classification": "synthetic",
            "cases": [{
                "id": "hallway", "image": "apps/sumai_web/assets/samples/hallway_sample.png",
                "room_hint": "hallway", "expected_risk_types": ["hallway_cord"],
            }],
        },
        repeat=1, base_url="http://test", real=False, timeout_seconds=1,
        client_factory=lambda **_kwargs: client,
    )
    assert summary["schema_valid_count"] == 0
    assert summary["risk_metrics"] == {
        "precision": 1.0, "recall": 1.0, "f1": 1.0, "tp": 0, "fp": 0, "fn": 0,
    }


def test_empty_valid_observation_uses_empty_set_metric_semantics() -> None:
    benchmark = _load_module()
    client = _ValidClient()
    client.post = lambda _url, **_kwargs: _Response(200, _valid_payload(findings=[]))  # type: ignore[method-assign]
    summary = benchmark.run_benchmark(
        {"version": "1", "classification": "synthetic", "cases": [{
            "id": "empty", "image": "apps/sumai_web/assets/samples/hallway_sample.png",
            "room_hint": "hallway", "expected_risk_types": [],
        }]},
        repeat=1, base_url="http://test", real=False, timeout_seconds=1,
        client_factory=lambda **_kwargs: client,
    )
    assert summary["risk_metrics"] == {
        "precision": 1.0, "recall": 1.0, "f1": 1.0, "tp": 0, "fp": 0, "fn": 0,
    }


def test_reviewed_manifest_uses_classification_specific_limitations() -> None:
    benchmark = _load_module()
    client = _ValidClient()
    summary = benchmark.run_benchmark(
        {"version": "1", "classification": "reviewed", "cases": [{
            "id": "reviewed", "image": "apps/sumai_web/assets/samples/hallway_sample.png",
            "room_hint": "hallway", "expected_risk_types": ["hallway_cord"],
        }]},
        repeat=1, base_url="http://test", real=False, timeout_seconds=1,
        client_factory=lambda **_kwargs: client,
    )
    assert any("reviewed" in item for item in summary["limitations"])
    assert any("mock" in item for item in summary["limitations"])
    assert not any("synthetic manifest" in item for item in summary["limitations"])
