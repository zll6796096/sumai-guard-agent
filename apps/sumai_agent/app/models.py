from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RoomType = Literal["genkan", "hallway", "bathroom", "toilet", "bedroom", "kitchen", "auto"]
RiskLevel = Literal["low", "medium", "high"]
ActionTier = Literal[
    "FAMILY_NO_COST",
    "CARE_MANAGER_PURCHASE",
    "CONTRACTOR_CONSTRUCTION",
]
CostLevel = Literal["ZERO", "LOW", "MEDIUM", "HIGH"]


class BoundingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    w: float = Field(..., ge=0.0, le=1.0)
    h: float = Field(..., ge=0.0, le=1.0)


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


class AnalysisResponse(BaseModel):
    analysis_id: str
    room_type: RoomType
    overall_risk_level: RiskLevel
    findings: list[RiskFinding]
    action_plan: ActionPlan
    annotated_image_base64: str
    improvement_image_base64: str
    risk_summary_markdown: str
    family_actions_markdown: str
    care_manager_actions_markdown: str
    contractor_actions_markdown: str
    disclaimer_ja: str
    mode: str = "mock"
    is_home_environment: bool = True
    not_applicable_reason_ja: str | None = None
    model: str = "N/A"
    result_key: str = ""
    semantic_hash: str = ""
    schema_version: str = "2.0.0"
    ontology_version: str = "1.0.0"
    preprocess_version: str = "1.0.0"
    inference_config_version: str = "1.0.0"
    stage_timings_ms: dict[str, int] = Field(default_factory=dict)


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
