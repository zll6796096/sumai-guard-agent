from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from app.models import VisionResult
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
        "floor", "room", "storage", "transfer_zone", "walking_path"
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

    with pytest.raises(ValueError, match="relationship_targets"):
        OntologyRepository.load(malformed_path)


def test_default_ontology_has_the_required_version_and_rooms() -> None:
    ontology = OntologyRepository.load_default()

    assert ontology.ontology_version == "1.0.0"
    assert ontology.version == "1.0.0"
    assert ontology.schema_version == "2.0.0"
    assert ontology.inference_config_version == "1.0.0"
    assert set(ontology.room_names) == {
        "toilet",
        "bathroom",
        "genkan",
        "hallway",
        "bedroom",
        "kitchen",
    }


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

    with pytest.raises(ValueError):
        OntologyRepository.load(malformed_path)


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
    findings = checklist_engine.process(
        VisionResult(
            room_type="toilet",
            is_home_environment=True,
            observations={"has_handrail": False},
            visible_hazards=[],
            missing_safety_features=[],
        )
    )
    normalized, actions = RuleEngine(checklists_path=legacy_path).apply(findings, "toilet")

    assert normalized[0].risk_type == "toilet_missing_handrail"
    assert actions.family_no_cost


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

    with pytest.raises(ValueError):
        OntologyRepository.load(malformed_path)
