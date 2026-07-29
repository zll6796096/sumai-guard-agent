from __future__ import annotations

import importlib.util
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


def test_schema_helper_requires_public_shape_without_exposing_sensitive_values() -> None:
    benchmark = _load_module()
    payload = {
        "analysis_id": "opaque-id", "room_type": "hallway",
        "findings": [{"risk_type": "hallway_cord"}], "action_plan": {},
        "result_key": "b" * 64, "semantic_hash": "a" * 64,
        "stage_timings_ms": {
            "intake": 1, "memo_lookup": 0, "vision": 1, "ontology": 1,
            "render": 1, "report": 1, "serialize": 1, "total": 6,
        },
    }
    assert benchmark.validate_response_schema(payload) is True
    payload["stage_timings_ms"].pop("total")
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


class _ValidClient(_Client):
    def __init__(self) -> None:
        super().__init__({})
        self.post_kwargs: dict[str, object] = {}

    def post(self, _url: str, **kwargs: object) -> _Response:
        self.analyze_calls += 1
        self.post_kwargs = kwargs
        return _Response(200, {
            "analysis_id": "opaque-id", "room_type": "hallway",
            "findings": [{"risk_type": "hallway_cord"}], "action_plan": {},
            "result_key": "b" * 64, "semantic_hash": "a" * 64,
            "stage_timings_ms": {
                "intake": 1, "memo_lookup": 0, "vision": 1, "ontology": 1,
                "render": 1, "report": 1, "serialize": 1, "total": 6,
            },
        })


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
