from __future__ import annotations

from copy import deepcopy
import importlib.util
import os
from pathlib import Path
from typing import Callable

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "benchmark_pipeline.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("benchmark_pipeline", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "ontology_text",
    [
        None,
        (
            'ontology_version: "1.0.0"\n'
            'schema_version: "2.1.0"\n'
            'inference_config_version: "1.0.5"\n'
            "rooms: [not-a-mapping]\n"
        ),
        "ontology_version: [\n",
    ],
)
def test_module_import_fails_closed_for_invalid_ontology_contract(
    tmp_path: Path,
    ontology_text: str | None,
) -> None:
    script_path = tmp_path / "scripts" / "benchmark_pipeline.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text(SCRIPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    if ontology_text is not None:
        ontology_path = (
            tmp_path
            / "apps"
            / "sumai_agent"
            / "app"
            / "knowledge_base"
            / "room_checklists.yaml"
        )
        ontology_path.parent.mkdir(parents=True)
        ontology_path.write_text(ontology_text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "benchmark_pipeline_invalid_ontology",
        script_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)

    with pytest.raises(ValueError, match="invalid_ontology_contract"):
        spec.loader.exec_module(module)


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
        assert ("/" + "Users/") not in case["image"]
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
            benchmark.read_approved_image(Path(*benchmark.SAMPLE_IMAGE_COMPONENTS) / fake_image.name)
    finally:
        fake_image.unlink(missing_ok=True)


def test_safe_image_read_detects_inode_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    benchmark = _load_module()
    target = benchmark.SAMPLE_IMAGE_ROOT / "benchmark_replace_target.png"
    replacement = benchmark.SAMPLE_IMAGE_ROOT / "benchmark_replace_source.png"
    sample = benchmark.SAMPLE_IMAGE_ROOT / "hallway_sample.png"
    target.write_bytes(sample.read_bytes())
    replacement.write_bytes(sample.read_bytes())
    monkeypatch.setattr(benchmark, "TRUSTED_REPO_ROOT_ID", (-1, -1))
    try:
        with pytest.raises(ValueError):
            benchmark.read_approved_image(Path(*benchmark.SAMPLE_IMAGE_COMPONENTS) / target.name)
    finally:
        target.unlink(missing_ok=True)
        replacement.unlink(missing_ok=True)


def test_safe_image_read_rejects_intermediate_symlink(monkeypatch: pytest.MonkeyPatch) -> None:
    benchmark = _load_module()
    linked_dir = benchmark.SAMPLE_IMAGE_ROOT / "benchmark_linked_dir"
    linked_dir.unlink(missing_ok=True)
    linked_dir.symlink_to(benchmark.SAMPLE_IMAGE_ROOT, target_is_directory=True)
    components = (*benchmark.SAMPLE_IMAGE_COMPONENTS, "benchmark_linked_dir")
    monkeypatch.setattr(benchmark, "SAMPLE_IMAGE_COMPONENTS", components)
    try:
        with pytest.raises(ValueError):
            benchmark.read_approved_image(Path(*components) / "hallway_sample.png")
    finally:
        linked_dir.unlink(missing_ok=True)


def test_safe_image_read_fails_closed_for_trusted_root_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    benchmark = _load_module()
    monkeypatch.setattr(benchmark, "TRUSTED_REPO_ROOT_ID", (-1, -1))
    with pytest.raises(ValueError):
        benchmark.read_approved_image(Path(*benchmark.SAMPLE_IMAGE_COMPONENTS) / "hallway_sample.png")


def test_safe_image_read_closes_directory_fds(monkeypatch: pytest.MonkeyPatch) -> None:
    benchmark = _load_module()
    closed: list[int] = []
    real_close = os.close

    def recording_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(benchmark.os, "close", recording_close)
    assert benchmark.read_approved_image(Path(*benchmark.SAMPLE_IMAGE_COMPONENTS) / "hallway_sample.png")
    assert len(closed) >= len(benchmark.SAMPLE_IMAGE_COMPONENTS)


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
        "display_bbox": None,
        "evidence_source_ids": ["E1"], "evidence_ja": "床に見えます。",
        "basis_label_ja": "転倒予防", "basis_summary_ja": "通路を空けます。",
        "needs_human_confirmation": False,
        "ontology_key": "hallway_cord",
        "ontology_rule_kind": "visible_hazard",
    }
    action = {
        "id": "A1", "risk_id": "R1", "tier": "FAMILY_NO_COST", "title_ja": "整理",
        "description_ja": "コードを寄せます。", "why_ja": "つまずきを減らします。",
        "cost_level": "ZERO", "requires_professional": False, "disclaimer_ja": "確認してください。",
    }
    resolved_findings = [finding] if findings is None else findings
    return {
        "analysis_id": "opaque-id", "room_type": "hallway",
        "overall_risk_level": "medium" if resolved_findings else "low",
        "findings": resolved_findings,
        "confirmation_items": [],
        "action_plan": {
            "family_no_cost": [action] if resolved_findings else [],
            "care_manager_purchase": [], "contractor_construction": [],
        },
        "annotated_image_base64": "aGVsbG8=", "improvement_image_base64": "aGVsbG8=",
        "risk_summary_markdown": "summary", "confirmation_items_markdown": "confirmations",
        "family_actions_markdown": "family",
        "care_manager_actions_markdown": "care", "contractor_actions_markdown": "contractor",
        "disclaimer_ja": "POC", "mode": "mock", "is_home_environment": True,
        "is_not_applicable": False, "model": "N/A",
        "not_applicable_reason_ja": None,
        "result_key": "b" * 64, "semantic_hash": "a" * 64,
        "schema_version": "2.1.0", "ontology_version": "1.0.1",
        "preprocess_version": "1.0.0", "inference_config_version": "1.0.6",
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
    malformed.pop("confirmation_items")
    assert benchmark.validate_response_schema(malformed) is False
    for invalid_value in (None, 42, ""):
        malformed = deepcopy(payload)
        malformed["confirmation_items_markdown"] = invalid_value
        assert benchmark.validate_response_schema(malformed) is False
    malformed = deepcopy(payload)
    malformed.pop("confirmation_items_markdown")
    assert benchmark.validate_response_schema(malformed) is False
    malformed = deepcopy(payload)
    malformed.pop("not_applicable_reason_ja")
    assert benchmark.validate_response_schema(malformed) is False
    malformed = deepcopy(payload)
    malformed["not_applicable_reason_ja"] = 42
    assert benchmark.validate_response_schema(malformed) is False
    malformed = deepcopy(payload)
    malformed.pop("is_not_applicable")
    assert benchmark.validate_response_schema(malformed) is False
    malformed = deepcopy(payload)
    malformed["is_not_applicable"] = "false"
    assert benchmark.validate_response_schema(malformed) is False
    malformed = deepcopy(payload)
    malformed["stage_timings_ms"]["total"] = True  # type: ignore[index]
    assert benchmark.validate_response_schema(malformed) is False
    payload["stage_timings_ms"].pop("total")  # type: ignore[index]
    assert benchmark.validate_response_schema(payload) is False


@pytest.mark.parametrize(
    "bbox",
    [
        {"x": 0.1, "y": 0.1, "w": 0.0, "h": 0.2},
        {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.0},
        {"x": 0.8, "y": 0.1, "w": 0.3, "h": 0.2},
        {"x": 0.1, "y": 0.8, "w": 0.2, "h": 0.3},
    ],
)
def test_schema_helper_rejects_zero_area_and_out_of_frame_bbox(
    bbox: dict[str, float],
) -> None:
    benchmark = _load_module()
    payload = _valid_payload()
    payload["findings"][0]["bbox"] = bbox  # type: ignore[index]

    assert benchmark.validate_response_schema(payload) is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda finding: finding.update({"ontology_rule_kind": "expected_feature"}),
        lambda finding: finding.pop("ontology_key"),
        lambda finding: finding.update({"ontology_key": ""}),
        lambda finding: finding.pop("ontology_rule_kind"),
        lambda finding: finding.pop("display_bbox"),
        lambda finding: finding.update({"unexpected": "field"}),
    ],
)
def test_finding_schema_is_exact_and_visible_only(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    benchmark = _load_module()
    payload = _valid_payload()
    finding = payload["findings"][0]  # type: ignore[index]
    mutate(finding)

    assert benchmark.validate_response_schema(payload) is False


def test_findings_must_match_room_scoped_visible_ontology_identity() -> None:
    benchmark = _load_module()
    assert benchmark.validate_response_schema(_valid_payload()) is True

    for ontology_key, risk_type in (
        ("sufficient_lighting", "poor_lighting"),
        ("unknown_hallway_key", "hallway_cord"),
        ("kitchen_slip", "kitchen_slip"),
        ("hallway_cord", "cluttered_path"),
    ):
        payload = _valid_payload()
        payload["findings"][0].update({  # type: ignore[index]
            "ontology_key": ontology_key,
            "risk_type": risk_type,
        })
        assert benchmark.validate_response_schema(payload) is False


def test_action_schema_rejects_extra_fields() -> None:
    benchmark = _load_module()
    payload = _valid_payload()
    payload["action_plan"]["family_no_cost"][0]["unexpected"] = "field"  # type: ignore[index]

    assert benchmark.validate_response_schema(payload) is False


def test_benchmark_loads_family_forbidden_words_from_ontology() -> None:
    benchmark = _load_module()

    assert set(benchmark.FAMILY_FORBIDDEN_WORDS) == {
        "購入",
        "レンタル",
        "工事",
        "施工",
        "設置を依頼",
        "専門",
    }


@pytest.mark.parametrize("field", ["title_ja", "description_ja", "why_ja"])
@pytest.mark.parametrize(
    "forbidden_word",
    ["購入", "レンタル", "工事", "施工", "設置を依頼", "専門"],
)
def test_benchmark_rejects_family_forbidden_words_in_all_action_text(
    field: str,
    forbidden_word: str,
) -> None:
    benchmark = _load_module()
    payload = _valid_payload()
    payload["action_plan"]["family_no_cost"][0][field] = (  # type: ignore[index]
        f"{forbidden_word}する"
    )

    assert benchmark.validate_response_schema(payload) is False


@pytest.mark.parametrize(
    ("severity", "overall_risk_level"),
    [
        (1, "medium"),
        (2, "low"),
        (3, "high"),
        (4, "medium"),
        (5, "medium"),
    ],
)
def test_overall_risk_level_must_match_max_finding_severity(
    severity: int,
    overall_risk_level: str,
) -> None:
    benchmark = _load_module()
    payload = _valid_payload()
    payload["findings"][0]["severity"] = severity  # type: ignore[index]
    payload["overall_risk_level"] = overall_risk_level

    assert benchmark.validate_response_schema(payload) is False


def test_empty_findings_require_low_overall_risk() -> None:
    benchmark = _load_module()
    payload = _valid_payload(findings=[])
    payload["overall_risk_level"] = "medium"

    assert benchmark.validate_response_schema(payload) is False


def test_finding_ids_must_be_canonical_and_follow_response_order() -> None:
    benchmark = _load_module()
    noncanonical = _valid_payload()
    noncanonical["findings"][0]["id"] = "risk-1"  # type: ignore[index]
    noncanonical["action_plan"]["family_no_cost"][0]["risk_id"] = "risk-1"  # type: ignore[index]
    assert benchmark.validate_response_schema(noncanonical) is False

    out_of_order = _valid_payload()
    first = deepcopy(out_of_order["findings"][0])  # type: ignore[index]
    second = deepcopy(first)
    second["id"] = "R2"
    out_of_order["findings"] = [second, first]
    assert benchmark.validate_response_schema(out_of_order) is False


def test_response_versions_must_match_current_benchmark_contract() -> None:
    benchmark = _load_module()
    assert benchmark.validate_response_schema(_valid_payload()) is True

    for field, stale_value in (
        ("schema_version", "2.0.0"),
        ("ontology_version", "arbitrary"),
        ("preprocess_version", "0.9.0"),
        ("inference_config_version", "1.0.4"),
    ):
        payload = _valid_payload()
        payload[field] = stale_value
        assert benchmark.validate_response_schema(payload) is False


def test_not_applicable_response_requires_empty_findings_actions_and_reason() -> None:
    benchmark = _load_module()
    payload = _valid_payload(findings=[])
    payload["is_not_applicable"] = True
    payload["room_type"] = "auto"
    payload["overall_risk_level"] = "low"
    payload["not_applicable_reason_ja"] = "写真から確認対象の部屋を特定できません。"

    assert benchmark.validate_response_schema(payload) is True

    with_findings = deepcopy(payload)
    with_findings["findings"] = _valid_payload()["findings"]
    assert benchmark.validate_response_schema(with_findings) is False

    with_action = deepcopy(payload)
    with_action["action_plan"]["family_no_cost"] = _valid_payload()["action_plan"]["family_no_cost"]
    assert benchmark.validate_response_schema(with_action) is False

    with_confirmation = deepcopy(payload)
    with_confirmation["confirmation_items"] = [_valid_confirmation_item()]
    assert benchmark.validate_response_schema(with_confirmation) is False

    without_reason = deepcopy(payload)
    without_reason["not_applicable_reason_ja"] = ""
    assert benchmark.validate_response_schema(without_reason) is False

    non_low = deepcopy(payload)
    non_low["overall_risk_level"] = "medium"
    assert benchmark.validate_response_schema(non_low) is False

    known_room = deepcopy(payload)
    known_room["room_type"] = "hallway"
    assert benchmark.validate_response_schema(known_room) is False


def _valid_confirmation_item() -> dict[str, object]:
    return {
        "id": "C1",
        "feature_key": "has_handrail",
        "label_ja": "手すり",
        "description_ja": "この写真では手すりを確認できませんでした。",
        "confidence": 0.82,
        "evidence_source_ids": ["MHLW_WELFARE_HOUSING"],
        "basis_label_ja": "写真で確認できる範囲",
        "basis_summary_ja": "写真だけでは実際の有無を判断できません。",
        "needs_human_confirmation": True,
    }


def test_confirmation_only_applicable_response_is_schema_valid() -> None:
    benchmark = _load_module()
    payload = _valid_payload(findings=[])
    payload.update({
        "room_type": "toilet",
        "overall_risk_level": "low",
        "confirmation_items": [_valid_confirmation_item()],
    })

    assert benchmark.validate_response_schema(payload) is True


@pytest.mark.parametrize("feature_key", ["has_handrail", "invented_device"])
def test_confirmation_must_match_room_expected_ontology(feature_key: str) -> None:
    benchmark = _load_module()
    payload = _valid_payload(findings=[])
    confirmation = _valid_confirmation_item()
    confirmation["feature_key"] = feature_key
    payload.update({
        "room_type": "hallway",
        "overall_risk_level": "low",
        "confirmation_items": [confirmation],
    })

    assert benchmark.validate_response_schema(payload) is False


def test_confirmation_ids_must_be_canonical_and_follow_response_order() -> None:
    benchmark = _load_module()
    noncanonical = _valid_payload(findings=[])
    noncanonical.update({
        "room_type": "toilet",
        "overall_risk_level": "low",
        "confirmation_items": [_valid_confirmation_item()],
    })
    noncanonical["confirmation_items"][0]["id"] = "confirmation-1"  # type: ignore[index]
    assert benchmark.validate_response_schema(noncanonical) is False

    out_of_order = _valid_payload(findings=[])
    first = _valid_confirmation_item()
    second = deepcopy(first)
    second.update({
        "id": "C2",
        "feature_key": "has_emergency_call_button",
    })
    out_of_order.update({
        "room_type": "toilet",
        "overall_risk_level": "low",
        "confirmation_items": [second, first],
    })
    assert benchmark.validate_response_schema(out_of_order) is False


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: item.pop("feature_key"),
        lambda item: item.update({"confidence": True}),
        lambda item: item.update({"evidence_source_ids": [""]}),
        lambda item: item.update({"needs_human_confirmation": False}),
        lambda item: item.update({"bbox": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}}),
        lambda item: item.update({"severity": 3}),
        lambda item: item.update({"risk_type": "toilet_missing_handrail"}),
        lambda item: item.update({"actions": []}),
    ],
)
def test_confirmation_item_schema_is_strict(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    benchmark = _load_module()
    payload = _valid_payload(findings=[])
    payload.update({
        "room_type": "toilet",
        "overall_risk_level": "low",
        "confirmation_items": [_valid_confirmation_item()],
    })
    confirmation_item = payload["confirmation_items"][0]  # type: ignore[index]
    mutate(confirmation_item)

    assert benchmark.validate_response_schema(payload) is False


def test_applicable_response_cannot_carry_a_neutral_reason() -> None:
    benchmark = _load_module()
    payload = _valid_payload()
    payload["not_applicable_reason_ja"] = "写真から確認対象の部屋を特定できません。"

    assert benchmark.validate_response_schema(payload) is False
    assert benchmark.validate_response_schema(_valid_payload()) is True

    false_non_home = _valid_payload()
    false_non_home["is_home_environment"] = False
    assert benchmark.validate_response_schema(false_non_home) is False

    false_auto = _valid_payload()
    false_auto["room_type"] = "auto"
    assert benchmark.validate_response_schema(false_auto) is False

    false_blank_reason = _valid_payload()
    false_blank_reason["not_applicable_reason_ja"] = ""
    assert benchmark.validate_response_schema(false_blank_reason) is False


def test_action_plan_semantics_require_tiers_unique_ids_and_known_risks() -> None:
    benchmark = _load_module()
    for mutation in (
        lambda response: response["action_plan"]["family_no_cost"][0].update({"tier": "CARE_MANAGER_PURCHASE"}),
        lambda response: response["action_plan"]["family_no_cost"][0].update({"risk_id": "missing"}),
        lambda response: response["action_plan"]["family_no_cost"][0].update({"id": "A1"}) or response["action_plan"]["care_manager_purchase"].append(deepcopy(response["action_plan"]["family_no_cost"][0])),
        lambda response: response["findings"].append(deepcopy(response["findings"][0])),
    ):
        malformed = _valid_payload()
        mutation(malformed)
        assert benchmark.validate_response_schema(malformed) is False


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


class _PayloadSequenceClient(_ValidClient):
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        super().__init__()
        self._payloads = [deepcopy(payload) for payload in payloads]

    def post(self, _url: str, **kwargs: object) -> _Response:
        self.analyze_calls += 1
        self.post_kwargs = kwargs
        assert self._payloads, "test client received more requests than expected"
        return _Response(200, self._payloads.pop(0))


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
        "available": False, "precision": None, "recall": None, "f1": None,
        "reason": "no_schema_valid_applicable_responses", "tp": 0, "fp": 0, "fn": 0,
    }


def test_invalid_applicability_reason_does_not_enter_metrics() -> None:
    benchmark = _load_module()
    client = _ValidClient()

    def invalid_post(_url: str, **_kwargs: object) -> _Response:
        payload = _valid_payload()
        payload["not_applicable_reason_ja"] = 42
        return _Response(200, payload)

    client.post = invalid_post  # type: ignore[method-assign]
    summary = benchmark.run_benchmark(
        {"version": "1", "classification": "synthetic", "cases": [{
            "id": "hallway", "image": "apps/sumai_web/assets/samples/hallway_sample.png",
            "room_hint": "hallway", "expected_risk_types": ["hallway_cord"],
        }]},
        repeat=1, base_url="http://test", real=False, timeout_seconds=1,
        client_factory=lambda **_kwargs: client,
    )
    assert summary["schema_valid_count"] == 0
    assert summary["risk_metrics"]["available"] is False


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
        "available": True, "precision": 1.0, "recall": 1.0, "f1": 1.0,
        "reason": None, "tp": 0, "fp": 0, "fn": 0,
    }


def test_not_applicable_empty_gold_response_is_schema_valid_but_not_risk_scored() -> None:
    benchmark = _load_module()
    not_applicable = _valid_payload(findings=[])
    not_applicable.update({
        "is_not_applicable": True,
        "room_type": "auto",
        "overall_risk_level": "low",
        "not_applicable_reason_ja": "写真から確認対象の部屋を特定できません。",
    })
    client = _PayloadSequenceClient([not_applicable])

    summary = benchmark.run_benchmark(
        {"version": "1", "classification": "synthetic", "cases": [{
            "id": "empty", "image": "apps/sumai_web/assets/samples/hallway_sample.png",
            "room_hint": "hallway", "expected_risk_types": [],
        }]},
        repeat=1, base_url="http://test", real=False, timeout_seconds=1,
        client_factory=lambda **_kwargs: client,
    )

    assert summary["schema_valid_count"] == 1
    assert summary["scored_applicable_response_count"] == 0
    assert summary["scored_applicable_response_coverage"] == 0.0
    assert summary["abstained_not_applicable_response_count"] == 1
    assert summary["risk_metrics"] == {
        "available": False, "precision": None, "recall": None, "f1": None,
        "reason": "all_schema_valid_responses_not_applicable", "tp": 0, "fp": 0, "fn": 0,
    }


def test_mixed_applicability_scores_only_applicable_responses_and_reports_coverage() -> None:
    benchmark = _load_module()
    not_applicable = _valid_payload(findings=[])
    not_applicable.update({
        "is_not_applicable": True,
        "room_type": "auto",
        "overall_risk_level": "low",
        "not_applicable_reason_ja": "写真から確認対象の部屋を特定できません。",
    })
    client = _PayloadSequenceClient([_valid_payload(), not_applicable])

    summary = benchmark.run_benchmark(
        {"version": "1", "classification": "synthetic", "cases": [
            {
                "id": "hallway", "image": "apps/sumai_web/assets/samples/hallway_sample.png",
                "room_hint": "hallway", "expected_risk_types": ["hallway_cord"],
            },
            {
                "id": "abstained", "image": "apps/sumai_web/assets/samples/hallway_sample.png",
                "room_hint": "hallway", "expected_risk_types": [],
            },
        ]},
        repeat=1, base_url="http://test", real=False, timeout_seconds=1,
        client_factory=lambda **_kwargs: client,
    )

    assert summary["schema_valid_count"] == 2
    assert summary["scored_applicable_response_count"] == 1
    assert summary["scored_applicable_response_coverage"] == 0.5
    assert summary["abstained_not_applicable_response_count"] == 1
    assert summary["risk_metrics"] == {
        "available": True, "precision": 1.0, "recall": 1.0, "f1": 1.0,
        "reason": None, "tp": 1, "fp": 0, "fn": 0,
    }


@pytest.mark.parametrize(
    "field, value",
    [("tier", "CARE_MANAGER_PURCHASE"), ("risk_id", "missing")],
)
def test_invalid_action_semantics_do_not_enter_metrics(field: str, value: str) -> None:
    benchmark = _load_module()
    client = _ValidClient()

    def invalid_post(_url: str, **_kwargs: object) -> _Response:
        payload = _valid_payload()
        payload["action_plan"]["family_no_cost"][0][field] = value  # type: ignore[index]
        return _Response(200, payload)

    client.post = invalid_post  # type: ignore[method-assign]
    summary = benchmark.run_benchmark(
        {"version": "1", "classification": "synthetic", "cases": [{
            "id": "hallway", "image": "apps/sumai_web/assets/samples/hallway_sample.png",
            "room_hint": "hallway", "expected_risk_types": ["hallway_cord"],
        }]},
        repeat=1, base_url="http://test", real=False, timeout_seconds=1,
        client_factory=lambda **_kwargs: client,
    )
    assert summary["schema_valid_count"] == 0
    assert summary["risk_metrics"]["available"] is False


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
