from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


RoomType = Literal["genkan", "hallway", "bathroom", "toilet", "bedroom", "kitchen", "auto"]
RiskLevel = Literal["low", "medium", "high"]
AssessmentStatus = Literal[
    "visible_risks_found",
    "needs_on_site_confirmation",
    "no_visible_risks_found",
    "not_applicable",
]
ActionTier = Literal[
    "FAMILY_NO_COST",
    "CARE_MANAGER_PURCHASE",
    "CONTRACTOR_CONSTRUCTION",
]
CostLevel = Literal["ZERO", "LOW", "MEDIUM", "HIGH"]


@lru_cache(maxsize=1)
def _default_visible_finding_identities() -> frozenset[tuple[str, str, str]]:
    from app.ontology import OntologyRepository

    ontology = OntologyRepository.load_default()
    identities: set[tuple[str, str, str]] = set()
    for room in ontology.room_names:
        room_data = ontology.room(room)
        if room_data is None:
            raise ValueError("default_ontology_room_missing")
        identities.update(
            (room, str(item["key"]), str(item["risk_type"]))
            for item in room_data["visible_hazards"]
        )
    return frozenset(identities)


@lru_cache(maxsize=1)
def _default_expected_confirmation_identities() -> frozenset[tuple[str, str]]:
    from app.ontology import OntologyRepository

    ontology = OntologyRepository.load_default()
    identities: set[tuple[str, str]] = set()
    for room in ontology.room_names:
        room_data = ontology.room(room)
        if room_data is None:
            raise ValueError("default_ontology_room_missing")
        identities.update(
            (room, str(item["key"]))
            for item in room_data["expected_features"]
        )
    return frozenset(identities)


@lru_cache(maxsize=1)
def _default_family_forbidden_words() -> tuple[str, ...]:
    from app.ontology import OntologyRepository

    ontology = OntologyRepository.load_default()
    family_policy = ontology.action_policy.get("family", {})
    words = family_policy.get("forbidden_words", ())
    if not isinstance(words, (list, tuple)) or not all(
        isinstance(word, str) and word for word in words
    ):
        raise ValueError("default_family_policy_invalid")
    return tuple(words)


class BoundingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    w: float = Field(..., gt=0.0, le=1.0)
    h: float = Field(..., gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _must_fit_normalized_frame(self) -> "BoundingBox":
        tolerance = 1e-9
        if self.x + self.w > 1.0 + tolerance or self.y + self.h > 1.0 + tolerance:
            raise ValueError("bounding_box_must_fit_normalized_frame")
        return self


EnvironmentType = Literal["home", "non_home", "uncertain"]
DetectedRoomType = Literal[
    "genkan", "hallway", "bathroom", "toilet", "bedroom", "kitchen", "unknown"
]
VisibilityState = Literal["clear", "partial", "uncertain"]
FeatureState = Literal["present", "absent_with_full_coverage", "cannot_determine"]


class VisionEntity(BaseModel):
    """Provider evidence only; this model contains no risk or action policy."""

    model_config = ConfigDict(extra="forbid")

    ref: str = Field(min_length=1, max_length=32)
    ontology_key: str
    bbox: BoundingBox
    visibility: VisibilityState
    model_score: float = Field(ge=0.0, le=1.0)


class FeatureObservation(BaseModel):
    """An observed feature state, without interpreting it as a risk."""

    model_config = ConfigDict(extra="forbid")

    feature_key: str
    state: FeatureState
    evidence_bbox: BoundingBox | None = None
    model_score: float = Field(ge=0.0, le=1.0)


class VisionRelationship(BaseModel):
    """A relation among visible references; policy inference belongs downstream."""

    model_config = ConfigDict(extra="forbid")

    subject: str
    predicate: str
    object: str


class VisionFacts(BaseModel):
    """Minimal, typed visual facts returned by Gemini before deterministic policy."""

    model_config = ConfigDict(extra="forbid")

    environment: EnvironmentType
    room_type: DetectedRoomType
    visible_regions: list[str] = Field(default_factory=list)
    entities: list[VisionEntity] = Field(default_factory=list)
    feature_observations: list[FeatureObservation] = Field(default_factory=list)
    relationships: list[VisionRelationship] = Field(default_factory=list)
    not_applicable_reason_code: str | None = None


class RiskFinding(BaseModel):
    id: str
    risk_type: str
    label_ja: str
    description_ja: str
    severity: int = Field(..., ge=1, le=5)
    confidence: float = Field(..., ge=0.0, le=1.0)
    # Evidence coordinates are immutable analysis evidence; display_bbox is presentation-only.
    bbox: BoundingBox
    display_bbox: BoundingBox | None = None
    evidence_source_ids: list[str] = Field(default_factory=list)
    evidence_ja: str
    basis_label_ja: str
    basis_summary_ja: str
    needs_human_confirmation: bool
    # Exact ontology identity is mandatory on the relationship path. Optional
    # values preserve compatibility with legacy callers that only know risk_type.
    ontology_key: str | None = None
    ontology_rule_kind: Literal["visible_hazard", "expected_feature"] | None = None


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


class ActionItem(BaseModel):
    id: str
    risk_id: str
    tier: ActionTier
    title_ja: str
    description_ja: str
    why_ja: str
    cost_level: CostLevel
    requires_professional: bool
    disclaimer_ja: str


class ActionPlan(BaseModel):
    family_no_cost: list[ActionItem] = Field(default_factory=list)
    care_manager_purchase: list[ActionItem] = Field(default_factory=list)
    contractor_construction: list[ActionItem] = Field(default_factory=list)


def _risk_level_for_findings(findings: list[RiskFinding]) -> RiskLevel:
    if not findings:
        return "low"
    maximum = max(finding.severity for finding in findings)
    if maximum >= 4:
        return "high"
    if maximum >= 2:
        return "medium"
    return "low"


def assessment_status_for_evidence(
    *,
    is_not_applicable: bool,
    findings: list[RiskFinding],
    confirmation_items: list[ConfirmationItem],
) -> AssessmentStatus:
    if is_not_applicable:
        return "not_applicable"
    if findings:
        return "visible_risks_found"
    if confirmation_items:
        return "needs_on_site_confirmation"
    return "no_visible_risks_found"


def _validate_action_plan(
    action_plan: ActionPlan,
    finding_ids: set[str],
) -> None:
    policies = (
        (
            action_plan.family_no_cost,
            "FAMILY_NO_COST",
            "ZERO",
            False,
        ),
        (
            action_plan.care_manager_purchase,
            "CARE_MANAGER_PURCHASE",
            "LOW",
            True,
        ),
        (
            action_plan.contractor_construction,
            "CONTRACTOR_CONSTRUCTION",
            "HIGH",
            True,
        ),
    )
    action_ids: set[str] = set()
    for actions, tier, cost_level, requires_professional in policies:
        for action in actions:
            if action.id in action_ids:
                raise ValueError("action_ids_must_be_unique")
            action_ids.add(action.id)
            if action.risk_id not in finding_ids:
                raise ValueError("action_risk_id_must_reference_finding")
            if action.tier != tier:
                raise ValueError("action_must_match_plan_tier")
            if (
                action.cost_level != cost_level
                or action.requires_professional is not requires_professional
            ):
                raise ValueError("action_must_match_plan_policy")
            if tier == "FAMILY_NO_COST":
                text = " ".join(
                    (action.title_ja, action.description_ja, action.why_ja)
                )
                if any(
                    forbidden in text
                    for forbidden in _default_family_forbidden_words()
                ):
                    raise ValueError("family_action_contains_forbidden_word")


class AnalysisResponse(BaseModel):
    """Validated public response with request-local logging metadata kept private."""

    _cache_hit: bool = PrivateAttr(default=False)

    analysis_id: str
    room_type: RoomType
    assessment_status: AssessmentStatus
    overall_risk_level: RiskLevel
    findings: list[RiskFinding]
    confirmation_items: list[ConfirmationItem] = Field(default_factory=list)
    action_plan: ActionPlan
    annotated_image_base64: str
    improvement_image_base64: str
    risk_summary_markdown: str
    confirmation_items_markdown: str = Field(min_length=1)
    family_actions_markdown: str
    care_manager_actions_markdown: str
    contractor_actions_markdown: str
    disclaimer_ja: str
    mode: str = "mock"
    is_home_environment: bool = True
    is_not_applicable: bool = False
    not_applicable_reason_ja: str | None = None
    model: str = "N/A"
    result_key: str = ""
    semantic_hash: str = ""
    schema_version: str = "2.2.0"
    ontology_version: str = "1.0.1"
    preprocess_version: str = "1.0.0"
    inference_config_version: str = "1.0.6"
    stage_timings_ms: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_applicability_state(self) -> "AnalysisResponse":
        if self.is_not_applicable:
            if self.room_type != "auto" or self.overall_risk_level != "low":
                raise ValueError("not_applicable_requires_auto_room_and_low_risk")
            if self.findings or self.confirmation_items or any((
                self.action_plan.family_no_cost,
                self.action_plan.care_manager_purchase,
                self.action_plan.contractor_construction,
            )):
                raise ValueError("not_applicable_requires_empty_findings_and_actions")
            if not isinstance(self.not_applicable_reason_ja, str) or not self.not_applicable_reason_ja.strip():
                raise ValueError("not_applicable_requires_reason")
        elif (
            not self.is_home_environment
            or self.room_type == "auto"
            or self.not_applicable_reason_ja is not None
        ):
            raise ValueError("applicable_response_requires_home_known_room_and_no_reason")
        elif any(
            not finding.ontology_key
            or not finding.ontology_key.strip()
            or finding.ontology_rule_kind != "visible_hazard"
            for finding in self.findings
        ):
            raise ValueError("applicable_findings_must_be_visible_hazards")
        elif any(
            (
                self.room_type,
                finding.ontology_key or "",
                finding.risk_type,
            )
            not in _default_visible_finding_identities()
            for finding in self.findings
        ):
            raise ValueError("applicable_findings_must_match_visible_ontology")
        elif any(
            (self.room_type, item.feature_key)
            not in _default_expected_confirmation_identities()
            for item in self.confirmation_items
        ):
            raise ValueError(
                "applicable_confirmation_items_must_match_expected_ontology"
            )

        finding_ids = [finding.id for finding in self.findings]
        if finding_ids != [
            f"R{index}" for index in range(1, len(finding_ids) + 1)
        ]:
            raise ValueError("finding_ids_must_be_canonical")
        confirmation_ids = [item.id for item in self.confirmation_items]
        if confirmation_ids != [
            f"C{index}" for index in range(1, len(confirmation_ids) + 1)
        ]:
            raise ValueError("confirmation_ids_must_be_canonical")
        confirmation_feature_keys = [
            item.feature_key for item in self.confirmation_items
        ]
        if len(set(confirmation_feature_keys)) != len(
            confirmation_feature_keys
        ):
            raise ValueError("confirmation_feature_keys_must_be_unique")
        if self.overall_risk_level != _risk_level_for_findings(self.findings):
            raise ValueError("overall_risk_level_must_match_findings")
        if self.assessment_status != assessment_status_for_evidence(
            is_not_applicable=self.is_not_applicable,
            findings=self.findings,
            confirmation_items=self.confirmation_items,
        ):
            raise ValueError("assessment_status_must_match_evidence_state")
        actions = (
            self.action_plan.family_no_cost
            + self.action_plan.care_manager_purchase
            + self.action_plan.contractor_construction
        )
        if not self.findings and actions:
            raise ValueError("zero_findings_require_empty_actions")
        _validate_action_plan(
            self.action_plan,
            set(finding_ids),
        )
        return self


class MissingSafetyFeature(BaseModel):
    feature_key: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: BoundingBox
    evidence_ja: str


class VisionResult(BaseModel):
    room_type: RoomType
    is_home_environment: bool = True
    observations: dict[str, bool | None] = Field(default_factory=dict)
    visible_hazards: list[RiskFinding] = Field(default_factory=list)
    missing_safety_features: list[MissingSafetyFeature] = Field(default_factory=list)
    not_applicable_reason_ja: str | None = None

    @property
    def findings(self) -> list[RiskFinding]:
        return self.visible_hazards
