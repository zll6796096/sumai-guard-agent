from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


_ROOM_NAMES = ("toilet", "bathroom", "genkan", "hallway", "bedroom", "kitchen")
RoomName = Literal["toilet", "bathroom", "genkan", "hallway", "bedroom", "kitchen"]
OntologyRuleKind = Literal["visible_hazard", "expected_feature"]
ActionList = list[str] | tuple[str, ...]


RELATIONSHIP_REQUIREMENTS = {
    "hallway_cord": "intersects",
    "cluttered_path": "obstructs",
    "cluttered_floor": "obstructs",
    "has_floor_clutter": "obstructs",
    "loose_mat": "located_in",
    "has_loose_mat": "located_in",
    "looks_slippery_floor": "located_in",
    "wet_floor": "located_in",
    "kitchen_slip": "located_in",
    "poor_lighting": "located_in",
    "lighting_poor": "located_in",
    "genkan_step": "located_in",
    "bathtub_stepover": "located_in",
    "space_looks_narrow": "obstructs",
    "loose_shoes": "obstructs",
    "reachable_storage_issue": "located_in",
}


class _StrictYamlModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ExpectedFeatureSchema(_StrictYamlModel):
    key: str
    label_ja: str
    missing_risk_type: str
    missing_label_ja: str
    severity: int = Field(ge=1, le=5)
    basis_label_ja: str
    basis_summary_ja: str
    measure_label_ja: str
    family_actions: ActionList
    care_manager_actions: ActionList
    contractor_actions: ActionList


class _VisibleHazardSchema(_StrictYamlModel):
    key: str
    risk_type: str
    label_ja: str
    severity: int = Field(ge=1, le=5)
    basis_label_ja: str
    basis_summary_ja: str
    measure_label_ja: str
    family_actions: ActionList
    care_manager_actions: ActionList
    contractor_actions: ActionList


class _RoomSchema(_StrictYamlModel):
    expected_features: list[_ExpectedFeatureSchema]
    visible_hazards: list[_VisibleHazardSchema]

    @model_validator(mode="after")
    def validate_unique_rule_keys(self) -> "_RoomSchema":
        for collection_name in ("expected_features", "visible_hazards"):
            rules = getattr(self, collection_name)
            keys = [rule.key for rule in rules]
            if len(keys) != len(set(keys)):
                raise ValueError(
                    f"{collection_name} rule keys must be unique within a room"
                )
        return self


class _SourceSchema(_StrictYamlModel):
    title_ja: str
    publisher_ja: str
    url: str


class _FamilyActionPolicySchema(_StrictYamlModel):
    forbidden_words: ActionList
    disclaimer_ja: str


class _ActionTierPolicySchema(_StrictYamlModel):
    disclaimer_ja: str


class _ActionPolicySchema(_StrictYamlModel):
    family: _FamilyActionPolicySchema
    care_manager: _ActionTierPolicySchema
    contractor: _ActionTierPolicySchema


class _OntologyDocumentSchema(_StrictYamlModel):
    ontology_version: str
    schema_version: str
    inference_config_version: str
    relationships: ActionList
    relationship_targets: dict[str, list[str]]
    source_registry: dict[str, _SourceSchema]
    basis_source_map: dict[str, ActionList]
    action_policy: _ActionPolicySchema
    rooms: dict[RoomName, _RoomSchema] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_references(self) -> "_OntologyDocumentSchema":
        source_ids = set(self.source_registry)
        referenced_source_ids = {
            source_id
            for references in self.basis_source_map.values()
            for source_id in references
        }
        unknown_source_ids = referenced_source_ids - source_ids
        if unknown_source_ids:
            raise ValueError("basis_source_map references unknown source IDs")
        rule_basis_labels = {
            rule.basis_label_ja
            for room in self.rooms.values()
            for rule in (*room.expected_features, *room.visible_hazards)
        }
        unregistered_basis_labels = rule_basis_labels - set(self.basis_source_map)
        if unregistered_basis_labels:
            raise ValueError("Rules reference unregistered basis labels")
        visible_observation_keys = {
            rule.key
            for room in self.rooms.values()
            for rule in room.visible_hazards
        }
        if set(self.relationship_targets) != visible_observation_keys:
            raise ValueError(
                "relationship_targets must cover exactly the visible observation keys"
            )
        if any(
            not target.strip()
            for targets in self.relationship_targets.values()
            for target in targets
        ) or any(not targets for targets in self.relationship_targets.values()):
            raise ValueError("relationship_targets must contain non-empty targets")
        return self


class OntologyRiskRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room: str
    key: str
    rule_kind: OntologyRuleKind
    risk_type: str
    label_ja: str
    severity: int = Field(ge=1, le=5)
    basis_label_ja: str
    basis_summary_ja: str
    measure_label_ja: str
    family_actions: tuple[str, ...] = ()
    care_manager_actions: tuple[str, ...] = ()
    contractor_actions: tuple[str, ...] = ()
    expected_feature_key: str | None = None
    evidence_source_ids: tuple[str, ...] = ()


class OntologyRepository:
    def __init__(
        self,
        *,
        ontology_version: str,
        schema_version: str,
        inference_config_version: str,
        relationships: tuple[str, ...],
        relationship_targets: dict[str, tuple[str, ...]],
        source_registry: dict[str, dict[str, str]],
        basis_source_map: dict[str, tuple[str, ...]],
        action_policy: dict[str, dict[str, Any]],
        rooms: dict[str, dict[str, Any]],
    ) -> None:
        if not rooms:
            raise ValueError("Ontology rooms must not be empty")
        self.ontology_version = ontology_version
        self.version = ontology_version
        self.schema_version = schema_version
        self.inference_config_version = inference_config_version
        self.relationships = relationships
        self.relationship_targets = relationship_targets
        self.source_registry = source_registry
        self.basis_source_map = basis_source_map
        self.action_policy = action_policy
        self._rooms = rooms
        self.relationship_requirements = {
            key: predicate
            for key, predicate in RELATIONSHIP_REQUIREMENTS.items()
            if key in self.visible_observation_keys
        }
        if set(self.relationship_requirements) != set(self.visible_observation_keys):
            raise ValueError(
                "Visible observations require exactly one relationship requirement"
            )
        invalid_predicates = set(self.relationship_requirements.values()) - set(
            self.relationships
        )
        if invalid_predicates:
            raise ValueError(
                "Relationship requirements reference unknown predicates: "
                + ", ".join(sorted(invalid_predicates))
            )
        if set(self.relationship_targets) != set(self.visible_observation_keys):
            raise ValueError(
                "relationship_targets must cover exactly the visible observation keys"
            )

    @classmethod
    def load_default(cls) -> "OntologyRepository":
        return cls.load(cls._default_path())

    @classmethod
    def load(cls, path: Path) -> "OntologyRepository":
        raw_document = cls._read_yaml(path)
        normalized_document = cls._normalize_legacy_document(raw_document)
        try:
            document = _OntologyDocumentSchema.model_validate(
                normalized_document, strict=True
            )
        except ValidationError:
            raise ValueError("Invalid ontology YAML") from None
        return cls._from_document(document)

    @classmethod
    def _default_path(cls) -> Path:
        return Path(__file__).resolve().parent / "knowledge_base" / "room_checklists.yaml"

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                document = yaml.safe_load(handle)
        except yaml.YAMLError:
            raise ValueError("Invalid ontology YAML syntax") from None
        if not isinstance(document, dict):
            raise ValueError("Invalid ontology YAML")
        return document

    @classmethod
    def _normalize_legacy_document(
        cls, document: dict[str, Any]
    ) -> dict[str, Any]:
        if "rooms" in document:
            return document
        if not cls._is_legacy_flat_room_mapping(document):
            return document

        default_document = cls._read_yaml(cls._default_path())
        try:
            default_schema = _OntologyDocumentSchema.model_validate(
                default_document, strict=True
            )
        except ValidationError:
            raise ValueError("Invalid ontology YAML") from None
        metadata = default_schema.model_dump(exclude={"rooms"})
        legacy_visible_observation_keys = {
            item["key"]
            for room in document.values()
            for item in room.get("visible_hazards", [])
            if isinstance(item, dict) and isinstance(item.get("key"), str)
        }
        metadata["relationship_targets"] = {
            key: targets
            for key, targets in metadata["relationship_targets"].items()
            if key in legacy_visible_observation_keys
        }
        return {**metadata, "rooms": document}

    @staticmethod
    def _is_legacy_flat_room_mapping(document: dict[str, Any]) -> bool:
        return bool(document) and set(document).issubset(_ROOM_NAMES)

    @classmethod
    def _from_document(
        cls, document: _OntologyDocumentSchema
    ) -> "OntologyRepository":
        return cls(
            ontology_version=document.ontology_version,
            schema_version=document.schema_version,
            inference_config_version=document.inference_config_version,
            relationships=tuple(document.relationships),
            relationship_targets={
                key: tuple(targets)
                for key, targets in document.relationship_targets.items()
            },
            source_registry={
                source_id: source.model_dump()
                for source_id, source in document.source_registry.items()
            },
            basis_source_map={
                basis_label: tuple(source_ids)
                for basis_label, source_ids in document.basis_source_map.items()
            },
            action_policy=document.action_policy.model_dump(),
            rooms={
                room_name: room.model_dump()
                for room_name, room in document.rooms.items()
            },
        )

    @property
    def room_names(self) -> tuple[str, ...]:
        return tuple(self._rooms)

    def room(self, room: str) -> dict[str, Any] | None:
        return self._rooms.get(room)

    @cached_property
    def expected_feature_keys(self) -> tuple[str, ...]:
        return self._derived_keys("expected_features", "key")

    @cached_property
    def visible_observation_keys(self) -> tuple[str, ...]:
        return self._derived_keys("visible_hazards", "key")

    @cached_property
    def risk_types(self) -> tuple[str, ...]:
        visible = self._derived_keys("visible_hazards", "risk_type")
        missing = self._derived_keys("expected_features", "missing_risk_type")
        return tuple(dict.fromkeys((*visible, *missing)))

    def risk_rule(self, room: str, risk_type: str) -> OntologyRiskRule:
        """Legacy compatibility lookup; exact inference paths must use rule()."""
        room_data = self.room(room)
        if room_data is None:
            raise KeyError(room)

        for item in room_data["visible_hazards"]:
            if item["risk_type"] == risk_type:
                return self._rule_from_item(
                    room,
                    item,
                    risk_type,
                    rule_kind="visible_hazard",
                    expected_feature_key=None,
                )
        for item in room_data["expected_features"]:
            if item["missing_risk_type"] == risk_type:
                return self._rule_from_item(
                    room,
                    item,
                    risk_type,
                    rule_kind="expected_feature",
                    expected_feature_key=item["key"],
                )
        raise KeyError((room, risk_type))

    def rule(
        self, room: str, ontology_key: str, rule_kind: OntologyRuleKind
    ) -> OntologyRiskRule:
        room_data = self.room(room)
        if room_data is None:
            raise KeyError(room)
        if rule_kind == "visible_hazard":
            collection = room_data["visible_hazards"]
            risk_field = "risk_type"
            expected_feature_key = None
        else:
            collection = room_data["expected_features"]
            risk_field = "missing_risk_type"
            expected_feature_key = ontology_key
        for item in collection:
            if item["key"] == ontology_key:
                return self._rule_from_item(
                    room,
                    item,
                    item[risk_field],
                    rule_kind=rule_kind,
                    expected_feature_key=expected_feature_key,
                )
        raise KeyError((room, ontology_key, rule_kind))

    def required_predicate(self, observation_key: str) -> str:
        return self.relationship_requirements[observation_key]

    def required_targets(self, observation_key: str) -> tuple[str, ...]:
        return self.relationship_targets[observation_key]

    @cached_property
    def visible_region_keys(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    target
                    for targets in self.relationship_targets.values()
                    for target in targets
                }
            )
        )

    def _derived_keys(self, collection_name: str, key_name: str) -> tuple[str, ...]:
        values = [
            item[key_name]
            for room_data in self._rooms.values()
            for item in room_data[collection_name]
        ]
        return tuple(dict.fromkeys(values))

    def _rule_from_item(
        self,
        room: str,
        item: dict[str, Any],
        risk_type: str,
        rule_kind: OntologyRuleKind,
        expected_feature_key: str | None,
    ) -> OntologyRiskRule:
        basis_label = item["basis_label_ja"]
        return OntologyRiskRule(
            room=room,
            key=item["key"],
            rule_kind=rule_kind,
            risk_type=risk_type,
            label_ja=item["missing_label_ja"]
            if expected_feature_key is not None
            else item["label_ja"],
            severity=item["severity"],
            basis_label_ja=basis_label,
            basis_summary_ja=item["basis_summary_ja"],
            measure_label_ja=item["measure_label_ja"],
            family_actions=self._actions(item, "family_actions"),
            care_manager_actions=self._actions(item, "care_manager_actions"),
            contractor_actions=self._actions(item, "contractor_actions"),
            expected_feature_key=expected_feature_key,
            evidence_source_ids=self.basis_source_map[basis_label],
        )

    @staticmethod
    def _actions(item: dict[str, Any], key: str) -> tuple[str, ...]:
        actions = item[key]
        if not isinstance(actions, (list, tuple)):
            raise ValueError(f"Validated action collection {key} is not a sequence")
        return tuple(actions)
