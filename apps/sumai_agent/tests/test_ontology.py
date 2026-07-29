from __future__ import annotations

from pathlib import Path

from app.ontology import OntologyRepository
from app.services.checklist_engine import ChecklistEngine
from app.services.rule_engine import RuleEngine


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


def test_engines_load_a_custom_ontology_path(tmp_path: Path) -> None:
    source_path = Path(__file__).resolve().parents[1] / "app" / "knowledge_base" / "room_checklists.yaml"
    custom_path = tmp_path / "room_checklists.yaml"
    custom_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    checklist_engine = ChecklistEngine(checklists_path=custom_path)
    rule_engine = RuleEngine(checklists_path=custom_path)

    assert checklist_engine.ontology.room_names == rule_engine.ontology.room_names
    assert rule_engine._find_checklist_item("toilet", "cluttered_path") is not None
