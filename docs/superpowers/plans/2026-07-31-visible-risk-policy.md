# Visible Risk Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure only directly visible and localized hazards affect findings, risk level, overlays, and actions, while photo-scoped equipment non-detections become neutral `confirmation_items`.

**Architecture:** Replace the mixed `RiskFinding` output from `RelationshipEngine` with a typed `RelationshipDerivation` containing visible findings and neutral confirmations. Canonicalization, orchestration, reports, the response schema, and the frontend consume the two collections separately; `RuleEngine` also rejects non-visible inputs defensively.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, Pillow, pytest, vanilla JavaScript, YAML ontology.

**Branch:** `codex/sumaiguard-visible-risk-policy`

**Dependency:** Starts from `main@4fe95e2`; waiting-experience work must branch from this plan's final reviewed HEAD.

---

## File Responsibility Map

- `apps/sumai_agent/app/models.py`: public domain models and response invariants.
- `apps/sumai_agent/app/services/relationship_engine.py`: convert typed visual facts into two semantic channels.
- `apps/sumai_agent/app/services/canonicalization.py`: stable ordering, deduplication, and IDs for both channels.
- `apps/sumai_agent/app/services/rule_engine.py`: accept visible hazards only and build deterministic actions.
- `apps/sumai_agent/app/services/orchestrator.py`: assemble semantic result, hash, reports, images, and response.
- `apps/sumai_agent/app/services/report_renderer.py`: risk-only report plus neutral confirmation section.
- `apps/sumai_agent/app/knowledge_base/room_checklists.yaml`: schema and inference identity bump.
- `apps/sumai_web/app.py`: separate risk summary from neutral confirmation UI.
- `apps/sumai_agent/tests/`: RED/GREEN contract, regression, and API tests.
- `scripts/benchmark_pipeline.py`: public response schema acceptance.
- `docs/{architecture,risk_policy,decisions}.md`: durable product boundary.

### Task 1: Split Relationship Output Into Visible Findings and Confirmations

**Files:**
- Modify: `apps/sumai_agent/tests/test_relationship_engine.py`
- Modify: `apps/sumai_agent/app/models.py`
- Modify: `apps/sumai_agent/app/services/relationship_engine.py`

- [ ] **Step 1: Write failing relationship tests**

Replace tests that expect `expected_feature` entries inside `findings` with the explicit split:

```python
def test_expected_feature_becomes_neutral_confirmation_not_risk() -> None:
    result = _engine().derive(
        _facts(
            room_type="toilet",
            entities=[],
            feature_observations=[{
                "feature_key": "has_emergency_call_button",
                "state": "absent_with_full_coverage",
                "evidence_bbox": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
                "model_score": 0.91,
            }],
        )
    )

    assert result.visible_findings == []
    assert len(result.confirmation_items) == 1
    item = result.confirmation_items[0]
    assert item.feature_key == "has_emergency_call_button"
    assert item.label_ja == "緊急呼出ボタン"
    assert item.needs_human_confirmation is True
    assert "確認できませんでした" in item.description_ja
    assert "不存在" in item.description_ja
    assert not hasattr(item, "severity")
    assert not hasattr(item, "bbox")
```

Add a mixed-result test:

```python
def test_visible_and_confirmation_channels_remain_separate() -> None:
    result = _engine().derive(
        _facts(
            room_type="bedroom",
            visible_regions=["room"],
            entities=[{
                "ref": "e1",
                "ontology_key": "poor_lighting",
                "bbox": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                "visibility": "clear",
                "model_score": 0.9,
            }],
            feature_observations=[{
                "feature_key": "bedside_light",
                "state": "absent_with_full_coverage",
                "evidence_bbox": {"x": 0.6, "y": 0.1, "w": 0.2, "h": 0.2},
                "model_score": 0.9,
            }],
            relationships=[
                {"subject": "e1", "predicate": "located_in", "object": "room"}
            ],
        )
    )

    assert [item.ontology_key for item in result.visible_findings] == ["poor_lighting"]
    assert [item.feature_key for item in result.confirmation_items] == ["bedside_light"]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./.venv/bin/pytest \
  apps/sumai_agent/tests/test_relationship_engine.py -q
```

Expected: FAIL because `derive()` still returns `list[RiskFinding]` and `ConfirmationItem` does not exist.

- [ ] **Step 3: Add neutral domain models**

In `models.py`, add:

```python
class ConfirmationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    feature_key: str
    label_ja: str
    description_ja: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_source_ids: list[str] = Field(default_factory=list)
    basis_label_ja: str
    basis_summary_ja: str
    needs_human_confirmation: Literal[True] = True


class RelationshipDerivation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visible_findings: list[RiskFinding] = Field(default_factory=list)
    confirmation_items: list[ConfirmationItem] = Field(default_factory=list)
```

Add `confirmation_items: list[ConfirmationItem] = Field(default_factory=list)` to
`AnalysisResponse`. Extend its validator so not-applicable responses require empty
confirmations and applicable responses reject any finding whose
`ontology_rule_kind != "visible_hazard"`.

- [ ] **Step 4: Make `RelationshipEngine` return both channels**

Change the signature and fail-closed returns:

```python
def derive(self, facts: VisionFacts) -> RelationshipDerivation:
    empty = RelationshipDerivation()
    if facts.environment != "home" or facts.room_type not in self.ontology.room_names:
        return empty
```

Keep the visible entity loop unchanged except that it appends only to
`visible_findings`. Replace expected-feature `RiskFinding` construction with:

```python
confirmation_items.append(
    ConfirmationItem(
        id="pending",
        feature_key=rule.key,
        label_ja=expected_feature_label,
        description_ja=(
            f"現在の写真では{expected_feature_label}を確認できませんでした。"
            "住宅内に存在しないことや、追加が必要なことを示すものではありません。"
        ),
        confidence=feature.model_score,
        evidence_source_ids=list(rule.evidence_source_ids),
        basis_label_ja=rule.basis_label_ja,
        basis_summary_ja=rule.basis_summary_ja,
        needs_human_confirmation=True,
    )
)
```

Return `RelationshipDerivation(visible_findings=findings,
confirmation_items=confirmation_items)`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: all relationship tests PASS after legacy list
assertions are updated to use `.visible_findings` or `.confirmation_items`.

- [ ] **Step 6: Commit**

```bash
git add \
  apps/sumai_agent/app/models.py \
  apps/sumai_agent/app/services/relationship_engine.py \
  apps/sumai_agent/tests/test_relationship_engine.py
git commit -m "refactor: separate visible risks from confirmations"
```

### Task 2: Canonicalize Both Channels and Defend the Action Boundary

**Files:**
- Modify: `apps/sumai_agent/tests/test_canonicalization.py`
- Modify: `apps/sumai_agent/tests/test_rule_engine.py`
- Modify: `apps/sumai_agent/app/services/canonicalization.py`
- Modify: `apps/sumai_agent/app/services/rule_engine.py`

- [ ] **Step 1: Write failing canonicalization and rule tests**

```python
def test_confirmation_items_have_stable_order_and_ids() -> None:
    items = [
        ConfirmationItem(
            id="pending",
            feature_key="has_emergency_call_button",
            label_ja="緊急呼出ボタン",
            description_ja="現在の写真では確認できませんでした。",
            confidence=0.8,
            basis_label_ja="根拠B",
            basis_summary_ja="要約B",
            needs_human_confirmation=True,
        ),
        ConfirmationItem(
            id="pending",
            feature_key="has_handrail",
            label_ja="手すり",
            description_ja="現在の写真では確認できませんでした。",
            confidence=0.9,
            basis_label_ja="根拠A",
            basis_summary_ja="要約A",
            needs_human_confirmation=True,
        ),
    ]

    forward = canonicalize_confirmation_items(items)
    reverse = canonicalize_confirmation_items(list(reversed(items)))
    assert [item.model_dump() for item in forward] == [
        item.model_dump() for item in reverse
    ]
    assert [item.id for item in forward] == ["C1", "C2"]
```

```python
def test_rule_engine_rejects_expected_feature_before_actions() -> None:
    expected = _finding("toilet_missing_handrail").model_copy(
        update={
            "ontology_key": "has_handrail",
            "ontology_rule_kind": "expected_feature",
        }
    )

    findings, plan = RuleEngine().apply([expected], "toilet")
    assert findings == []
    assert plan == ActionPlan()
```

- [ ] **Step 2: Verify RED**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./.venv/bin/pytest \
  apps/sumai_agent/tests/test_canonicalization.py \
  apps/sumai_agent/tests/test_rule_engine.py -q
```

Expected: FAIL because the confirmation canonicalizer is missing and the rule engine
still converts expected-feature inputs into actions.

- [ ] **Step 3: Implement confirmation canonicalization**

Add:

```python
def canonicalize_confirmation_items(
    items: list[ConfirmationItem],
) -> list[ConfirmationItem]:
    ordered = sorted(
        (item.model_copy(deep=True) for item in items),
        key=lambda item: (
            item.feature_key,
            -item.confidence,
            item.label_ja,
            json.dumps(
                normalize_signed_zero(item.model_dump(mode="json", exclude={"id"})),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )
    unique: list[ConfirmationItem] = []
    seen: set[str] = set()
    for item in ordered:
        if item.feature_key in seen:
            continue
        seen.add(item.feature_key)
        unique.append(item)
    return [
        item.model_copy(update={"id": f"C{index}"})
        for index, item in enumerate(unique, start=1)
    ]
```

- [ ] **Step 4: Add RuleEngine defense**

At the start of the filter loop, before confidence and ontology lookup:

```python
if finding.ontology_rule_kind not in {None, "visible_hazard"}:
    continue
```

Legacy `None` remains allowed only so existing risk-type callers can be resolved to an
exact visible rule. Remove the `expected_feature` action-construction branch.

- [ ] **Step 5: Verify GREEN and commit**

Run the Step 2 command. Expected: PASS.

```bash
git add \
  apps/sumai_agent/app/services/canonicalization.py \
  apps/sumai_agent/app/services/rule_engine.py \
  apps/sumai_agent/tests/test_canonicalization.py \
  apps/sumai_agent/tests/test_rule_engine.py
git commit -m "fix: keep confirmations outside action policy"
```

### Task 3: Wire the Public Response, Risk Identity, and Cache Identity

**Files:**
- Modify: `apps/sumai_agent/tests/test_mock_analyze.py`
- Modify: `apps/sumai_agent/tests/test_idempotency.py`
- Modify: `apps/sumai_agent/tests/test_ontology.py`
- Modify: `apps/sumai_agent/tests/test_benchmark_pipeline.py`
- Modify: `apps/sumai_agent/app/services/orchestrator.py`
- Modify: `apps/sumai_agent/app/knowledge_base/room_checklists.yaml`
- Modify: `scripts/benchmark_pipeline.py`
- Modify: `apps/sumai_web/app.py`

- [ ] **Step 1: Write failing API and semantic-identity tests**

Add the complete fake provider and API regression:

```python
from app.models import (
    ActionPlan,
    ConfirmationItem,
    VisionFacts,
)
from app.services.orchestrator import (
    AnalysisOrchestrator,
    analysis_semantic_payload,
)
from app.services.canonicalization import semantic_hash


class ExpectedOnlyVision:
    async def analyze(self, **_: object) -> tuple[VisionFacts, str]:
        return (
            VisionFacts(
                environment="home",
                room_type="toilet",
                visible_regions=["room"],
                entities=[],
                feature_observations=[
                    {
                        "feature_key": "has_handrail",
                        "state": "absent_with_full_coverage",
                        "evidence_bbox": {
                            "x": 0.05, "y": 0.1, "w": 0.9, "h": 0.8
                        },
                        "model_score": 0.9,
                    },
                    {
                        "feature_key": "has_emergency_call_button",
                        "state": "absent_with_full_coverage",
                        "evidence_bbox": {
                            "x": 0.05, "y": 0.1, "w": 0.9, "h": 0.8
                        },
                        "model_score": 0.9,
                    },
                ],
                relationships=[],
            ),
            "gemini",
        )

    async def aclose(self) -> None:
        return None


def test_expected_only_response_is_zero_visible_risk(
    monkeypatch,
) -> None:
    from app import main as main_module

    monkeypatch.setattr(
        main_module,
        "orchestrator",
        AnalysisOrchestrator(vision=ExpectedOnlyVision()),
    )
    client = TestClient(main_module.app)
    payload = client.post(
        "/analyze",
        files={
            "image": (
                "toilet.png",
                _png_bytes(),
                "image/png",
            )
        },
        data={"room_hint": "toilet", "mock": "false"},
    ).json()

    assert payload["findings"] == []
    assert payload["overall_risk_level"] == "low"
    assert payload["action_plan"] == {
        "family_no_cost": [],
        "care_manager_purchase": [],
        "contractor_construction": [],
    }
    assert [
        item["feature_key"]
        for item in payload["confirmation_items"]
    ] == [
        "has_emergency_call_button",
        "has_handrail",
    ]
```

Add a semantic hash test:

```python
confirmation = ConfirmationItem(
    id="C1",
    feature_key="has_handrail",
    label_ja="手すり",
    description_ja=(
        "現在の写真では手すりを確認できませんでした。"
        "住宅内に存在しないことや、追加が必要なことを示すものではありません。"
    ),
    confidence=0.9,
    basis_label_ja="根拠",
    basis_summary_ja="要約",
    needs_human_confirmation=True,
)
base = analysis_semantic_payload(
    "toilet", [], ActionPlan(), confirmation_items=[]
)
changed = analysis_semantic_payload(
    "toilet", [], ActionPlan(), confirmation_items=[confirmation]
)
assert semantic_hash(base) != semantic_hash(changed)
```

Expect ontology versions:

```python
assert ontology.schema_version == "2.1.0"
assert ontology.inference_config_version == "1.0.5"
```

- [ ] **Step 2: Verify RED**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./.venv/bin/pytest \
  apps/sumai_agent/tests/test_mock_analyze.py \
  apps/sumai_agent/tests/test_idempotency.py \
  apps/sumai_agent/tests/test_ontology.py \
  apps/sumai_agent/tests/test_benchmark_pipeline.py -q
```

Expected: FAIL because the response and semantic payload do not include confirmations
and versions are still `2.0.0` / `1.0.4`.

- [ ] **Step 3: Wire confirmations through orchestration**

Add `confirmation_items` to `ComputedAnalysis`. Replace the derivation block with:

```python
derivation = self.relationship_engine.derive(vision_facts)
visible = canonicalize_findings(derivation.visible_findings)
confirmations = canonicalize_confirmation_items(
    derivation.confirmation_items
)
findings, action_plan = self.rule_engine.apply(visible, response_room)
```

Pass confirmations to `analysis_semantic_payload`, `ReportRenderer.render`,
`ComputedAnalysis`, and `AnalysisResponse`. Extend the semantic payload:

```python
"confirmation_items": [
    item.model_dump(mode="json") for item in confirmation_items
],
```

For not-applicable results, keep both collections empty.

- [ ] **Step 4: Bump versions and validators**

Set:

```yaml
schema_version: "2.1.0"
inference_config_version: "1.0.5"
```

Update `AnalysisResponse.schema_version` default, frontend local-abstention response,
benchmark required keys, and test fixtures. The frontend local-abstention payload must
include `"confirmation_items": []` and use the new versions. `result_key` then changes
through its existing version inputs without a new hashing algorithm.

- [ ] **Step 5: Verify GREEN and commit**

Run the Step 2 command. Expected: PASS.

```bash
git add \
  apps/sumai_agent/app/services/orchestrator.py \
  apps/sumai_agent/app/knowledge_base/room_checklists.yaml \
  apps/sumai_agent/tests/test_mock_analyze.py \
  apps/sumai_agent/tests/test_idempotency.py \
  apps/sumai_agent/tests/test_ontology.py \
  apps/sumai_agent/tests/test_benchmark_pipeline.py \
  apps/sumai_web/app.py \
  scripts/benchmark_pipeline.py
git commit -m "feat: expose neutral confirmation items"
```

### Task 4: Separate Reports and Result-Page Presentation

**Files:**
- Modify: `apps/sumai_agent/tests/test_report_renderer.py`
- Modify: `apps/sumai_agent/tests/test_frontend_contract.py`
- Modify: `apps/sumai_agent/app/services/report_renderer.py`
- Modify: `apps/sumai_web/app.py`

- [ ] **Step 1: Write failing report and frontend tests**

```python
def test_confirmation_only_result_has_zero_risk_and_no_actions() -> None:
    confirmation = ConfirmationItem(
        id="C1",
        feature_key="has_handrail",
        label_ja="手すり",
        description_ja=(
            "現在の写真では手すりを確認できませんでした。"
            "住宅内に存在しないことや、追加が必要なことを示すものではありません。"
        ),
        confidence=0.9,
        basis_label_ja="根拠",
        basis_summary_ja="要約",
        needs_human_confirmation=True,
    )
    reports = ReportRenderer().render(
        room_type="toilet",
        overall_risk_level="low",
        findings=[],
        confirmation_items=[confirmation],
        action_plan=ActionPlan(),
    )
    assert "現時点で大きな赤枠リスクは検出されませんでした" in (
        reports["risk_summary_markdown"]
    )
    assert "写真だけでは確認できない項目" in (
        reports["confirmation_items_markdown"]
    )
    assert "不存在" in reports["confirmation_items_markdown"]
    assert "###" not in reports["family_actions_markdown"]
```

Frontend contract:

```python
assert "payload.confirmation_items" in html
assert "payload.findings.length" in html
assert "可視リスク" in html
assert "btnShowSuggestions.style.display = hasVisibleFindings ? '' : 'none'" in html
assert "finding.ontology_rule_kind === 'expected_feature'" not in html
```

- [ ] **Step 2: Verify RED**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./.venv/bin/pytest \
  apps/sumai_agent/tests/test_report_renderer.py \
  apps/sumai_agent/tests/test_frontend_contract.py -q
```

Expected: FAIL because expected features are still rendered from `findings` and the
frontend still filters `ontology_rule_kind`.

- [ ] **Step 3: Implement report separation**

Add `confirmation_items_markdown` to `AnalysisResponse` and report dictionaries.
The frontend local-abstention payload must include a neutral
`confirmation_items_markdown` string as well.
Change the renderer signature:

```python
def render(
    self,
    room_type: RoomType,
    overall_risk_level: RiskLevel,
    findings: list[RiskFinding],
    confirmation_items: list[ConfirmationItem],
    action_plan: ActionPlan,
) -> dict[str, str]:
```

Render confirmations only in:

```python
def confirmations_markdown(
    self, items: list[ConfirmationItem]
) -> str:
    lines = ["## 写真だけでは確認できない項目", ""]
    if not items:
        return "\n".join(lines + ["この写真には追加の確認項目はありません。"])
    for item in items:
        lines.extend([
            f"### {item.label_ja}",
            f"- 確認結果: {item.description_ja}",
            "- 注意: 写真だけで不存在・必要性・設置位置を判断しません。",
            "",
        ])
    return "\n".join(lines).strip()
```

Delete expected-feature branches from risk and action Markdown.
Make `render_not_applicable()` return
`"confirmation_items_markdown": "## 写真だけでは確認できない項目\n\n対象外または判定不能のため、確認項目は表示していません。"`
so every public response has the same report keys.

- [ ] **Step 4: Implement frontend separation**

Rename the summary label to `可視リスク`. In `renderResults`:

```javascript
const findings = Array.isArray(payload.findings) ? payload.findings : [];
const confirmations = Array.isArray(payload.confirmation_items)
    ? payload.confirmation_items
    : [];
const hasVisibleFindings = findings.length > 0;

riskCount.textContent = `${findings.length}件`;
confirmationNote.hidden = confirmations.length === 0;
confirmationTitle.textContent =
    `写真だけでは確認できない項目：${confirmations.length}件`;
improvementCard.hidden = !hasVisibleFindings;
btnShowSuggestions.style.display = hasVisibleFindings ? '' : 'none';
```

Render a neutral confirmation body from `confirmation_items_markdown`. Keep the clean
photo visible for applicable zero-risk results.

- [ ] **Step 5: Verify GREEN and commit**

Run the Step 2 command. Expected: PASS.

```bash
git add \
  apps/sumai_agent/app/models.py \
  apps/sumai_agent/app/services/report_renderer.py \
  apps/sumai_agent/tests/test_report_renderer.py \
  apps/sumai_agent/tests/test_frontend_contract.py \
  apps/sumai_web/app.py
git commit -m "fix: present only visible hazards as risks"
```

### Task 5: Documentation, Full Regression, and Branch Review

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/risk_policy.md`
- Modify: `docs/decisions.md`
- Modify: `apps/sumai_agent/tests/test_documentation_contract.py`

- [ ] **Step 1: Add failing documentation assertions**

```python
assert "`findings` contains only `visible_hazard`" in risk_policy
assert "`confirmation_items` never affects overall risk" in risk_policy
assert "A photo-scoped non-detection does not create an action" in decisions
```

- [ ] **Step 2: Verify RED**

```bash
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./.venv/bin/pytest \
  apps/sumai_agent/tests/test_documentation_contract.py -q
```

Expected: FAIL until the durable documents state the new contract.

- [ ] **Step 3: Update documentation and verify GREEN**

Document the two-channel flow, zero-risk applicable state, schema `2.1.0`, inference
config `1.0.5`, action exclusion, and the actual-photo evidence limitation. Run the
Step 2 command. Expected: PASS.

- [ ] **Step 4: Run the full gate**

```bash
git diff --check
PATH=/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH \
  ./scripts/test_all.sh
```

Expected: all pytest tests PASS, `frontend import ok`, and
`docker compose config ok`.

- [ ] **Step 5: Review scope and commit**

```bash
git diff --stat main...HEAD
git diff --name-only main...HEAD
git status --short --branch
```

Confirm no files under `docs/preconsultation/` changed.

```bash
git add \
  docs/architecture.md \
  docs/risk_policy.md \
  docs/decisions.md \
  apps/sumai_agent/tests/test_documentation_contract.py
git commit -m "docs: codify visible-risk-only outputs"
```

- [ ] **Step 6: Independent review gate**

Request a code review focused on:

```text
Check that expected-feature non-detections cannot affect findings, risk level,
overlays, reports, actions, or suggestion navigation. Check semantic hash and
result-key versioning, not-applicable invariants, and backward compatibility.
Report P0-P3 findings with file and line evidence.
```

Fix all P0-P2 issues with new RED/GREEN cycles, rerun `./scripts/test_all.sh`, and
record the reviewed HEAD. Do not push or deploy this branch until the review is clean.
