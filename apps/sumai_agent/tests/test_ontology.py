from __future__ import annotations

from app.ontology import OntologyRepository


def test_default_ontology_has_the_required_version_and_rooms() -> None:
    ontology = OntologyRepository.load_default()

    assert ontology.version == "1.0.0"
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
