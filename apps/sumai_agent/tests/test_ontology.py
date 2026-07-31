from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from app.models import BoundingBox, RiskFinding, VisionResult
from app.ontology import OntologyRepository
from app.services.checklist_engine import ChecklistEngine
from app.services.rule_engine import RuleEngine


def test_visible_observation_keys_have_exact_relationship_requirements() -> None:
    ontology = OntologyRepository.load_default()

    assert set(ontology.relationship_requirements) == set(ontology.visible_observation_keys)
    assert set(ontology.relationship_requirements.values()) <= set(ontology.relationships)
    assert ontology.required_targets("hallway_cord") == ("walking_path",)
    assert set(ontology.relationship_targets) == set(ontology.visible_observation_keys)
    assert set(ontology.visible_region_keys) == {
        "floor", "room", "transfer_zone", "walking_path"
    }
    assert ontology.required_predicate("hallway_cord") == "intersects"
    with pytest.raises(KeyError):
        ontology.required_predicate("not_an_observation")
    with pytest.raises(KeyError):
        ontology.required_targets("not_an_observation")


def test_shower_chair_is_an_expected_feature_not_a_visible_hazard() -> None:
    ontology = OntologyRepository.load_default()

    assert "has_shower_chair" in ontology.expected_feature_keys
    assert "no_shower_chair" not in ontology.visible_observation_keys
    assert "no_shower_chair" not in ontology.relationship_requirements


def test_load_rejects_incomplete_relationship_target_coverage(tmp_path: Path) -> None:
    source_path = Path(__file__).resolve().parents[1] / "app" / "knowledge_base" / "room_checklists.yaml"
    document = deepcopy(yaml.safe_load(source_path.read_text(encoding="utf-8")))
    del document["relationship_targets"]["hallway_cord"]
    malformed_path = tmp_path / "missing-relationship-target.yaml"
    malformed_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError) as error:
        OntologyRepository.load(malformed_path)

    assert str(error.value) == "Invalid ontology YAML"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.parametrize(
    "mutate_document",
    [
        lambda document: document.__setitem__(
            "SENSITIVE_ONTOLOGY_FIELD_NAME",
            "SENSITIVE_ONTOLOGY_FIELD_VALUE",
        ),
        lambda document: document["rooms"]["genkan"]["visible_hazards"][0].update(
            {
                "SENSITIVE_RULE_FIELD_NAME": "SENSITIVE_RULE_FIELD_VALUE",
            }
        ),
    ],
)
def test_load_validation_error_is_generic_for_arbitrary_extra_fields(
    tmp_path: Path,
    mutate_document: Callable[[dict[str, Any]], None],
) -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "knowledge_base"
        / "room_checklists.yaml"
    )
    document = deepcopy(yaml.safe_load(source_path.read_text(encoding="utf-8")))
    mutate_document(document)
    malformed_path = tmp_path / "sensitive-extra-field.yaml"
    malformed_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError) as error:
        OntologyRepository.load(malformed_path)

    assert str(error.value) == "Invalid ontology YAML"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_load_yaml_syntax_error_is_generic_without_source_fragment(
    tmp_path: Path,
) -> None:
    malformed_path = tmp_path / "invalid-syntax.yaml"
    malformed_path.write_text(
        "rooms:\n  SENSITIVE_SYNTAX_FRAGMENT: [\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as error:
        OntologyRepository.load(malformed_path)

    assert str(error.value) == "Invalid ontology YAML syntax"
    assert "SENSITIVE_SYNTAX_FRAGMENT" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_load_non_mapping_root_uses_generic_validation_error(
    tmp_path: Path,
) -> None:
    malformed_path = tmp_path / "non-mapping.yaml"
    malformed_path.write_text(
        "- SENSITIVE_ROOT_VALUE\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as error:
        OntologyRepository.load(malformed_path)

    assert str(error.value) == "Invalid ontology YAML"


@pytest.mark.parametrize(
    ("collection", "duplicate_key"),
    [
        ("visible_hazards", "genkan_step"),
        ("expected_features", "has_handrail_or_support"),
    ],
)
def test_load_rejects_duplicate_room_rule_keys_without_leaking_document_content(
    tmp_path: Path,
    collection: str,
    duplicate_key: str,
) -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "knowledge_base"
        / "room_checklists.yaml"
    )
    document = deepcopy(yaml.safe_load(source_path.read_text(encoding="utf-8")))
    rules = document["rooms"]["genkan"][collection]
    duplicate = deepcopy(next(rule for rule in rules if rule["key"] == duplicate_key))
    duplicate["basis_summary_ja"] = "SENSITIVE_ONTOLOGY_DOCUMENT_CONTENT"
    rules.append(duplicate)
    malformed_path = tmp_path / f"duplicate-{collection}.yaml"
    malformed_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError) as error:
        OntologyRepository.load(malformed_path)

    assert str(error.value) == "Invalid ontology YAML"


def test_load_allows_the_same_room_key_across_distinct_rule_kinds(
    tmp_path: Path,
) -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "knowledge_base"
        / "room_checklists.yaml"
    )
    document = deepcopy(yaml.safe_load(source_path.read_text(encoding="utf-8")))
    document["rooms"]["genkan"]["expected_features"][0]["key"] = "genkan_step"
    overlapping_path = tmp_path / "cross-kind-key.yaml"
    overlapping_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    ontology = OntologyRepository.load(overlapping_path)

    assert ontology.rule("genkan", "genkan_step", "visible_hazard").rule_kind == (
        "visible_hazard"
    )
    assert ontology.rule("genkan", "genkan_step", "expected_feature").rule_kind == (
        "expected_feature"
    )


def test_default_ontology_has_the_required_version_and_rooms() -> None:
    ontology = OntologyRepository.load_default()

    assert ontology.ontology_version == "1.0.1"
    assert ontology.version == "1.0.1"
    assert ontology.schema_version == "2.2.0"
    assert ontology.inference_config_version == "1.0.6"
    assert set(ontology.room_names) == {
        "toilet",
        "bathroom",
        "genkan",
        "hallway",
        "bedroom",
        "kitchen",
    }


@pytest.mark.parametrize(
    ("room", "ontology_key", "risk_type"),
    [
        ("toilet", "space_looks_narrow", "toilet_transfer_support"),
        ("toilet", "looks_slippery_floor", "toilet_slip"),
        ("kitchen", "kitchen_slip", "kitchen_slip"),
        ("kitchen", "reachable_storage_issue", "kitchen_unreachable_storage"),
    ],
)
def test_default_ontology_excludes_non_visual_inference_rules(
    room: str,
    ontology_key: str,
    risk_type: str,
) -> None:
    ontology = OntologyRepository.load_default()
    room_data = ontology.room(room)

    assert room_data is not None
    assert ontology_key not in {
        rule["key"] for rule in room_data["visible_hazards"]
    }
    assert risk_type not in {
        rule["risk_type"] for rule in room_data["visible_hazards"]
    }
    assert ontology_key not in ontology.relationship_requirements
    assert ontology_key not in ontology.relationship_targets


def test_explicit_bathroom_wet_floor_remains_a_visible_rule() -> None:
    ontology = OntologyRepository.load_default()

    rule = ontology.rule("bathroom", "wet_floor", "visible_hazard")

    assert rule.risk_type == "bathroom_slip"
    assert ontology.required_predicate("wet_floor") == "located_in"
    assert ontology.required_targets("wet_floor") == ("floor",)


def test_risk_rule_is_scoped_to_its_room() -> None:
    ontology = OntologyRepository.load_default()

    toilet_rule = ontology.risk_rule("toilet", "cluttered_path")
    kitchen_rule = ontology.risk_rule("kitchen", "cluttered_path")

    assert toilet_rule.room == "toilet"
    assert kitchen_rule.room == "kitchen"
    assert toilet_rule.family_actions != kitchen_rule.family_actions


def test_derived_vocabulary_contains_room_observations_and_risks() -> None:
    ontology = OntologyRepository.load_default()

    vocabulary = set(ontology.visible_observation_keys) | set(ontology.expected_feature_keys) | set(ontology.risk_types)
    assert {"hallway_cord", "clear_path", "cluttered_path"} <= vocabulary


def test_basis_sources_are_registered() -> None:
    ontology = OntologyRepository.load_default()

    for source_ids in ontology.basis_source_map.values():
        assert set(source_ids) <= set(ontology.source_registry)


def test_every_rule_basis_label_is_explicitly_registered() -> None:
    ontology = OntologyRepository.load_default()
    rule_basis_labels = {
        item["basis_label_ja"]
        for room_name in ontology.room_names
        for room in (ontology.room(room_name),)
        if room is not None
        for collection in ("expected_features", "visible_hazards")
        for item in room[collection]
    }

    assert rule_basis_labels <= set(ontology.basis_source_map)


def test_load_rejects_rule_without_explicit_basis_registration(tmp_path: Path) -> None:
    source_path = Path(__file__).resolve().parents[1] / "app" / "knowledge_base" / "room_checklists.yaml"
    document = deepcopy(yaml.safe_load(source_path.read_text(encoding="utf-8")))
    basis_label = document["rooms"]["toilet"]["visible_hazards"][0]["basis_label_ja"]
    del document["basis_source_map"][basis_label]
    malformed_path = tmp_path / "missing-basis-registration.yaml"
    malformed_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError) as error:
        OntologyRepository.load(malformed_path)

    assert str(error.value) == "Invalid ontology YAML"


@pytest.mark.parametrize(
    "mutate_document",
    [
        lambda document: document["basis_source_map"].__setitem__(
            "厚労省 福祉用具・住宅改修の考え方に関連",
            ["SENSITIVE_ONTOLOGY_REFERENCE"],
        ),
        lambda document: document["rooms"]["toilet"]["visible_hazards"][0].update(
            {"basis_label_ja": "SENSITIVE_ONTOLOGY_REFERENCE"}
        ),
    ],
)
def test_load_validation_errors_do_not_echo_unknown_reference_content(
    tmp_path: Path,
    mutate_document: Callable[[dict[str, Any]], None],
) -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "knowledge_base"
        / "room_checklists.yaml"
    )
    document = deepcopy(yaml.safe_load(source_path.read_text(encoding="utf-8")))
    mutate_document(document)
    malformed_path = tmp_path / "sensitive-reference.yaml"
    malformed_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError) as error:
        OntologyRepository.load(malformed_path)

    assert str(error.value) == "Invalid ontology YAML"


def test_engines_load_a_custom_ontology_path(tmp_path: Path) -> None:
    source_path = Path(__file__).resolve().parents[1] / "app" / "knowledge_base" / "room_checklists.yaml"
    custom_path = tmp_path / "room_checklists.yaml"
    custom_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    checklist_engine = ChecklistEngine(checklists_path=custom_path)
    rule_engine = RuleEngine(checklists_path=custom_path)

    assert checklist_engine.ontology.room_names == rule_engine.ontology.room_names
    assert rule_engine._find_checklist_item("toilet", "cluttered_path") is not None


def test_engines_load_a_legacy_flat_room_mapping(tmp_path: Path) -> None:
    source_path = Path(__file__).resolve().parents[1] / "app" / "knowledge_base" / "room_checklists.yaml"
    default_document = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    legacy_document = {
        "toilet": default_document["rooms"]["toilet"],
        "kitchen": default_document["rooms"]["kitchen"],
    }
    legacy_path = tmp_path / "legacy_room_checklists.yaml"
    legacy_path.write_text(
        yaml.safe_dump(legacy_document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    checklist_engine = ChecklistEngine(checklists_path=legacy_path)
    visible_finding = RiskFinding(
        id="pending",
        risk_type="cluttered_path",
        label_ja="床の物・動線阻害",
        description_ja="床の物が写真で確認されました。",
        severity=3,
        confidence=0.85,
        bbox=BoundingBox(x=0.1, y=0.2, w=0.15, h=0.6),
        evidence_source_ids=["CAA_FALL_PREVENTION"],
        evidence_ja="写真内の表示範囲に可視の根拠があります。",
        basis_label_ja="消費者庁 転倒予防ポイントに基づく一般注意",
        basis_summary_ja="床や動線上の物はつまずきにつながります。",
        needs_human_confirmation=False,
        ontology_key="has_floor_clutter",
        ontology_rule_kind="visible_hazard",
    )
    findings = checklist_engine.process(
        VisionResult(
            room_type="toilet",
            is_home_environment=True,
            visible_hazards=[visible_finding],
        )
    )
    normalized, actions = RuleEngine(checklists_path=legacy_path).apply(findings, "toilet")

    assert normalized[0].risk_type == "cluttered_path"
    assert actions.family_no_cost


def test_legacy_normalization_default_validation_error_is_generic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "knowledge_base"
        / "room_checklists.yaml"
    )
    default_document = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    legacy_document = {"toilet": default_document["rooms"]["toilet"]}
    legacy_path = tmp_path / "legacy.yaml"
    legacy_path.write_text(
        yaml.safe_dump(legacy_document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    invalid_default = deepcopy(default_document)
    invalid_default["SENSITIVE_DEFAULT_FIELD_NAME"] = "SENSITIVE_DEFAULT_FIELD_VALUE"
    invalid_default_path = tmp_path / "invalid-default.yaml"
    invalid_default_path.write_text(
        yaml.safe_dump(invalid_default, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        OntologyRepository,
        "_default_path",
        classmethod(lambda cls: invalid_default_path),
    )

    with pytest.raises(ValueError) as error:
        OntologyRepository.load(legacy_path)

    assert str(error.value) == "Invalid ontology YAML"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.parametrize(
    "mutate_document",
    [
        lambda document: document["rooms"]["toilet"]["visible_hazards"][0].update(
            {"severty": document["rooms"]["toilet"]["visible_hazards"][0].pop("severity")}
        ),
        lambda document: document["rooms"].__setitem__("toilet", "not-a-room-object"),
        lambda document: document["basis_source_map"].__setitem__(
            "厚労省 福祉用具・住宅改修の考え方に関連", ["UNKNOWN_SOURCE"]
        ),
        lambda document: document["rooms"]["toilet"].__setitem__(
            "visible_hazards", {"not": "a-list"}
        ),
    ],
)
def test_load_rejects_malformed_safety_documents(
    tmp_path: Path, mutate_document: Callable[[dict[str, Any]], None]
) -> None:
    source_path = Path(__file__).resolve().parents[1] / "app" / "knowledge_base" / "room_checklists.yaml"
    document = deepcopy(yaml.safe_load(source_path.read_text(encoding="utf-8")))
    mutate_document(document)
    malformed_path = tmp_path / "malformed.yaml"
    malformed_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError) as error:
        OntologyRepository.load(malformed_path)

    assert str(error.value) == "Invalid ontology YAML"
