from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


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
        version: str,
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
        self.version = version
        self.schema_version = schema_version
        self.inference_config_version = inference_config_version
        self.relationships = relationships
        self.source_registry = source_registry
        self.basis_source_map = basis_source_map
        self.action_policy = action_policy
        self._rooms = rooms

    @classmethod
    def load_default(cls) -> "OntologyRepository":
        path = Path(__file__).resolve().parent / "knowledge_base" / "room_checklists.yaml"
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            raise ValueError("Ontology root must be a mapping")

        raw_rooms = data.get("rooms")
        if not isinstance(raw_rooms, dict):
            raise ValueError("Ontology rooms must be a mapping")

        rooms = {
            str(room_name): room_data
            for room_name, room_data in raw_rooms.items()
            if isinstance(room_data, dict)
        }
        raw_registry = data.get("source_registry", {})
        raw_basis_map = data.get("basis_source_map", {})
        raw_policy = data.get("action_policy", {})
        return cls(
            version=str(data.get("ontology_version", "")),
            schema_version=str(data.get("schema_version", "")),
            inference_config_version=str(data.get("inference_config_version", "")),
            relationships=tuple(str(item) for item in data.get("relationships", [])),
            source_registry={
                str(key): value
                for key, value in raw_registry.items()
                if isinstance(value, dict)
            }
            if isinstance(raw_registry, dict)
            else {},
            basis_source_map={
                str(label): tuple(str(source_id) for source_id in source_ids)
                for label, source_ids in raw_basis_map.items()
                if isinstance(source_ids, list)
            }
            if isinstance(raw_basis_map, dict)
            else {},
            action_policy={
                str(tier): policy
                for tier, policy in raw_policy.items()
                if isinstance(policy, dict)
            }
            if isinstance(raw_policy, dict)
            else {},
            rooms=rooms,
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

        for item in room_data.get("visible_hazards", []):
            if isinstance(item, dict) and item.get("risk_type") == risk_type:
                return self._rule_from_item(room, item, risk_type, expected_feature_key=None)
        for item in room_data.get("expected_features", []):
            if isinstance(item, dict) and item.get("missing_risk_type") == risk_type:
                return self._rule_from_item(
                    room,
                    item,
                    risk_type,
                    expected_feature_key=str(item.get("key", "")),
                )
        raise KeyError((room, risk_type))

    def _derived_keys(self, collection_name: str, key_name: str) -> tuple[str, ...]:
        values: list[str] = []
        for room_data in self._rooms.values():
            for item in room_data.get(collection_name, []):
                if isinstance(item, dict) and isinstance(item.get(key_name), str):
                    values.append(item[key_name])
        return tuple(dict.fromkeys(values))

    def _rule_from_item(
        self,
        room: str,
        item: dict[str, Any],
        risk_type: str,
        expected_feature_key: str | None,
    ) -> OntologyRiskRule:
        basis_label = str(item.get("basis_label_ja", ""))
        return OntologyRiskRule(
            room=room,
            key=str(item.get("key", "")),
            risk_type=risk_type,
            label_ja=str(item.get("missing_label_ja" if expected_feature_key else "label_ja", "")),
            severity=item.get("severity", 1),
            basis_label_ja=basis_label,
            basis_summary_ja=str(item.get("basis_summary_ja", "")),
            measure_label_ja=str(item.get("measure_label_ja", "")),
            family_actions=self._actions(item, "family_actions"),
            care_manager_actions=self._actions(item, "care_manager_actions"),
            contractor_actions=self._actions(item, "contractor_actions"),
            expected_feature_key=expected_feature_key,
            evidence_source_ids=self.basis_source_map.get(basis_label, ()),
        )

    @staticmethod
    def _actions(item: dict[str, Any], key: str) -> tuple[str, ...]:
        actions = item.get(key, [])
        if not isinstance(actions, list):
            return ()
        return tuple(str(action) for action in actions)
