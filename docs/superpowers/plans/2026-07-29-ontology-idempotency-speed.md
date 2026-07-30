# SumaiGuard Ontology, Idempotency, and Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make repeated analysis of the same canonical photo semantically stable, derive risks and actions from a versioned ontology in Python, and remove blocking I/O from the vision pipeline without weakening the safety boundary.

**Architecture:** Gemini returns a minimal versioned visual-facts document containing scene state, typed evidence entities, feature observations, and relationships. A typed ontology repository derives room-scoped risks, deterministic Japanese copy, actions, stable IDs, result keys, and semantic hashes; a bounded process-local memo reuses successful semantic results while images are rendered per request. Gemini and web proxy calls use reusable asynchronous clients, while Pillow work runs in worker threads.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, Pillow, PyYAML, google-genai 2.x async client, httpx, pytest.

---

## File Responsibility Map

- `apps/sumai_agent/app/ontology.py`: typed ontology loading, validation, vocabulary, and room-scoped rule lookup.
- `apps/sumai_agent/app/knowledge_base/room_checklists.yaml`: single versioned ontology source.
- `apps/sumai_agent/app/models.py`: public API models plus internal visual-fact models.
- `apps/sumai_agent/app/services/gemini_vision.py`: minimal structured-output schema, async Gemini call, strict parsing, and deterministic mock facts.
- `apps/sumai_agent/app/services/relationship_engine.py`: converts validated visual facts into evidence-backed `RiskFinding` objects.
- `apps/sumai_agent/app/services/canonicalization.py`: pixel digest, result key, stable IDs, ordering, and semantic hash.
- `apps/sumai_agent/app/services/result_memo.py`: bounded TTL memo and in-flight coalescing.
- `apps/sumai_agent/app/services/orchestrator.py`: stage orchestration, memo integration, thread offloading, timings, and response assembly.
- `apps/sumai_agent/app/services/rule_engine.py`: deterministic action policy using room-scoped ontology rules.
- `apps/sumai_agent/app/services/checklist_engine.py`: compatibility adapter for existing `VisionResult` callers during migration.
- `apps/sumai_agent/app/services/visual_renderer.py`: preserve evidence bbox and use optional display bbox only for drawing.
- `apps/sumai_agent/app/main.py`: serialization timing and sanitized stage logging.
- `apps/sumai_web/app.py`: reusable async backend proxy.
- `apps/sumai_agent/tests/test_ontology.py`: ontology contract and room-scoped lookup.
- `apps/sumai_agent/tests/test_visual_facts.py`: minimal Gemini facts schema and parser.
- `apps/sumai_agent/tests/test_relationship_engine.py`: relationship and missing-feature inference.
- `apps/sumai_agent/tests/test_canonicalization.py`: digests, stable IDs, sorting, and semantic hash.
- `apps/sumai_agent/tests/test_idempotency.py`: memo, expiry, copy isolation, and coalescing.
- `apps/sumai_agent/tests/test_async_pipeline.py`: awaited Gemini and web proxy behavior.
- `scripts/benchmark_pipeline.py`: bounded local benchmark and optional reviewed manifest evaluation.
- `evaluation/goldset_manifest.example.yaml`: synthetic-only example manifest.
- `docs/architecture.md`, `docs/gemini_integration.md`, `docs/risk_policy.md`, `docs/llm_stability_plan.md`: current implementation truth.

### Task 1: Versioned typed ontology and room-scoped lookup

**Files:**
- Create: `apps/sumai_agent/app/ontology.py`
- Modify: `apps/sumai_agent/app/knowledge_base/room_checklists.yaml`
- Modify: `apps/sumai_agent/app/services/checklist_engine.py`
- Modify: `apps/sumai_agent/app/services/rule_engine.py`
- Create: `apps/sumai_agent/tests/test_ontology.py`

- [ ] **Step 1: Write failing ontology tests**

```python
from app.ontology import OntologyRepository


def test_ontology_is_versioned_and_exposes_six_rooms() -> None:
    ontology = OntologyRepository.load_default()
    assert ontology.version == "1.0.0"
    assert set(ontology.room_names) == {
        "toilet", "bathroom", "genkan", "hallway", "bedroom", "kitchen"
    }


def test_repeated_risk_type_lookup_requires_room() -> None:
    ontology = OntologyRepository.load_default()
    toilet = ontology.risk_rule("toilet", "cluttered_path")
    kitchen = ontology.risk_rule("kitchen", "cluttered_path")
    assert toilet.room == "toilet"
    assert kitchen.room == "kitchen"
    assert toilet.family_actions != kitchen.family_actions


def test_vocabularies_are_derived_from_ontology() -> None:
    ontology = OntologyRepository.load_default()
    assert "hallway_cord" in ontology.visible_observation_keys
    assert "clear_path" in ontology.expected_feature_keys
    assert "cluttered_path" in ontology.risk_types
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_ontology.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.ontology'`.

- [ ] **Step 3: Migrate the YAML root to an explicit version and rooms map**

Insert this exact metadata at the document root:

```yaml
ontology_version: "1.0.0"
schema_version: "2.0.0"
inference_config_version: "1.0.0"
relationships:
  - located_in
  - intersects
  - obstructs
  - expected_in
  - supports_transfer_at
  - requires_confirmation
source_registry:
  MHLW_WELFARE_HOUSING:
    title_ja: 福祉用具・住宅改修
    publisher_ja: 厚生労働省
    url: https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/0000212398.html
  MHLW_NOTICE_OLD34:
    title_ja: 介護保険の給付対象となる福祉用具及び住宅改修の取扱いについて
    publisher_ja: 厚生労働省
    url: https://www.mhlw.go.jp/web/t_doc?dataId=00ta4381&dataType=1&pageNo=1
  CAA_FALL_PREVENTION:
    title_ja: 高齢者の転倒事故に注意しましょう
    publisher_ja: 消費者庁
    url: https://www.caa.go.jp/policies/policy/consumer_safety/caution/caution_040
basis_source_map:
  厚労省 福祉用具・住宅改修の考え方に関連:
    - MHLW_WELFARE_HOUSING
    - MHLW_NOTICE_OLD34
  消費者庁 転倒予防ポイントに基づく一般注意:
    - CAA_FALL_PREVENTION
action_policy:
  family:
    forbidden_words:
      - 購入
      - レンタル
      - 工事
      - 施工
      - 設置を依頼
      - 専門
    disclaimer_ja: 家族でできる範囲の一般的な予防行動です。無理な作業は避けてください。
  care_manager:
    disclaimer_ja: 購入・レンタル・福祉用具の相談候補です。適用制度や必要性は専門職に確認してください。
  contractor:
    disclaimer_ja: 写真だけでは寸法や施工可否を判断しません。必要に応じて現地確認を行ってください。
rooms:
```

Move the six complete existing `toilet`, `bathroom`, `genkan`, `hallway`,
`bedroom`, and `kitchen` mappings under `rooms` by adding two spaces to every
line in those blocks. Do not edit the contents of any expected-feature or
visible-hazard rule during this mechanical move.

- [ ] **Step 4: Add typed ontology models and repository**

Implement the complete loader in `app/ontology.py`:

```python
from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    def __init__(self, raw: dict[str, Any]) -> None:
        self.version = str(raw["ontology_version"])
        self.schema_version = str(raw["schema_version"])
        self.inference_config_version = str(raw["inference_config_version"])
        self.relationships = frozenset(raw["relationships"])
        self.source_registry: dict[str, dict[str, str]] = raw["source_registry"]
        self.basis_source_map: dict[str, list[str]] = raw["basis_source_map"]
        self.action_policy: dict[str, dict[str, Any]] = raw["action_policy"]
        self._rooms: dict[str, dict[str, Any]] = raw["rooms"]
        if not self._rooms:
            raise ValueError("Ontology must define at least one room.")

    @classmethod
    def load_default(cls) -> "OntologyRepository":
        path = (
            Path(__file__).resolve().parent
            / "knowledge_base"
            / "room_checklists.yaml"
        )
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        if not isinstance(raw, dict):
            raise ValueError("Ontology root must be an object.")
        return cls(raw)

    @property
    def room_names(self) -> tuple[str, ...]:
        return tuple(self._rooms)

    @cached_property
    def expected_feature_keys(self) -> frozenset[str]:
        return frozenset(
            item["key"]
            for room in self._rooms.values()
            for item in room.get("expected_features", [])
        )

    @cached_property
    def visible_observation_keys(self) -> frozenset[str]:
        return frozenset(
            item["key"]
            for room in self._rooms.values()
            for item in room.get("visible_hazards", [])
        )

    @cached_property
    def risk_types(self) -> frozenset[str]:
        return frozenset(
            item["risk_type"]
            for room in self._rooms.values()
            for item in room.get("visible_hazards", [])
        )

    def room(self, room: str) -> dict[str, Any] | None:
        return self._rooms.get(room)

    def risk_rule(self, room: str, risk_type: str) -> OntologyRiskRule:
        room_data = self._rooms.get(room)
        if room_data is None:
            raise KeyError(f"Unsupported ontology room: {room}")
        for item in room_data.get("visible_hazards", []):
            if item["risk_type"] == risk_type:
                rule = OntologyRiskRule(room=room, **item)
                return rule.model_copy(update={
                    "evidence_source_ids": tuple(
                        self.basis_source_map.get(item["basis_label_ja"], [])
                    )
                })
        for item in room_data.get("expected_features", []):
            if item["missing_risk_type"] == risk_type:
                return OntologyRiskRule(
                    room=room,
                    key=item["key"],
                    risk_type=item["missing_risk_type"],
                    label_ja=item["missing_label_ja"],
                    severity=item["severity"],
                    basis_label_ja=item["basis_label_ja"],
                    basis_summary_ja=item["basis_summary_ja"],
                    measure_label_ja=item["measure_label_ja"],
                    family_actions=tuple(item.get("family_actions", [])),
                    care_manager_actions=tuple(item.get("care_manager_actions", [])),
                    contractor_actions=tuple(item.get("contractor_actions", [])),
                    expected_feature_key=item["key"],
                    evidence_source_ids=tuple(
                        self.basis_source_map.get(item["basis_label_ja"], [])
                    ),
                )
        raise KeyError(f"No risk rule for {room}:{risk_type}")
```

- [ ] **Step 5: Make checklist and rule engines consume one repository**

Construct `OntologyRepository.load_default()` once per engine. Replace direct
YAML loading. Change `_find_checklist_item` to require room:

```python
def _find_checklist_item(
    self, room_type: str, risk_type: str
) -> OntologyRiskRule | None:
    try:
        return self.ontology.risk_rule(room_type, risk_type)
    except KeyError:
        return None
```

Pass `room_type` into `RuleEngine.apply(findings, room_type)`. Update the
orchestrator and existing tests to supply the detected room.

Move the family forbidden words and all three tier disclaimers out of
`rule_engine.py` constants and read them from `ontology.action_policy`. Add a
test asserting every referenced evidence-source ID exists in
`ontology.source_registry`.

- [ ] **Step 6: Run focused and existing rule tests**

Run:

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_ontology.py \
  apps/sumai_agent/tests/test_checklist_system.py \
  apps/sumai_agent/tests/test_rule_engine.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 1**

```bash
git add \
  apps/sumai_agent/app/ontology.py \
  apps/sumai_agent/app/knowledge_base/room_checklists.yaml \
  apps/sumai_agent/app/services/checklist_engine.py \
  apps/sumai_agent/app/services/rule_engine.py \
  apps/sumai_agent/app/services/orchestrator.py \
  apps/sumai_agent/tests/test_ontology.py \
  apps/sumai_agent/tests/test_checklist_system.py \
  apps/sumai_agent/tests/test_rule_engine.py
git commit -m "feat: make safety rules room-scoped ontology"
```

### Task 2: Minimal visual-facts schema

**Files:**
- Modify: `apps/sumai_agent/app/models.py`
- Modify: `apps/sumai_agent/app/services/gemini_vision.py`
- Create: `apps/sumai_agent/tests/test_visual_facts.py`
- Modify: `apps/sumai_agent/tests/test_gemini_parsing.py`

- [ ] **Step 1: Write failing model and schema tests**

```python
import json

from app.models import VisionFacts
from app.services.gemini_vision import (
    GEMINI_FACTS_JSON_SCHEMA,
    parse_vision_facts_json,
)


def test_visual_facts_schema_contains_no_policy_or_report_fields() -> None:
    encoded = json.dumps(GEMINI_FACTS_JSON_SCHEMA, ensure_ascii=False)
    for forbidden in (
        "severity", "action_plan", "label_ja", "description_ja",
        "basis_label_ja", "basis_summary_ja",
    ):
        assert forbidden not in encoded


def test_parse_visual_facts_preserves_typed_evidence() -> None:
    facts = parse_vision_facts_json(json.dumps({
        "environment": "home",
        "room_type": "hallway",
        "visible_regions": ["walking_path"],
        "entities": [{
            "ref": "e1",
            "ontology_key": "hallway_cord",
            "bbox": {"x": 0.1, "y": 0.7, "w": 0.7, "h": 0.1},
            "visibility": "clear",
            "model_score": 0.9,
        }],
        "feature_observations": [],
        "relationships": [{
            "subject": "e1",
            "predicate": "intersects",
            "object": "walking_path",
        }],
        "not_applicable_reason_code": None,
    }))
    assert isinstance(facts, VisionFacts)
    assert facts.entities[0].ontology_key == "hallway_cord"
    assert facts.relationships[0].predicate == "intersects"
```

- [ ] **Step 2: Run and confirm RED**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_visual_facts.py -q
```

Expected: import fails because `VisionFacts` does not exist.

- [ ] **Step 3: Add internal visual-fact models**

Add to `models.py`:

```python
EnvironmentType = Literal["home", "non_home", "uncertain"]
DetectedRoomType = Literal[
    "genkan", "hallway", "bathroom", "toilet",
    "bedroom", "kitchen", "unknown",
]
VisibilityState = Literal["clear", "partial", "uncertain"]
FeatureState = Literal[
    "present", "absent_with_full_coverage", "cannot_determine"
]


class VisionEntity(BaseModel):
    ref: str = Field(min_length=1, max_length=32)
    ontology_key: str
    bbox: BoundingBox
    visibility: VisibilityState
    model_score: float = Field(ge=0.0, le=1.0)


class FeatureObservation(BaseModel):
    feature_key: str
    state: FeatureState
    evidence_bbox: BoundingBox | None = None
    model_score: float = Field(ge=0.0, le=1.0)


class VisionRelationship(BaseModel):
    subject: str
    predicate: str
    object: str


class VisionFacts(BaseModel):
    environment: EnvironmentType
    room_type: DetectedRoomType
    visible_regions: list[str] = Field(default_factory=list)
    entities: list[VisionEntity] = Field(default_factory=list)
    feature_observations: list[FeatureObservation] = Field(default_factory=list)
    relationships: list[VisionRelationship] = Field(default_factory=list)
    not_applicable_reason_code: str | None = None
```

- [ ] **Step 4: Generate the facts schema from the ontology**

In `gemini_vision.py`, load the repository once and define
`GEMINI_FACTS_JSON_SCHEMA`. Use `additionalProperties: false` at every object,
enumerate ontology keys and relationships, and require all top-level fields.
The entity item has only `ref`, `ontology_key`, `bbox`, `visibility`, and
`model_score`. The feature item has only `feature_key`, `state`,
`evidence_bbox`, and `model_score`.

Implement strict parsing:

```python
def parse_vision_facts_json(raw_json: str) -> VisionFacts:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        logger.warning("gemini_json_decode_error", extra={"raw_length": len(raw_json)})
        raise ValueError("Gemini response is empty or not valid JSON.") from None
    if not isinstance(data, dict):
        raise ValueError("Gemini response must be a JSON object.")
    try:
        return VisionFacts.model_validate(data)
    except ValidationError:
        logger.warning("gemini_facts_schema_validation_error")
        raise ValueError("Gemini response does not match visual facts schema.") from None
```

After Pydantic validation, explicitly reject entity keys, feature keys, and
relationship predicates not present in the ontology repository.

- [ ] **Step 5: Switch only the provider call to the facts parser**

Keep `parse_vision_json` for existing compatibility tests. Change
`_call_gemini` to request `GEMINI_FACTS_JSON_SCHEMA` and return `VisionFacts`.
Update `GeminiVisionService.analyze` return type accordingly. Replace
`mock_vision_result` provider usage with a new deterministic
`mock_vision_facts`; retain `mock_vision_result` as a compatibility helper.

- [ ] **Step 6: Run schema, parsing, strict-mode, and mock tests**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_visual_facts.py \
  apps/sumai_agent/tests/test_gemini_parsing.py \
  apps/sumai_agent/tests/test_strict_production.py \
  apps/sumai_agent/tests/test_mock_analyze.py -q
```

Expected: all selected tests pass; strict invalid facts still become HTTP 503
and non-strict failures remain explicitly labeled fallback.

- [ ] **Step 7: Commit Task 2**

```bash
git add \
  apps/sumai_agent/app/models.py \
  apps/sumai_agent/app/services/gemini_vision.py \
  apps/sumai_agent/tests/test_visual_facts.py \
  apps/sumai_agent/tests/test_gemini_parsing.py \
  apps/sumai_agent/tests/test_strict_production.py
git commit -m "feat: constrain Gemini to minimal visual facts"
```

### Task 3: Evidence relationships and Python risk derivation

**Files:**
- Create: `apps/sumai_agent/app/services/relationship_engine.py`
- Modify: `apps/sumai_agent/app/ontology.py`
- Modify: `apps/sumai_agent/app/services/checklist_engine.py`
- Modify: `apps/sumai_agent/app/services/rule_engine.py`
- Create: `apps/sumai_agent/tests/test_relationship_engine.py`

- [ ] **Step 1: Write failing relationship tests**

```python
from app.models import (
    BoundingBox, FeatureObservation, VisionEntity, VisionFacts,
    VisionRelationship,
)
from app.ontology import OntologyRepository
from app.services.relationship_engine import RelationshipEngine


def test_cord_requires_path_relationship() -> None:
    facts = VisionFacts(
        environment="home",
        room_type="hallway",
        visible_regions=["walking_path"],
        entities=[VisionEntity(
            ref="e1",
            ontology_key="hallway_cord",
            bbox=BoundingBox(x=0.1, y=0.7, w=0.7, h=0.1),
            visibility="clear",
            model_score=0.9,
        )],
        relationships=[],
    )
    findings = RelationshipEngine(OntologyRepository.load_default()).derive(facts)
    assert findings == []

    facts.relationships.append(VisionRelationship(
        subject="e1", predicate="intersects", object="walking_path"
    ))
    findings = RelationshipEngine(OntologyRepository.load_default()).derive(facts)
    assert [finding.risk_type for finding in findings] == ["hallway_cord"]


def test_missing_feature_requires_explicit_full_coverage_absence() -> None:
    base = dict(
        environment="home",
        room_type="bathroom",
        visible_regions=["transfer_zone"],
        entities=[],
        relationships=[],
    )
    uncertain = VisionFacts(**base, feature_observations=[FeatureObservation(
        feature_key="has_handrail",
        state="cannot_determine",
        evidence_bbox=None,
        model_score=0.9,
    )])
    assert RelationshipEngine(
        OntologyRepository.load_default()
    ).derive(uncertain) == []

    absent = VisionFacts(**base, feature_observations=[FeatureObservation(
        feature_key="has_handrail",
        state="absent_with_full_coverage",
        evidence_bbox=BoundingBox(x=0.05, y=0.2, w=0.3, h=0.6),
        model_score=0.9,
    )])
    assert [finding.risk_type for finding in RelationshipEngine(
        OntologyRepository.load_default()
    ).derive(absent)] == ["bathroom_missing_handrail"]
```

- [ ] **Step 2: Run and confirm RED**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_relationship_engine.py -q
```

Expected: import fails because `relationship_engine.py` does not exist.

- [ ] **Step 3: Add ontology relationship requirements**

Expose the required predicate for each visible observation. Use this
deterministic mapping in `ontology.py`:

```python
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
    "no_shower_chair": "located_in",
    "space_looks_narrow": "obstructs",
    "loose_shoes": "obstructs",
    "reachable_storage_issue": "located_in",
}
```

Every visible observation key present in the ontology must have a requirement;
add an ontology test asserting exact coverage.

- [ ] **Step 4: Implement deterministic derivation**

Implement `RelationshipEngine`:

```python
class RelationshipEngine:
    def __init__(self, ontology: OntologyRepository) -> None:
        self.ontology = ontology

    def derive(self, facts: VisionFacts) -> list[RiskFinding]:
        if facts.environment != "home" or facts.room_type not in self.ontology.room_names:
            return []
        room = str(facts.room_type)
        relations = {
            (item.subject, item.predicate, item.object)
            for item in facts.relationships
        }
        findings: list[RiskFinding] = []
        room_data = self.ontology.room(room)
        assert room_data is not None

        visible_by_key = {
            item["key"]: item
            for item in room_data.get("visible_hazards", [])
        }
        for entity in facts.entities:
            rule_data = visible_by_key.get(entity.ontology_key)
            if rule_data is None or entity.visibility != "clear":
                continue
            predicate = self.ontology.required_predicate(entity.ontology_key)
            if not any(
                subject == entity.ref and relation == predicate
                for subject, relation, _ in relations
            ):
                continue
            rule = self.ontology.risk_rule(room, rule_data["risk_type"])
            findings.append(self._finding(rule, entity.bbox, entity.model_score))

        expected_by_key = {
            item["key"]: item
            for item in room_data.get("expected_features", [])
        }
        for observation in facts.feature_observations:
            item = expected_by_key.get(observation.feature_key)
            if (
                item is None
                or observation.state != "absent_with_full_coverage"
                or observation.evidence_bbox is None
            ):
                continue
            rule = self.ontology.risk_rule(room, item["missing_risk_type"])
            findings.append(
                self._finding(rule, observation.evidence_bbox, observation.model_score)
            )
        return findings

    @staticmethod
    def _finding(
        rule: OntologyRiskRule,
        bbox: BoundingBox,
        model_score: float,
    ) -> RiskFinding:
        return RiskFinding(
            id="pending",
            risk_type=rule.risk_type,
            label_ja=rule.label_ja,
            description_ja=f"{rule.label_ja}が写真で確認されました。",
            severity=rule.severity,
            confidence=model_score,
            bbox=bbox,
            evidence_ja="写真内の表示範囲に可視の根拠があります。",
            basis_label_ja=rule.basis_label_ja,
            basis_summary_ja=rule.basis_summary_ja,
            needs_human_confirmation=model_score < 0.60,
        )
```

- [ ] **Step 5: Use relationship derivation in the orchestrator**

After `GeminiVisionService.analyze`, call `RelationshipEngine.derive` and pass
the resulting findings plus room to `RuleEngine.apply`. Keep
`ChecklistEngine.process` only as a compatibility adapter for existing tests
and legacy `VisionResult` callers.

- [ ] **Step 6: Run focused and regression tests**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_relationship_engine.py \
  apps/sumai_agent/tests/test_checklist_system.py \
  apps/sumai_agent/tests/test_rule_engine.py \
  apps/sumai_agent/tests/test_mock_analyze.py -q
```

Expected: all selected tests pass and `cannot_determine` never becomes a
missing-feature finding.

- [ ] **Step 7: Commit Task 3**

```bash
git add \
  apps/sumai_agent/app/ontology.py \
  apps/sumai_agent/app/services/relationship_engine.py \
  apps/sumai_agent/app/services/checklist_engine.py \
  apps/sumai_agent/app/services/rule_engine.py \
  apps/sumai_agent/app/services/orchestrator.py \
  apps/sumai_agent/tests/test_ontology.py \
  apps/sumai_agent/tests/test_relationship_engine.py
git commit -m "feat: derive visible risks from evidence relationships"
```

### Task 4: Canonical identity, stable ordering, and semantic hash

**Files:**
- Create: `apps/sumai_agent/app/services/canonicalization.py`
- Modify: `apps/sumai_agent/app/services/image_intake.py`
- Modify: `apps/sumai_agent/app/models.py`
- Modify: `apps/sumai_agent/app/services/orchestrator.py`
- Modify: `apps/sumai_agent/app/services/visual_renderer.py`
- Create: `apps/sumai_agent/tests/test_canonicalization.py`

- [ ] **Step 1: Write failing canonicalization tests**

```python
from PIL import Image

from app.models import BoundingBox, RiskFinding
from app.services.canonicalization import (
    canonical_pixel_digest,
    canonicalize_findings,
    result_key,
    semantic_hash,
)


def _finding(
    risk_type: str,
    severity: int,
    confidence: float,
    bbox_x: float,
) -> RiskFinding:
    return RiskFinding(
        id="pending",
        risk_type=risk_type,
        label_ja=risk_type,
        description_ja="決定的な説明",
        severity=severity,
        confidence=confidence,
        bbox=BoundingBox(x=bbox_x, y=0.1, w=0.1, h=0.1),
        evidence_ja="写真内の表示範囲に可視の根拠があります。",
        basis_label_ja="テスト根拠",
        basis_summary_ja="テスト根拠の要約",
        needs_human_confirmation=False,
    )


def test_pixel_digest_ignores_container_encoding() -> None:
    image = Image.new("RGB", (10, 10), "white")
    assert canonical_pixel_digest(image) == canonical_pixel_digest(image.copy())


def test_result_key_changes_when_ontology_version_changes() -> None:
    first = result_key("pixels", "auto", "1", "2", "model", "1")
    second = result_key("pixels", "auto", "1", "3", "model", "1")
    assert first != second


def test_findings_have_stable_order_and_ids() -> None:
    low = _finding("poor_lighting", 2, 0.8, 0.2)
    high = _finding("hallway_cord", 3, 0.9, 0.7)
    left_to_right = canonicalize_findings([low, high])
    reversed_input = canonicalize_findings([high, low])
    assert [item.model_dump() for item in left_to_right] == [
        item.model_dump() for item in reversed_input
    ]
    assert [item.id for item in left_to_right] == ["R1", "R2"]
```

- [ ] **Step 2: Run and confirm RED**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_canonicalization.py -q
```

Expected: module import fails.

- [ ] **Step 3: Implement canonicalization**

```python
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from PIL import Image

from app.models import RiskFinding


def canonical_pixel_digest(image: Image.Image) -> str:
    normalized = image.convert("RGB")
    payload = (
        normalized.mode.encode("ascii")
        + normalized.width.to_bytes(4, "big")
        + normalized.height.to_bytes(4, "big")
        + normalized.tobytes()
    )
    return hashlib.sha256(payload).hexdigest()


def result_key(
    pixel_digest: str,
    room_hint: str,
    preprocess_version: str,
    ontology_version: str,
    model: str,
    inference_config_version: str,
) -> str:
    payload = "|".join((
        pixel_digest,
        room_hint,
        preprocess_version,
        ontology_version,
        model,
        inference_config_version,
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonicalize_findings(findings: list[RiskFinding]) -> list[RiskFinding]:
    ordered = sorted(
        (deepcopy(item) for item in findings),
        key=lambda item: (
            -item.severity,
            item.risk_type,
            round(item.bbox.x, 3),
            round(item.bbox.y, 3),
            round(item.bbox.w, 3),
            round(item.bbox.h, 3),
        ),
    )
    return [
        item.model_copy(update={
            "id": f"R{index}",
            "bbox": item.bbox.model_copy(update={
                "x": round(item.bbox.x, 3),
                "y": round(item.bbox.y, 3),
                "w": round(item.bbox.w, 3),
                "h": round(item.bbox.h, 3),
            }),
        })
        for index, item in enumerate(ordered, start=1)
    ]


def semantic_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Add additive public response fields**

Add defaults to `AnalysisResponse`:

```python
result_key: str = ""
semantic_hash: str = ""
schema_version: str = "2.0.0"
ontology_version: str = "1.0.0"
preprocess_version: str = "1.0.0"
inference_config_version: str = "1.0.0"
stage_timings_ms: dict[str, int] = Field(default_factory=dict)
```

Keep `bbox` as the evidence bbox. Add
`display_bbox: BoundingBox | None = None` to `RiskFinding`; update visual
rendering to use `display_bbox or bbox` and never overwrite `bbox`. Also add
`evidence_source_ids: list[str] = Field(default_factory=list)` and populate it
from the room-scoped ontology rule in `RelationshipEngine`.

- [ ] **Step 5: Integrate stable identity before action generation**

Canonicalize findings before `RuleEngine.apply`, so action IDs reference stable
risk IDs. Build the semantic-hash payload from room type, findings, and action
plan only; exclude `analysis_id`, timings, mode, model, image Base64, and log
data.

- [ ] **Step 6: Run focused and visual regressions**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_canonicalization.py \
  apps/sumai_agent/tests/test_visual_renderer.py \
  apps/sumai_agent/tests/test_visual_renderer_prioritization.py \
  apps/sumai_agent/tests/test_mock_analyze.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add \
  apps/sumai_agent/app/models.py \
  apps/sumai_agent/app/services/canonicalization.py \
  apps/sumai_agent/app/services/image_intake.py \
  apps/sumai_agent/app/services/orchestrator.py \
  apps/sumai_agent/app/services/visual_renderer.py \
  apps/sumai_agent/tests/test_canonicalization.py \
  apps/sumai_agent/tests/test_mock_analyze.py \
  apps/sumai_agent/tests/test_visual_renderer.py \
  apps/sumai_agent/tests/test_visual_renderer_prioritization.py
git commit -m "feat: add canonical analysis identity"
```

### Task 5: Bounded semantic memo and request coalescing

**Files:**
- Create: `apps/sumai_agent/app/services/result_memo.py`
- Modify: `apps/sumai_agent/app/config.py`
- Modify: `apps/sumai_agent/app/services/orchestrator.py`
- Create: `apps/sumai_agent/tests/test_idempotency.py`

- [ ] **Step 1: Write failing memo tests**

```python
import asyncio

from app.services.result_memo import AsyncResultMemo


def test_memo_returns_copy_and_expires() -> None:
    async def scenario() -> None:
        now = [10.0]
        memo = AsyncResultMemo(max_items=2, ttl_seconds=5, clock=lambda: now[0])
        calls = 0

        async def factory() -> tuple[dict[str, list[int]], bool]:
            nonlocal calls
            calls += 1
            return {"values": [1]}, True

        first, first_hit = await memo.get_or_compute("key", factory)
        first["values"].append(2)
        second, second_hit = await memo.get_or_compute("key", factory)
        assert first_hit is False
        assert second_hit is True
        assert second == {"values": [1]}
        now[0] = 16.0
        _, third_hit = await memo.get_or_compute("key", factory)
        assert third_hit is False
        assert calls == 2

    asyncio.run(scenario())


def test_concurrent_identical_requests_compute_once() -> None:
    async def scenario() -> None:
        memo = AsyncResultMemo(max_items=2, ttl_seconds=30)
        calls = 0

        async def factory() -> tuple[dict[str, int], bool]:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return {"value": 1}, True

        await asyncio.gather(*[
            memo.get_or_compute("same", factory) for _ in range(5)
        ])
        assert calls == 1

    asyncio.run(scenario())
```

- [ ] **Step 2: Run and confirm RED**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_idempotency.py -q
```

Expected: module import fails.

- [ ] **Step 3: Add memo configuration**

Add integer settings:

```python
result_memo_ttl_seconds: int = int(
    os.getenv("RESULT_MEMO_TTL_SECONDS", "300")
)
result_memo_max_items: int = int(
    os.getenv("RESULT_MEMO_MAX_ITEMS", "128")
)
```

Reject non-positive values in `Settings.__post_init__`.

- [ ] **Step 4: Implement the memo**

Use `OrderedDict`, `asyncio.Lock`, monotonic time, and `deepcopy`. Store
`(expires_at, value)` and an in-flight `Task` by key. `get_or_compute` returns
`(copied_value, cache_hit)`. Cache only when the factory's second return value
is true. Always remove completed or failed in-flight tasks in `finally`.

The implementation must not accept or store image bytes. Type the class
generically over structured Python values.

- [ ] **Step 5: Integrate semantic memo in the orchestrator**

Create a dataclass `ComputedAnalysis` containing room, findings, action plan,
reports, mode, model, and semantic hash, but no image or Base64 fields. Use
`result_key` before the provider call and wrap vision through report generation
in `memo.get_or_compute`.

Set cacheable true only for:

```python
cacheable = mode == "mock" or mode == "gemini"
```

Any mode beginning with `gemini_fallback` remains uncached. Render from the
current request's sanitized image after the memo result returns.

- [ ] **Step 6: Add endpoint idempotency test**

Patch the vision service with a deterministic facts result, submit the same
image twice, and assert:

```python
assert first["analysis_id"] != second["analysis_id"]
assert first["result_key"] == second["result_key"]
assert first["semantic_hash"] == second["semantic_hash"]
assert first["findings"] == second["findings"]
assert first["action_plan"] == second["action_plan"]
```

- [ ] **Step 7: Run focused and API tests**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_idempotency.py \
  apps/sumai_agent/tests/test_mock_analyze.py \
  apps/sumai_agent/tests/test_strict_production.py -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit Task 5**

```bash
git add \
  apps/sumai_agent/app/config.py \
  apps/sumai_agent/app/services/result_memo.py \
  apps/sumai_agent/app/services/orchestrator.py \
  apps/sumai_agent/tests/test_idempotency.py \
  apps/sumai_agent/tests/test_mock_analyze.py
git commit -m "feat: coalesce repeated semantic analysis"
```

### Task 6: Stage timing and CPU thread isolation

**Files:**
- Modify: `apps/sumai_agent/app/services/orchestrator.py`
- Modify: `apps/sumai_agent/app/main.py`
- Create: `apps/sumai_agent/tests/test_pipeline_timings.py`

- [ ] **Step 1: Write failing stage-timing test**

Post one mock image and assert:

```python
timings = response.json()["stage_timings_ms"]
assert set(timings) == {
    "intake", "memo_lookup", "vision", "ontology",
    "render", "report", "serialize", "total",
}
assert all(isinstance(value, int) and value >= 0 for value in timings.values())
```

Capture logs and assert neither `result_key` nor any SHA-256-shaped string is
present.

- [ ] **Step 2: Run and confirm RED**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_pipeline_timings.py -q
```

Expected: missing timing keys.

- [ ] **Step 3: Add monotonic stage measurement**

In the orchestrator, use a helper:

```python
def elapsed_ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
```

Use `await asyncio.to_thread` for `read_and_sanitize_image` and
`visual_renderer.render`. Record each stage around the actual operation. Store
zero for `vision` on a memo hit and retain the memo-hit marker only in logs.

- [ ] **Step 4: Measure serialization without bypassing Pydantic**

In `main.analyze`, after receiving `AnalysisResponse`, time
`response.model_dump(mode="json")`, add `serialize`, recompute `total`, and
return `JSONResponse(content=content)`. Do not include images, digests, or raw
provider payload in logs.

- [ ] **Step 5: Extend structured log allowlist**

Log `stage_timings_ms` and `cache_hit` as structured fields. Do not log
`result_key`, `semantic_hash`, or pixel digest.

- [ ] **Step 6: Run timing and endpoint regressions**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_pipeline_timings.py \
  apps/sumai_agent/tests/test_healthz.py \
  apps/sumai_agent/tests/test_mock_analyze.py \
  apps/sumai_agent/tests/test_strict_production.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 6**

```bash
git add \
  apps/sumai_agent/app/main.py \
  apps/sumai_agent/app/services/orchestrator.py \
  apps/sumai_agent/tests/test_pipeline_timings.py
git commit -m "feat: measure and isolate analysis stages"
```

### Task 7: Reusable asynchronous Gemini and web clients

**Files:**
- Modify: `apps/sumai_agent/app/services/gemini_vision.py`
- Modify: `apps/sumai_web/app.py`
- Modify: `apps/sumai_web/requirements.txt`
- Create: `apps/sumai_agent/tests/test_async_pipeline.py`

- [ ] **Step 1: Write failing Gemini async-client test**

Build a fake client with:

```python
generate = AsyncMock(return_value=SimpleNamespace(text=VALID_FACTS_JSON))
fake_client = SimpleNamespace(
    aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))
)
service = GeminiVisionService(client_factory=lambda: fake_client)
first = asyncio.run(service._call_gemini(b"image", "auto"))
second = asyncio.run(service._call_gemini(b"image", "auto"))
assert generate.await_count == 2
assert service._client is fake_client
```

The test must also assert `response_json_schema is GEMINI_FACTS_JSON_SCHEMA`.

- [ ] **Step 2: Write failing async web-proxy test**

Load `apps/sumai_web/app.py`, inject an `httpx.AsyncClient` fake whose `post`
is an `AsyncMock`, call the `/analyze` route, and assert it was awaited once.
Use a deterministic 200 backend JSON response.

- [ ] **Step 3: Run and confirm RED**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_async_pipeline.py -q
```

Expected: constructor signature or awaited-client assertions fail.

- [ ] **Step 4: Implement lazy reusable async Gemini client**

Add:

```python
class GeminiVisionService:
    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                from google import genai
                self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client
```

In `_call_gemini`:

```python
response = await self._get_client().aio.models.generate_content(
    model=settings.gemini_model,
    contents=[prompt, image_part],
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=GEMINI_FACTS_JSON_SCHEMA,
    ),
)
```

- [ ] **Step 5: Replace blocking web proxy**

Remove `requests.post`. Add module-level lazy client:

```python
_backend_client: httpx.AsyncClient | None = None


def backend_client() -> httpx.AsyncClient:
    global _backend_client
    if _backend_client is None:
        _backend_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    return _backend_client
```

Await `backend_client().post(...)`. Add a FastAPI shutdown handler that closes
and clears the client. Preserve strict-mode 503 behavior and non-strict local
fallback labels.

- [ ] **Step 6: Run async, strict, and parser tests**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_async_pipeline.py \
  apps/sumai_agent/tests/test_gemini_parsing.py \
  apps/sumai_agent/tests/test_strict_production.py -q
```

Expected: all selected tests pass, and no production code calls
`requests.post`.

- [ ] **Step 7: Commit Task 7**

```bash
git add \
  apps/sumai_agent/app/services/gemini_vision.py \
  apps/sumai_web/app.py \
  apps/sumai_web/requirements.txt \
  apps/sumai_agent/tests/test_async_pipeline.py \
  apps/sumai_agent/tests/test_gemini_parsing.py
git commit -m "perf: make vision and proxy calls asynchronous"
```

### Task 8: Benchmark and evaluation interface

**Files:**
- Create: `scripts/benchmark_pipeline.py`
- Create: `evaluation/goldset_manifest.example.yaml`
- Create: `apps/sumai_agent/tests/test_benchmark_pipeline.py`

- [ ] **Step 1: Write failing manifest and metric tests**

Test that the example manifest contains only repository synthetic sample paths,
no absolute local home-directory paths, and no `private` classification. Test the metric
helper:

```python
assert percentile([1, 2, 3, 4], 0.50) == 2
assert precision_recall_f1({"a", "b"}, {"b", "c"}) == {
    "precision": 0.5,
    "recall": 0.5,
    "f1": 0.5,
}
```

- [ ] **Step 2: Run and confirm RED**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_benchmark_pipeline.py -q
```

Expected: benchmark module import fails.

- [ ] **Step 3: Add the synthetic example manifest**

```yaml
version: "1"
classification: synthetic
cases:
  - id: hallway_synthetic
    image: apps/sumai_web/assets/samples/hallway_sample.png
    room_hint: hallway
    expected_risk_types:
      - hallway_cord
  - id: bathroom_synthetic
    image: apps/sumai_web/assets/samples/bathroom_sample.png
    room_hint: bathroom
    expected_risk_types:
      - bathroom_slip
  - id: genkan_synthetic
    image: apps/sumai_web/assets/samples/genkan_sample.png
    room_hint: genkan
    expected_risk_types:
      - genkan_step
```

- [ ] **Step 4: Implement bounded benchmark runner**

The script:

- accepts `--manifest`, `--repeat`, and `--base-url`;
- rejects `repeat < 1` or `repeat > 50`;
- resolves image paths relative to repository root;
- refuses paths outside the repository for the committed example runner;
- sends multipart requests with explicit `mock=true` unless `--real` is passed;
- in real mode first validates `/status` has strict real provenance;
- records total and response stage timings;
- computes risk precision, recall, and F1 from expected risk types;
- prints JSON summary only;
- never prints image bytes, hashes, API keys, or raw Gemini text.

Expose pure helpers `percentile` and `precision_recall_f1` for unit tests.

- [ ] **Step 5: Run tests and local mock benchmark**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_benchmark_pipeline.py -q
```

Then start the local mock backend on an unused port and run:

```bash
PYTHONPATH=apps/sumai_agent MOCK_MODE=true \
  python3 -m uvicorn app.main:app --host 127.0.0.1 --port 18082
python3 scripts/benchmark_pipeline.py \
  --manifest evaluation/goldset_manifest.example.yaml \
  --repeat 10 \
  --base-url http://127.0.0.1:18082
```

Expected: three cases complete, `schema_valid_rate` is `1.0`, and the summary
labels the dataset `synthetic`.

- [ ] **Step 6: Commit Task 8**

```bash
git add \
  scripts/benchmark_pipeline.py \
  evaluation/goldset_manifest.example.yaml \
  apps/sumai_agent/tests/test_benchmark_pipeline.py
git commit -m "test: add bounded analysis benchmark"
```

### Task 9: Documentation alignment

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/gemini_integration.md`
- Modify: `docs/risk_policy.md`
- Modify: `docs/llm_stability_plan.md`
- Modify: `docs/decisions.md`
- Create: `apps/sumai_agent/tests/test_documentation_contract.py`

- [ ] **Step 1: Write failing documentation contract tests**

Implement:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_documentation_matches_runtime_contracts() -> None:
    gemini_doc = _read("docs/gemini_integration.md")
    architecture_doc = _read("docs/architecture.md")
    risk_policy_doc = _read("docs/risk_policy.md")
    decisions_doc = _read("docs/decisions.md")
    stability_doc = _read("docs/llm_stability_plan.md")

    assert "GEMINI_FACTS_JSON_SCHEMA" in gemini_doc
    assert "room_checklists.yaml" in architecture_doc
    assert "result_key" in architecture_doc
    assert "semantic_hash" in architecture_doc
    assert "0.45" in risk_policy_doc
    assert "0.60" in risk_policy_doc
    assert "demo_rules.yaml" not in decisions_doc
    assert "strict malformed JSON behavior" not in stability_doc
```

- [ ] **Step 2: Run and confirm RED**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_documentation_contract.py -q
```

Expected: current docs fail multiple assertions.

- [ ] **Step 3: Update architecture and integration docs**

Document:

- minimal visual facts;
- Python relationship inference;
- room-scoped ontology lookup;
- evidence bbox versus display bbox;
- result key and semantic hash boundaries;
- process-local memo limitations;
- async clients and timeout budget;
- stage timings;
- no persistent images or results;
- synthetic benchmark is not recognition evidence.

- [ ] **Step 4: Correct policy and decision drift**

Make the risk-policy thresholds match code:

- below `0.45`: drop;
- known `0.45` through below `0.60`: human confirmation;
- unknown below `0.75`: drop.

Remove claims that `demo_rules.yaml` controls routing. Record
`room_checklists.yaml` plus `OntologyRepository` as the source of truth.
Record that strict malformed provider payloads fail closed.

- [ ] **Step 5: Run documentation and full backend tests**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_documentation_contract.py -q
PYTHONPATH=apps/sumai_agent python3 -m pytest apps/sumai_agent/tests -q
```

Expected: documentation contract passes and backend test count has zero
failures.

- [ ] **Step 6: Commit Task 9**

```bash
git add \
  docs/architecture.md \
  docs/gemini_integration.md \
  docs/risk_policy.md \
  docs/llm_stability_plan.md \
  docs/decisions.md \
  apps/sumai_agent/tests/test_documentation_contract.py
git commit -m "docs: align safety pipeline contracts"
```

### Task 10: Full verification and branch closeout

**Files:**
- Review: all files changed by Tasks 1-9

- [ ] **Step 1: Run the complete repository verification**

```bash
./scripts/test_all.sh
```

Expected:

- backend tests: zero failures;
- frontend import: success;
- Docker Compose config: success.

- [ ] **Step 2: Run the benchmark unit tests and bounded synthetic benchmark**

```bash
PYTHONPATH=apps/sumai_agent python3 -m pytest \
  apps/sumai_agent/tests/test_benchmark_pipeline.py -q
```

Start the verified local mock backend and run the exact Task 8 benchmark
command. Expected: JSON summary, synthetic classification, no secrets or raw
image data.

- [ ] **Step 3: Verify no blocking proxy call or duplicate ontology loader remains**

```bash
rg -n "requests\\.post|yaml\\.safe_load" \
  apps/sumai_web/app.py \
  apps/sumai_agent/app/services
```

Expected:

- no `requests.post` in the web proxy;
- no direct YAML load in checklist or rule engines.

- [ ] **Step 4: Review formatting and complete diff**

```bash
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
git diff origin/main...HEAD
```

Expected: no whitespace errors; only the approved pipeline, tests, benchmark,
and documentation are changed.

- [ ] **Step 5: Verify repository state and preserve user files**

```bash
git status --short --branch
git status --short docs/preconsultation
```

Expected:

- branch is `codex/sumaiguard-ontology-speed`;
- `docs/preconsultation/` remains untracked and unmodified;
- no unrelated file is staged.

- [ ] **Step 6: Use the finishing-a-development-branch skill**

Review test evidence and present the user with the supported branch completion
options. Do not merge, push, open a PR, or remove the worktree without the
user's explicit selection.
