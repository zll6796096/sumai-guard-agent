from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RoomType = Literal["genkan", "hallway", "bathroom", "toilet", "bedroom", "kitchen", "auto"]
RiskLevel = Literal["low", "medium", "high"]
ActionTier = Literal[
    "FAMILY_NO_COST",
    "CARE_MANAGER_PURCHASE",
    "CONTRACTOR_CONSTRUCTION",
]
CostLevel = Literal["ZERO", "LOW", "MEDIUM", "HIGH"]


class BoundingBox(BaseModel):
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    w: float = Field(..., ge=0.0, le=1.0)
    h: float = Field(..., ge=0.0, le=1.0)


class RiskFinding(BaseModel):
    id: str
    risk_type: str
    label_ja: str
    description_ja: str
    severity: int = Field(..., ge=1, le=5)
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: BoundingBox
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


class VisionResult(BaseModel):
    room_type: RoomType
    findings: list[RiskFinding] = Field(default_factory=list)
    is_home_environment: bool = True
    not_applicable_reason_ja: str | None = None
