from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


_ROOM_NAMES = ("toilet", "bathroom", "genkan", "hallway", "bedroom", "kitchen")
RoomName = Literal["toilet", "bathroom", "genkan", "hallway", "bedroom", "kitchen"]
ActionList = list[str] | tuple[str, ...]


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
            raise ValueError(
                "basis_source_map references unknown source IDs: "
                + ", ".join(sorted(unknown_source_ids))
            )
        rule_basis_labels = {
            rule.basis_label_ja
            for room in self.rooms.values()
            for rule in (*room.expected_features, *room.visible_hazards)
        }
        unregistered_basis_labels = rule_basis_labels - set(self.basis_source_map)
        if unregistered_basis_labels:
            raise ValueError(
                "Rules reference unregistered basis labels: "
                + ", ".join(sorted(unregistered_basis_labels))
            )
        return self


class OntologyRiskRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room: str
    key: str
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
        self.source_registry = source_registry
        self.basis_source_map = basis_source_map
        self.action_policy = action_policy
        self._rooms = rooms

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
        except ValidationError as exc:
            raise ValueError(f"Invalid ontology YAML: {exc}") from exc
        return cls._from_document(document)

    @classmethod
    def _default_path(cls) -> Path:
        return Path(__file__).resolve().parent / "knowledge_base" / "room_checklists.yaml"

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                document = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid ontology YAML syntax: {exc}") from exc
        if not isinstance(document, dict):
            raise ValueError("Ontology root must be a mapping")
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
        except ValidationError as exc:
            raise ValueError(f"Invalid default ontology YAML: {exc}") from exc
        metadata = default_schema.model_dump(exclude={"rooms"})
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
        room_data = self.room(room)
        if room_data is None:
            raise KeyError(room)

        for item in room_data["visible_hazards"]:
            if item["risk_type"] == risk_type:
                return self._rule_from_item(room, item, risk_type, expected_feature_key=None)
        for item in room_data["expected_features"]:
            if item["missing_risk_type"] == risk_type:
                return self._rule_from_item(
                    room,
                    item,
                    risk_type,
                    expected_feature_key=item["key"],
                )
        raise KeyError((room, risk_type))

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
        expected_feature_key: str | None,
    ) -> OntologyRiskRule:
        basis_label = item["basis_label_ja"]
        return OntologyRiskRule(
            room=room,
            key=item["key"],
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
