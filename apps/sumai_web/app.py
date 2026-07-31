from __future__ import annotations

import base64
import codecs
import hashlib
import io
import json
import logging
import math
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from dotenv import load_dotenv
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator


load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("sumai.web")

SUMAI_AGENT_URL = os.getenv("SUMAI_AGENT_URL", "http://localhost:8080").rstrip("/")
SUMAI_WEB_PORT = int(os.getenv("SUMAI_WEB_PORT", "8081"))
FRONTEND_MOCK = os.getenv("MOCK_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}

_backend_client: httpx.AsyncClient | None = None

DISCLAIMER = (
    "POC版です。医療・介護・施工判断を代替しません。\n"
    "改善イメージはコミュニケーション用であり施工図ではありません。\n"
    "写真から正確な寸法や適用制度を判断するものではありません。"
)

CURRENT_SCHEMA_VERSION = "2.2.0"
CURRENT_ONTOLOGY_VERSION = "1.0.1"
CURRENT_PREPROCESS_VERSION = "1.0.0"
CURRENT_INFERENCE_CONFIG_VERSION = "1.0.6"

CURRENT_VISIBLE_FINDING_IDENTITIES = frozenset(
    {
        ("toilet", "has_floor_clutter", "cluttered_path"),
        ("toilet", "has_loose_mat", "loose_mat"),
        ("toilet", "lighting_poor", "poor_lighting"),
        ("bathroom", "wet_floor", "bathroom_slip"),
        ("bathroom", "bathtub_stepover", "bathtub_stepover"),
        ("bathroom", "cluttered_floor", "cluttered_path"),
        ("genkan", "genkan_step", "genkan_step"),
        ("genkan", "loose_shoes", "cluttered_path"),
        ("genkan", "poor_lighting", "poor_lighting"),
        ("genkan", "cluttered_path", "cluttered_path"),
        ("hallway", "hallway_cord", "hallway_cord"),
        ("hallway", "cluttered_path", "cluttered_path"),
        ("hallway", "loose_mat", "loose_mat"),
        ("hallway", "poor_lighting", "poor_lighting"),
        ("bedroom", "cluttered_path", "cluttered_path"),
        ("bedroom", "loose_mat", "loose_mat"),
        ("bedroom", "poor_lighting", "poor_lighting"),
        ("kitchen", "loose_mat", "loose_mat"),
        ("kitchen", "cluttered_path", "cluttered_path"),
    }
)
CURRENT_EXPECTED_CONFIRMATION_IDENTITIES = frozenset(
    {
        ("toilet", "has_handrail"),
        ("toilet", "has_emergency_call_button"),
        ("bathroom", "has_handrail"),
        ("bathroom", "has_non_slip_floor_or_mat"),
        ("bathroom", "has_bath_transfer_support"),
        ("bathroom", "has_emergency_call_button"),
        ("bathroom", "has_shower_chair"),
        ("genkan", "has_handrail_or_support"),
        ("genkan", "step_visible_marking"),
        ("hallway", "clear_path"),
        ("hallway", "sufficient_lighting"),
        ("bedroom", "clear_path_from_bed"),
        ("bedroom", "bedside_light"),
        ("bedroom", "stable_bedside_support"),
        ("kitchen", "clear_floor"),
        ("kitchen", "stable_working_path"),
    }
)
CURRENT_FAMILY_FORBIDDEN_WORDS = (
    "購入",
    "レンタル",
    "工事",
    "施工",
    "設置を依頼",
    "専門",
)


class WireBoundingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _fits_frame(self) -> "WireBoundingBox":
        if self.x + self.w > 1.0 + 1e-9 or self.y + self.h > 1.0 + 1e-9:
            raise ValueError("bbox_outside_frame")
        return self


class WireFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    risk_type: str
    label_ja: str
    description_ja: str
    severity: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: WireBoundingBox
    display_bbox: WireBoundingBox | None = None
    evidence_source_ids: list[str] = Field(default_factory=list)
    evidence_ja: str
    basis_label_ja: str
    basis_summary_ja: str
    needs_human_confirmation: bool
    ontology_key: str | None = None
    ontology_rule_kind: Literal[
        "visible_hazard", "expected_feature"
    ] | None = None


class WireConfirmationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    feature_key: str
    label_ja: str
    description_ja: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_source_ids: list[str] = Field(default_factory=list)
    basis_label_ja: str
    basis_summary_ja: str
    needs_human_confirmation: Literal[True]


class WireActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    risk_id: str
    tier: Literal[
        "FAMILY_NO_COST",
        "CARE_MANAGER_PURCHASE",
        "CONTRACTOR_CONSTRUCTION",
    ]
    title_ja: str
    description_ja: str
    why_ja: str
    cost_level: Literal["ZERO", "LOW", "MEDIUM", "HIGH"]
    requires_professional: bool
    disclaimer_ja: str


class WireActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family_no_cost: list[WireActionItem] = Field(default_factory=list)
    care_manager_purchase: list[WireActionItem] = Field(default_factory=list)
    contractor_construction: list[WireActionItem] = Field(default_factory=list)


class WireAnalysisResponse(BaseModel):
    """Web-side copy of the Agent's public AnalysisResponse wire contract."""

    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    room_type: Literal[
        "genkan",
        "hallway",
        "bathroom",
        "toilet",
        "bedroom",
        "kitchen",
        "auto",
    ]
    assessment_status: Literal[
        "visible_risks_found",
        "needs_on_site_confirmation",
        "no_visible_risks_found",
        "not_applicable",
    ]
    overall_risk_level: Literal["low", "medium", "high"]
    findings: list[WireFinding]
    confirmation_items: list[WireConfirmationItem] = Field(
        default_factory=list
    )
    action_plan: WireActionPlan
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
    schema_version: str = CURRENT_SCHEMA_VERSION
    ontology_version: str = CURRENT_ONTOLOGY_VERSION
    preprocess_version: str = CURRENT_PREPROCESS_VERSION
    inference_config_version: str = CURRENT_INFERENCE_CONFIG_VERSION
    stage_timings_ms: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _public_invariants(self) -> "WireAnalysisResponse":
        if (
            self.schema_version != CURRENT_SCHEMA_VERSION
            or self.ontology_version != CURRENT_ONTOLOGY_VERSION
            or self.preprocess_version != CURRENT_PREPROCESS_VERSION
            or self.inference_config_version
            != CURRENT_INFERENCE_CONFIG_VERSION
        ):
            raise ValueError("response_contract_version_mismatch")
        actions = (
            self.action_plan.family_no_cost
            + self.action_plan.care_manager_purchase
            + self.action_plan.contractor_construction
        )
        action_ids = [action.id for action in actions]
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("action_ids_must_be_unique")
        for action in self.action_plan.family_no_cost:
            action_text = " ".join(
                (action.title_ja, action.description_ja, action.why_ja)
            )
            if any(
                forbidden in action_text
                for forbidden in CURRENT_FAMILY_FORBIDDEN_WORDS
            ):
                raise ValueError("family_action_contains_forbidden_word")
        if self.is_not_applicable:
            if (
                self.room_type != "auto"
                or self.assessment_status != "not_applicable"
                or self.overall_risk_level != "low"
                or self.findings
                or self.confirmation_items
                or actions
                or not isinstance(self.not_applicable_reason_ja, str)
                or not self.not_applicable_reason_ja.strip()
            ):
                raise ValueError("invalid_not_applicable_response")
            return self

        if (
            not self.is_home_environment
            or self.room_type == "auto"
            or self.not_applicable_reason_ja is not None
        ):
            raise ValueError("invalid_applicable_response")
        if any(
            not finding.ontology_key
            or finding.ontology_rule_kind != "visible_hazard"
            for finding in self.findings
        ):
            raise ValueError("findings_must_be_visible_hazards")
        if any(
            (
                self.room_type,
                finding.ontology_key or "",
                finding.risk_type,
            )
            not in CURRENT_VISIBLE_FINDING_IDENTITIES
            for finding in self.findings
        ):
            raise ValueError("finding_identity_not_allowed_for_room")
        if any(
            (self.room_type, item.feature_key)
            not in CURRENT_EXPECTED_CONFIRMATION_IDENTITIES
            for item in self.confirmation_items
        ):
            raise ValueError("confirmation_identity_not_allowed_for_room")
        if [finding.id for finding in self.findings] != [
            f"R{index}" for index in range(1, len(self.findings) + 1)
        ]:
            raise ValueError("invalid_finding_ids")
        if [item.id for item in self.confirmation_items] != [
            f"C{index}"
            for index in range(1, len(self.confirmation_items) + 1)
        ]:
            raise ValueError("invalid_confirmation_ids")
        confirmation_features = [
            item.feature_key for item in self.confirmation_items
        ]
        if len(set(confirmation_features)) != len(confirmation_features):
            raise ValueError("confirmation_feature_keys_must_be_unique")
        expected_risk = "low"
        if self.findings:
            maximum = max(finding.severity for finding in self.findings)
            expected_risk = (
                "high" if maximum >= 4 else "medium" if maximum >= 2 else "low"
            )
        if self.overall_risk_level != expected_risk:
            raise ValueError("risk_level_mismatch")
        expected_assessment = (
            "visible_risks_found"
            if self.findings
            else "needs_on_site_confirmation"
            if self.confirmation_items
            else "no_visible_risks_found"
        )
        if self.assessment_status != expected_assessment:
            raise ValueError("assessment_status_mismatch")
        finding_ids = {finding.id for finding in self.findings}
        if not finding_ids and actions:
            raise ValueError("zero_findings_require_empty_actions")
        policies = (
            (
                self.action_plan.family_no_cost,
                "FAMILY_NO_COST",
                "ZERO",
                False,
            ),
            (
                self.action_plan.care_manager_purchase,
                "CARE_MANAGER_PURCHASE",
                "LOW",
                True,
            ),
            (
                self.action_plan.contractor_construction,
                "CONTRACTOR_CONSTRUCTION",
                "HIGH",
                True,
            ),
        )
        for items, tier, cost, professional in policies:
            if any(
                item.risk_id not in finding_ids
                or item.tier != tier
                or item.cost_level != cost
                or item.requires_professional is not professional
                for item in items
            ):
                raise ValueError("action_plan_policy_mismatch")
        return self


# HTML Template with mobile-first CSS and vanilla JS
INDEX_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>親の家 安全チェックAI</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            color-scheme: light;
            --system-bg: #F5F5F7;
            --surface: #FFFFFF;
            --surface-muted: #F2F2F7;
            --text-primary: #1D1D1F;
            --text-secondary: #6E6E73;
            --separator: rgba(60, 60, 67, 0.16);
            --system-blue: #007AFF;
            --system-blue-pressed: #0062CC;
            --system-green: #248A3D;
            --system-orange: #C93400;
            --system-red: #D70015;
            --control-min-height: 44px;
            --card-radius: 20px;
            --control-radius: 14px;
            --page-shadow: 0 24px 64px rgba(0, 0, 0, 0.12);
            --bg-gradient: linear-gradient(180deg, #FFFFFF 0%, #F5F5F7 100%);
            --card-bg: var(--surface);
            --text-color: var(--text-primary);
            --text-muted: var(--text-secondary);
            --primary-color: var(--system-blue);
            --secondary-color: var(--system-blue);
            --border-color: var(--separator);
            --danger-color: var(--system-red);
            --success-color: var(--system-green);
            --warning-color: var(--system-orange);
            --accent-green: var(--system-green);
            --accent-blue: var(--system-blue);
            --accent-red: var(--system-red);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            background:
                radial-gradient(circle at 50% 0%, rgba(0, 122, 255, 0.10), transparent 34rem),
                var(--system-bg);
            font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans",
                "Hiragino Kaku Gothic ProN", "Noto Sans JP", sans-serif;
            color: var(--text-color);
            min-height: 100vh;
            min-height: 100dvh;
            display: flex;
            justify-content: center;
            align-items: center;
            -webkit-font-smoothing: antialiased;
            text-rendering: optimizeLegibility;
        }

        #app-container {
            width: 100%;
            max-width: 480px;
            height: 100vh;
            height: 100dvh;
            background: var(--bg-gradient);
            display: flex;
            flex-direction: column;
            position: relative;
            overflow: hidden;
            border-radius: 0;
        }

        @media (min-width: 481px) {
            #app-container {
                height: min(900px, calc(100dvh - 40px));
                border-radius: 30px;
                border: 1px solid var(--border-color);
                box-shadow: var(--page-shadow);
            }
        }

        .screen {
            width: 100%;
            height: 100%;
            display: none;
            flex-direction: column;
            padding: max(20px, env(safe-area-inset-top)) 20px
                max(20px, env(safe-area-inset-bottom));
            position: absolute;
            top: 0;
            left: 0;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
        }

        .screen.active {
            display: flex;
        }

        [hidden] {
            display: none !important;
        }

        :focus-visible {
            outline: 3px solid rgba(0, 122, 255, 0.45);
            outline-offset: 3px;
        }

        [data-screen-title]:focus {
            outline: none;
        }

        /* Screen 1: Home */
        #screen-home {
            overflow-y: auto;
            justify-content: flex-start;
        }

        .home-header {
            text-align: left;
            margin-top: 4px;
            margin-bottom: 20px;
        }

        .app-tag {
            display: inline-block;
            font-size: 0.78rem;
            font-weight: 700;
            color: var(--primary-color);
            background-color: rgba(0, 122, 255, 0.10);
            padding: 5px 10px;
            border-radius: 999px;
            margin-bottom: 12px;
            letter-spacing: 0.02em;
        }

        .home-title {
            font-size: clamp(1.75rem, 8vw, 2.15rem);
            font-weight: 750;
            letter-spacing: -0.035em;
            line-height: 1.2;
            color: var(--text-color);
            margin-bottom: 10px;
        }

        .home-lead {
            max-width: 24rem;
            font-size: 0.98rem;
            line-height: 1.65;
            color: var(--text-muted);
        }

        /* Place Grid */
        .place-section-title {
            font-size: 0.82rem;
            font-weight: 700;
            color: var(--text-muted);
            margin-bottom: 10px;
            text-align: left;
        }

        .place-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-bottom: 12px;
        }

        .place-block {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background-color: var(--surface);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            min-height: 76px;
            padding: 10px 4px;
            gap: 6px;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
        }

        .place-block svg {
            width: 24px;
            height: 24px;
            color: var(--secondary-color);
        }

        .place-block span {
            font-size: 0.76rem;
            font-weight: 600;
            color: var(--text-color);
        }

        .shooting-hint {
            font-size: 0.82rem;
            line-height: 1.5;
            color: var(--text-muted);
            text-align: left;
            margin-bottom: 14px;
        }

        .home-controls {
            margin: 0;
        }

        .control-group {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 10px 16px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .control-label {
            font-size: 0.85rem;
            font-weight: 700;
            color: var(--text-muted);
        }

        .room-dropdown {
            background: transparent;
            border: none;
            color: var(--text-color);
            font-size: 0.9rem;
            font-weight: 700;
            outline: none;
            text-align: right;
            cursor: pointer;
            width: 120px;
            direction: rtl;
        }

        .room-dropdown option {
            background-color: var(--surface);
            color: var(--text-color);
            direction: ltr;
        }

        .guidance-text {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-align: center;
            line-height: 1.4;
            background-color: var(--surface-muted);
            border-radius: 8px;
            padding: 8px;
            border: 1px dashed var(--border-color);
        }

        .error-message {
            background-color: rgba(239, 68, 68, 0.12);
            border: 1px solid var(--danger-color);
            color: var(--danger-color);
            border-radius: 8px;
            padding: 8px 12px;
            font-size: 0.75rem;
            text-align: center;
            margin-top: 10px;
            font-weight: bold;
        }

        .home-footer {
            margin-top: auto;
            padding-top: 4px;
            margin-bottom: 4px;
        }

        .trust-card {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 16px;
            padding: 14px;
            background: var(--surface);
            border: 1px solid var(--border-color);
            border-radius: 16px;
        }

        .trust-item {
            min-width: 0;
        }

        .trust-label {
            display: block;
            margin-bottom: 3px;
            color: var(--text-muted);
            font-size: 0.72rem;
            font-weight: 600;
        }

        .trust-value {
            display: block;
            color: var(--text-color);
            font-size: 0.82rem;
            font-weight: 700;
            line-height: 1.35;
        }

        .trust-note {
            grid-column: 1 / -1;
            padding-top: 10px;
            border-top: 1px solid var(--border-color);
            color: var(--text-muted);
            font-size: 0.76rem;
            line-height: 1.5;
        }

        /* Enlarge Image Preview State */
        .compact-preview-wrapper {
            position: relative;
            width: 80%;
            height: 260px;
            margin: 0 auto 16px auto;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid var(--border-color);
            background-color: var(--card-bg);
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .compact-preview-wrapper img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }

        .btn-clear-x {
            position: absolute;
            top: 4px;
            right: 4px;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background-color: rgba(0,0,0,0.6);
            color: white;
            border: none;
            font-size: 14px;
            line-height: 20px;
            text-align: center;
            cursor: pointer;
            font-weight: bold;
        }

        .btn {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            min-height: var(--control-min-height);
            height: 52px;
            border-radius: var(--control-radius);
            font-size: 1rem;
            font-weight: 700;
            border: none;
            cursor: pointer;
            transition: transform 0.16s ease, background-color 0.16s ease,
                box-shadow 0.16s ease;
            box-sizing: border-box;
            margin-bottom: 10px;
            text-decoration: none;
        }

        .btn:active {
            transform: scale(0.98);
        }

        .btn-primary {
            background-color: var(--primary-color);
            color: white;
            box-shadow: 0 8px 20px rgba(0, 122, 255, 0.22);
        }

        .btn-primary:active {
            background-color: var(--system-blue-pressed);
        }

        .btn-secondary {
            background-color: var(--surface);
            color: var(--primary-color);
            border: 1px solid var(--border-color);
            box-shadow: none;
        }

        .btn-secondary:active {
            background-color: var(--surface-muted);
        }

        .btn-outline {
            background-color: transparent;
            border: 1px solid var(--border-color);
            color: var(--text-color);
        }

        .btn-outline:active {
            background-color: var(--surface-muted);
        }

        .btn-icon {
            width: 18px;
            height: 18px;
            margin-right: 8px;
        }

        .disclaimer-text {
            font-size: 0.78rem;
            color: var(--text-muted);
            text-align: center;
            line-height: 1.5;
        }

        /* Screen: Result & Analyzing */
        .large-preview-wrapper {
            width: 100%;
            max-height: 46svh;
            border-radius: var(--card-radius);
            overflow: hidden;
            border: 1px solid var(--border-color);
            background-color: var(--card-bg);
            display: flex;
            justify-content: center;
            align-items: center;
            margin-bottom: 16px;
            position: relative;
        }

        .large-preview-wrapper img {
            width: 100%;
            height: auto;
            max-height: 46svh;
            object-fit: contain;
            display: block;
            border-radius: 12px;
        }

        .analysis-scan-overlay {
            position: absolute;
            inset: 0;
            overflow: hidden;
            pointer-events: none;
            border-radius: inherit;
        }

        .analysis-scan-line {
            position: absolute;
            top: 8%;
            left: 8%;
            width: 84%;
            height: 2px;
            border-radius: 999px;
            background-color: rgba(0, 122, 255, 0.72);
            animation: analysis-scan 2.8s ease-in-out infinite;
        }

        @keyframes analysis-scan {
            0%, 100% {
                top: 8%;
                opacity: 0.34;
            }
            50% {
                top: 92%;
                opacity: 0.78;
            }
        }

        .analysis-activity {
            position: relative;
            width: 100%;
            height: 4px;
            margin: -2px 0 16px;
            overflow: hidden;
            border-radius: 999px;
            background-color: rgba(0, 122, 255, 0.14);
        }

        .analysis-activity::after {
            content: "";
            position: absolute;
            left: -34%;
            width: 34%;
            height: 100%;
            border-radius: inherit;
            background-color: var(--primary-color);
            animation: analysis-activity 1.55s ease-in-out infinite;
        }

        @keyframes analysis-activity {
            0% {
                transform: translateX(0);
            }
            100% {
                transform: translateX(394%);
            }
        }

        .analyzing-status-box {
            text-align: left;
        }

        .analyzing-subtitle {
            font-size: 0.95rem;
            font-weight: 700;
            color: var(--text-color);
            margin-bottom: 12px;
        }

        .analysis-stages {
            list-style: none;
            background-color: var(--surface);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 8px 14px;
            margin-bottom: 12px;
        }

        .analysis-stage {
            position: relative;
            min-height: 38px;
            padding: 9px 0 9px 32px;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.84rem;
            font-weight: 600;
            color: var(--text-muted);
            transition: color 0.2s ease;
        }

        .analysis-stage:last-child {
            border-bottom: 0;
        }

        .analysis-stage::before {
            content: "";
            position: absolute;
            top: 50%;
            left: 4px;
            width: 13px;
            height: 13px;
            border: 2px solid var(--separator);
            border-radius: 50%;
            transform: translateY(-50%);
            background-color: var(--surface);
        }

        .analysis-stage.active {
            color: var(--primary-color);
            font-weight: 700;
        }

        .analysis-stage.active::before {
            border-color: var(--primary-color);
            animation: analysis-stage-pulse 1.8s ease-in-out infinite;
        }

        .analysis-stage.completed {
            color: var(--success-color);
            font-weight: 700;
        }

        .analysis-stage.completed::before {
            content: "✓";
            display: grid;
            place-items: center;
            width: 17px;
            height: 17px;
            border: 0;
            color: #FFFFFF;
            background-color: var(--success-color);
            font-size: 0.67rem;
            line-height: 1;
        }

        @keyframes analysis-stage-pulse {
            0%, 100% {
                opacity: 0.45;
            }
            50% {
                opacity: 1;
            }
        }

        .analysis-tip-card {
            border: 1px solid var(--border-color);
            border-radius: 16px;
            background-color: var(--surface);
            padding: 13px 14px;
        }

        .analysis-tip-label {
            display: block;
            margin-bottom: 5px;
            color: var(--text-muted);
            font-size: 0.72rem;
            font-weight: 700;
        }

        .analysis-tip-text {
            min-height: 2.8em;
            font-size: 0.84rem;
            line-height: 1.55;
            color: var(--text-color);
        }

        .analysis-long-wait {
            margin-top: 10px;
            color: var(--text-muted);
            font-size: 0.78rem;
            line-height: 1.5;
            text-align: center;
        }

        /* Screen: Result & Suggestions */
        .screen-nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
            min-height: var(--control-min-height);
            margin-bottom: 18px;
            flex-shrink: 0;
            position: sticky;
            top: 0;
            z-index: 5;
            background: rgba(245, 245, 247, 0.90);
            -webkit-backdrop-filter: blur(18px) saturate(160%);
            backdrop-filter: blur(18px) saturate(160%);
        }

        .nav-back {
            background: transparent;
            border: none;
            color: var(--secondary-color);
            min-width: 64px;
            min-height: var(--control-min-height);
            padding: 8px 0;
            font-size: 0.96rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            cursor: pointer;
            border-radius: 10px;
        }

        .nav-back svg {
            width: 18px;
            height: 18px;
            margin-right: 4px;
        }

        .nav-title {
            font-size: 1.02rem;
            font-weight: 700;
            letter-spacing: -0.015em;
        }

        .result-summary {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: var(--card-radius);
            padding: 16px;
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 14px 8px;
            margin-bottom: 16px;
            flex-shrink: 0;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.05);
        }

        .analysis-mode-banner {
            border-radius: 10px;
            margin-bottom: 12px;
            padding: 10px 12px;
            font-size: 0.85rem;
            font-weight: 700;
            text-align: center;
        }

        .analysis-mode-banner.mode-gemini {
            background-color: rgba(16, 185, 129, 0.12);
            border: 1px solid var(--success-color);
            color: var(--success-color);
        }

        .analysis-mode-banner.mode-mock,
        .analysis-mode-banner.mode-warning {
            background-color: rgba(245, 158, 11, 0.1);
            border: 1px solid var(--warning-color);
            color: var(--warning-color);
        }

        .summary-item {
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .assessment-item {
            grid-column: 1 / -1;
            border-top: 1px solid var(--border-color);
            padding-top: 12px;
        }

        .assessment-label {
            color: var(--text-muted);
            font-size: 0.78rem;
            margin-right: 8px;
        }

        .assessment-badge {
            border-radius: 999px;
            font-size: 0.86rem;
            font-weight: 750;
            padding: 5px 11px;
        }

        .assessment-visible {
            background-color: rgba(239, 68, 68, 0.11);
            border: 1px solid rgba(239, 68, 68, 0.35);
            color: var(--danger-color);
        }

        .assessment-confirm {
            background-color: rgba(0, 122, 255, 0.10);
            border: 1px solid rgba(0, 122, 255, 0.32);
            color: var(--secondary-color);
        }

        .assessment-clear {
            background-color: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.34);
            color: var(--success-color);
        }

        .summary-label {
            font-size: 0.78rem;
            color: var(--text-muted);
            margin-bottom: 4px;
        }

        .summary-value {
            font-size: 1.45rem;
            font-weight: 750;
            letter-spacing: -0.03em;
        }

        .badge {
            padding: 4px 11px;
            border-radius: 999px;
            font-weight: 750;
            font-size: 0.9rem;
        }

        .badge-low {
            background-color: rgba(16, 185, 129, 0.15);
            color: var(--success-color);
            border: 1px solid var(--success-color);
        }

        .badge-medium {
            background-color: rgba(245, 158, 11, 0.15);
            color: var(--warning-color);
            border: 1px solid var(--warning-color);
        }

        .badge-high {
            background-color: rgba(239, 68, 68, 0.15);
            color: var(--danger-color);
            border: 1px solid var(--danger-color);
        }

        .result-images-list {
            display: flex;
            flex-direction: column;
            gap: 16px;
            margin-bottom: 20px;
        }

        .confirmation-items-note {
            background-color: rgba(0, 122, 255, 0.07);
            border: 1px solid rgba(0, 122, 255, 0.24);
            border-radius: 14px;
            color: var(--text-color);
            margin-bottom: 16px;
            padding: 14px 16px;
        }

        .confirmation-items-note strong {
            display: block;
            font-size: 0.92rem;
            margin-bottom: 5px;
        }

        .confirmation-items-note p {
            color: var(--text-muted);
            font-size: 0.82rem;
            line-height: 1.55;
            margin: 0;
        }

        .result-image-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: var(--card-radius);
            overflow: hidden;
            padding: 14px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.04);
        }

        .image-card-title {
            font-size: 0.92rem;
            font-weight: 700;
            color: var(--text-color);
            margin-bottom: 10px;
            display: block;
        }

        .image-wrapper {
            width: 100%;
            border-radius: 14px;
            overflow: hidden;
            border: 1px solid var(--border-color);
            background-color: var(--surface-muted);
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .image-wrapper img {
            width: 100%;
            height: auto;
            display: block;
            object-fit: contain;
        }

        .result-actions, .suggestions-actions {
            margin-top: auto;
            padding: 14px 0 max(2px, env(safe-area-inset-bottom));
            flex-shrink: 0;
        }

        .result-actions {
            position: sticky;
            bottom: -20px;
            z-index: 4;
            background: linear-gradient(
                to bottom,
                rgba(245, 245, 247, 0),
                rgba(245, 245, 247, 0.98) 24px
            );
            padding-top: 28px;
        }

        /* Screen 3: Action Suggestions */
        .section-title {
            font-size: 1.75rem;
            line-height: 1.25;
            font-weight: 750;
            letter-spacing: -0.035em;
            margin-bottom: 8px;
        }

        .section-subtitle {
            font-size: 0.92rem;
            line-height: 1.55;
            color: var(--text-muted);
            margin-bottom: 20px;
        }

        .action-cards-container {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: 16px;
        }

        /* Custom Accordion Cards */
        .accordion-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 18px;
            overflow: hidden;
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.035);
        }

        .accordion-card-header {
            width: 100%;
            min-height: var(--control-min-height);
            padding: 14px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            user-select: none;
            border: 0;
            background: transparent;
            color: inherit;
            font: inherit;
            text-align: left;
        }

        .accordion-card-title-group {
            display: flex;
            flex-direction: column;
        }

        .accordion-card-title {
            font-size: 0.96rem;
            font-weight: 700;
            color: var(--text-color);
        }

        .accordion-card-sub {
            display: flex;
            align-items: center;
            gap: 6px;
            margin-top: 4px;
        }

        .accordion-card-label {
            font-size: 0.72rem;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 999px;
        }

        .accordion-card-count {
            font-size: 0.78rem;
            color: var(--text-muted);
            font-weight: 500;
        }

        .accordion-card-icon {
            width: 18px;
            height: 18px;
            color: var(--text-muted);
            transition: transform 0.25s ease;
        }

        .accordion-card.open .accordion-card-icon {
            transform: rotate(180deg);
        }

        .accordion-card-content {
            padding: 0 16px;
        }

        .accordion-card.open .accordion-card-content {
            padding: 12px 16px 16px 16px;
            border-top: 1px solid var(--border-color);
        }

        /* Color variations for left borders and badges */
        .family-card {
            border-left: 4px solid var(--accent-green);
        }
        .family-card .accordion-card-label {
            background-color: rgba(16, 185, 129, 0.15);
            color: var(--accent-green);
        }

        .care-card {
            border-left: 4px solid var(--accent-blue);
        }
        .care-card .accordion-card-label {
            background-color: rgba(59, 130, 246, 0.15);
            color: var(--accent-blue);
        }

        .contractor-card {
            border-left: 4px solid var(--accent-red);
        }
        .contractor-card .accordion-card-label {
            background-color: rgba(239, 68, 68, 0.15);
            color: var(--accent-red);
        }

        .card-body {
            font-size: 0.94rem;
            line-height: 1.65;
            color: var(--text-color);
        }

        /* Markdown styles */
        .markdown-body h2, .markdown-body h3 {
            font-size: 0.96rem;
            margin-top: 12px;
            margin-bottom: 6px;
            font-weight: bold;
            color: var(--text-color);
        }
        
        .markdown-body p {
            margin-bottom: 6px;
        }

        .markdown-body ul, .markdown-body ol {
            padding-left: 16px;
            margin-bottom: 8px;
        }

        .markdown-body li {
            margin-bottom: 5px;
        }

        .action-report > h2,
        .action-report > ul > li:nth-child(-n + 2) {
            display: none;
        }

        .action-report > h3 {
            margin-top: 14px;
            font-size: 1rem;
            letter-spacing: -0.01em;
        }

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                scroll-behavior: auto !important;
                transition-duration: 0.01ms !important;
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
            }

            .analysis-scan-line,
            .analysis-activity::after,
            .analysis-stage.active::before {
                animation: none !important;
                transform: none !important;
            }

            .analysis-scan-line {
                top: 50%;
                opacity: 0.42;
            }

            .analysis-activity::after {
                left: 33%;
                opacity: 0.58;
            }
        }
    </style>
</head>
<body>
    <div id="app-container">
        <!-- Separate Hidden Inputs for Camera and Library -->
        <input type="file" id="camera-input" accept="image/*" capture="environment" style="display: none;">
        <input type="file" id="library-input" accept="image/*" style="display: none;">

        <!-- SCREEN 1: Home / Photo Input -->
        <div id="screen-home" class="screen active" aria-hidden="false">
            <div class="home-header">
                <div class="app-tag">親の家 安全チェック</div>
                <h1
                    class="home-title"
                    data-screen-title
                    tabindex="-1"
                    aria-label="写真1枚で、親の家を安全チェック"
                >
                    写真1枚で、<br>親の家を安全チェック
                </h1>
                <p class="home-lead">
                    写真に写っている転倒・すべり・つまずきの注意箇所を確認します。
                </p>
            </div>

            <p class="place-section-title">撮影する場所の例</p>
            <div class="place-grid">
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4"/></svg>
                    <span>玄関</span>
                </div>
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 12h18"/></svg>
                    <span>廊下</span>
                </div>
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 21h10M12 3v4M5 7h14a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2V9a2 2 0 012-2z"/></svg>
                    <span>浴室</span>
                </div>
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="2" width="12" height="20" rx="2"/><line x1="12" y1="18" x2="12" y2="18.01"/></svg>
                    <span>トイレ</span>
                </div>
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V7"/><path d="M21 7H3l2-4h14l2 4z"/></svg>
                    <span>寝室</span>
                </div>
                <div class="place-block">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3v4a1 1 0 001 1h4"/><path d="M4 14h6v7H4z"/><circle cx="17" cy="17" r="3"/></svg>
                    <span>キッチン</span>
                </div>
            </div>
            <p class="shooting-hint">
                床・段差・手すり・通路が一緒に写るように、まずは1か所を撮影してください。
            </p>

            <div class="home-controls">
                <div
                    id="error-message"
                    class="error-message"
                    role="alert"
                    aria-live="assertive"
                    style="display: none;"
                ></div>
            </div>

            <div class="home-footer">
                <div class="trust-card" aria-label="このチェックについて">
                    <div class="trust-item">
                        <span class="trust-label">写真の取り扱い</span>
                        <strong class="trust-value">写真は保存しません</strong>
                    </div>
                    <div class="trust-item">
                        <span class="trust-label">確認できること</span>
                        <strong class="trust-value">見える範囲のみ確認します</strong>
                    </div>
                    <p class="trust-note">
                        POC版です。医療・介護・保険・施工の専門判断を代替しません。
                    </p>
                </div>

                <!-- Select buttons state -->
                <div id="selection-buttons-container">
                    <button id="btn-camera" class="btn btn-primary">
                        <svg class="btn-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M4 4h3l2-2h6l2 2h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm8 3a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 2a3 3 0 1 1 0 6 3 3 0 0 1 0-6z"/>
                        </svg>
                        カメラで撮る
                    </button>
                    <button id="btn-library" class="btn btn-secondary">
                        <svg class="btn-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm-9 14l-4-4 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                        </svg>
                        ライブラリから選ぶ
                    </button>
                </div>
            </div>
        </div>

        <!-- SCREEN 2: Safety Check Result / Analyzing -->
        <div id="screen-result" class="screen" aria-hidden="true">
            <div class="screen-nav">
                <button class="nav-back btn-back-home">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M10.828 12l4.95 4.95-1.414 1.414-6.364-6.364 6.364-6.364 1.414 1.414z"/>
                    </svg>
                    ホーム
                </button>
                <span class="nav-title" id="screen2-title" data-screen-title tabindex="-1">
                    写真確認中
                </span>
                <div style="width: 60px;"></div>
            </div>

            <!-- 1. Analyzing State Container -->
            <div id="result-analyzing-container">
                <div class="large-preview-wrapper">
                    <img id="result-large-preview" src="" alt="安全確認のために選択した写真">
                    <div class="analysis-scan-overlay" aria-hidden="true">
                        <span class="analysis-scan-line"></span>
                    </div>
                </div>
                <div
                    class="analysis-activity"
                    role="progressbar"
                    aria-label="写真の安全確認を進めています"
                ></div>
                <div class="analyzing-status-box">
                    <p
                        id="analysis-stage-message"
                        class="analyzing-subtitle"
                        role="status"
                        aria-live="polite"
                    >写真を安全に処理しています</p>
                    <ol class="analysis-stages" aria-label="解析の進行段階">
                        <li
                            class="analysis-stage active"
                            id="analysis-stage-intake"
                            aria-current="step"
                        >写真を安全に処理</li>
                        <li
                            class="analysis-stage"
                            id="analysis-stage-vision"
                        >見える範囲を解析</li>
                        <li
                            class="analysis-stage"
                            id="analysis-stage-organize"
                        >結果を整理</li>
                    </ol>
                    <aside class="analysis-tip-card" aria-label="待ち時間の安全確認ヒント">
                        <span class="analysis-tip-label">待ち時間にできること</span>
                        <p id="analysis-tip" class="analysis-tip-text">
                            床が濡れていたら、早めに拭きましょう。
                        </p>
                    </aside>
                    <p
                        id="analysis-long-wait"
                        class="analysis-long-wait"
                        role="status"
                        aria-live="polite"
                        hidden
                    >通常より時間がかかっていますが、解析は続いています。</p>
                </div>
            </div>

            <!-- 2. Completed State Container -->
            <div id="result-completed-container" style="display: none;">
                <div id="analysis-mode-banner" class="analysis-mode-banner mode-warning" role="status"></div>
                <div class="result-summary">
                    <div class="summary-item">
                        <span class="summary-label">写真内の注意箇所</span>
                        <span id="risk-count" class="summary-value">--件</span>
                    </div>
                    <div class="summary-item">
                        <span class="summary-label">現地で要確認</span>
                        <span id="confirmation-count" class="summary-value">--件</span>
                    </div>
                    <div class="summary-item assessment-item">
                        <div>
                            <span class="assessment-label">写真からの判定</span>
                            <span id="assessment-badge" class="assessment-badge">--</span>
                        </div>
                    </div>
                </div>

                <!-- Not Applicable Warning Box -->
                <div id="not-applicable-container" style="display: none; background-color: rgba(201, 52, 0, 0.08); border: 1px solid var(--warning-color); border-radius: 16px; padding: 16px; margin-bottom: 20px; text-align: center;">
                    <p id="not-applicable-message" style="color: var(--warning-color); font-weight: bold; font-size: 0.95rem;"></p>
                </div>

                <div
                    id="confirmation-items-note"
                    class="confirmation-items-note"
                    role="note"
                    hidden
                >
                    <strong id="confirmation-items-title">写真だけでは確認できない項目</strong>
                    <div id="confirmation-items-body">
                        <p>
                            写真で確認できなかったことは、住宅内に存在しないことを意味しません。
                            増設が必要かどうかや、設置位置もこの写真だけでは判断できません。
                            誤解を避けるため、画像上に赤枠や設置候補を表示していません。
                        </p>
                    </div>
                </div>

                <!-- Stacked Images: Annotated first, Improvement second -->
                <div class="result-images-list">
                    <div id="result-current-image-card" class="result-image-card">
                        <span id="result-current-image-title" class="image-card-title">現在の注意箇所</span>
                        <div class="image-wrapper">
                            <img id="result-annotated-img" src="" alt="赤枠で注意箇所を示した現在の写真">
                        </div>
                    </div>
                    <div id="result-improvement-image-card" class="result-image-card">
                        <span class="image-card-title">対策イメージ（施工図ではありません）</span>
                        <div class="image-wrapper">
                            <img id="result-improvement-img" src="" alt="注意箇所への一般的な対策イメージ">
                        </div>
                    </div>
                </div>

                <!-- Hidden Debug Panel -->
                <div class="debug-panel" style="display: none; background-color: var(--surface); border: 1px dashed var(--border-color); border-radius: 12px; padding: 12px; font-size: 0.75rem; font-family: monospace; margin-top: 16px; text-align: left;">
                    <div style="font-weight: bold; margin-bottom: 4px; color: var(--warning-color);">[DEBUG INFO]</div>
                    <div>Mode: <span class="debug-mode">--</span></div>
                    <div>Analysis ID: <span class="debug-analysis-id">--</span></div>
                    <div>Model: <span class="debug-model">--</span></div>
                    <div>Findings Count: <span class="debug-finding-count">--</span></div>
                    <div>Is Home Environment: <span class="debug-is-home">--</span></div>
                </div>

                <div class="result-actions">
                    <button id="btn-show-suggestions" class="btn btn-primary">次にできることを見る</button>
                    <button class="btn btn-outline btn-back-home">ホームに戻る</button>
                </div>
            </div>
        </div>

        <!-- SCREEN 3: Action Suggestions -->
        <div id="screen-suggestions" class="screen" aria-hidden="true">
            <div class="screen-nav">
                <button id="btn-back-to-result" class="nav-back">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M10.828 12l4.95 4.95-1.414 1.414-6.364-6.364 6.364-6.364 1.414 1.414z"/>
                    </svg>
                    戻る
                </button>
                <span class="nav-title">次にできること</span>
                <div style="width: 60px;"></div>
            </div>

            <h1 class="section-title" data-screen-title tabindex="-1">次にできること</h1>
            <p class="section-subtitle">
                安全のため、家族で今日できることから順に確認してください。
            </p>

            <!-- Collapsed Accordion Cards -->
            <div class="action-cards-container">
                <!-- Family Card -->
                <div class="accordion-card family-card open">
                    <button
                        type="button"
                        class="accordion-card-header"
                        aria-expanded="true"
                        aria-controls="accordion-family"
                    >
                        <span class="accordion-card-title-group">
                            <span class="accordion-card-title">家族で今日できること</span>
                            <span class="accordion-card-sub">
                                <span class="accordion-card-label">今日・費用なし</span>
                                <span id="family-count" class="accordion-card-count"></span>
                            </span>
                        </span>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </button>
                    <div id="accordion-family" class="accordion-card-content">
                        <div id="action-family-content" class="card-body markdown-body action-report"></div>
                    </div>
                </div>

                <!-- Care Manager Card -->
                <div class="accordion-card care-card">
                    <button
                        type="button"
                        class="accordion-card-header"
                        aria-expanded="false"
                        aria-controls="accordion-care"
                    >
                        <span class="accordion-card-title-group">
                            <span class="accordion-card-title">ケアマネ・福祉用具に相談</span>
                            <span class="accordion-card-sub">
                                <span class="accordion-card-label">購入・レンタルの相談</span>
                                <span id="care-count" class="accordion-card-count"></span>
                            </span>
                        </span>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </button>
                    <div id="accordion-care" class="accordion-card-content" hidden>
                        <div id="action-care-content" class="card-body markdown-body action-report"></div>
                    </div>
                </div>

                <!-- Contractor Card -->
                <div class="accordion-card contractor-card">
                    <button
                        type="button"
                        class="accordion-card-header"
                        aria-expanded="false"
                        aria-controls="accordion-contractor"
                    >
                        <span class="accordion-card-title-group">
                            <span class="accordion-card-title">専門施工・現地確認</span>
                            <span class="accordion-card-sub">
                                <span class="accordion-card-label">工事・現地確認</span>
                                <span id="contractor-count" class="accordion-card-count"></span>
                            </span>
                        </span>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </button>
                    <div id="accordion-contractor" class="accordion-card-content" hidden>
                        <div id="action-contractor-content" class="card-body markdown-body action-report"></div>
                    </div>
                </div>

                <!-- Risk Basis Card -->
                <div class="accordion-card basis-card">
                    <button
                        type="button"
                        class="accordion-card-header"
                        aria-expanded="false"
                        aria-controls="accordion-basis"
                    >
                        <span class="accordion-card-title-group">
                            <span class="accordion-card-title">詳しいリスク根拠を見る</span>
                        </span>
                        <svg class="accordion-card-icon" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/>
                        </svg>
                    </button>
                    <div id="accordion-basis" class="accordion-card-content" hidden>
                        <div id="risk-details-content" class="markdown-body"></div>
                    </div>
                </div>
            </div>

            <p class="disclaimer-text" style="color: var(--text-muted); text-align: left; margin: 16px 0;">
                ※POC版です。医療・介護・施工判断を代替しません。<br>
                ※対策イメージはコミュニケーション用であり施工図ではありません。
            </p>

            <!-- Hidden Debug Panel -->
            <div class="debug-panel" style="display: none; background-color: var(--surface); border: 1px dashed var(--border-color); border-radius: 12px; padding: 12px; font-size: 0.75rem; font-family: monospace; margin-top: 16px; text-align: left; margin-bottom: 16px;">
                <div style="font-weight: bold; margin-bottom: 4px; color: var(--warning-color);">[DEBUG INFO]</div>
                <div>Mode: <span class="debug-mode">--</span></div>
                <div>Analysis ID: <span class="debug-analysis-id">--</span></div>
                <div>Model: <span class="debug-model">--</span></div>
                <div>Findings Count: <span class="debug-finding-count">--</span></div>
                <div>Is Home Environment: <span class="debug-is-home">--</span></div>
            </div>

            <div class="suggestions-actions">
                <button class="btn btn-outline btn-back-home">ホームに戻る</button>
            </div>
        </div>
    </div>

    <script>
        const cameraInput = document.getElementById('camera-input');
        const libraryInput = document.getElementById('library-input');
        const btnCamera = document.getElementById('btn-camera');
        const btnLibrary = document.getElementById('btn-library');
        const errorDiv = document.getElementById('error-message');

        const btnShowSuggestions = document.getElementById('btn-show-suggestions');
        const btnBackToResult = document.getElementById('btn-back-to-result');
        const btnBackHomes = document.querySelectorAll('.btn-back-home');

        let selectedFile = null;
        const analysisTips = [
            '床が濡れていたら、早めに拭きましょう。',
            '通り道に物がないか、無理のない範囲で確認しましょう。',
            '夜間に足元が見える明るさか、家族と確認しましょう。'
        ];
        const analysisStageMessages = {
            intake: '写真を安全に処理しています',
            vision: '写真に見える範囲を解析しています',
            organize: '結果を整理しています'
        };
        /* ANALYSIS_STATE_MACHINES_START */
        class AnalysisUiError extends Error {}

        class AnalysisEventStateMachine {
            constructor() {
                this.progressStages = ['intake_complete', 'vision_complete'];
                this.progressIndex = 0;
                this.terminal = false;
            }

            accept(event) {
                if (!event || typeof event !== 'object' || this.terminal) {
                    throw new AnalysisUiError(
                        '分析結果を正しく受信できませんでした。'
                    );
                }
                if (event.type === 'progress') {
                    if (event.stage !== this.progressStages[this.progressIndex]) {
                        throw new AnalysisUiError(
                            '分析結果を正しく受信できませんでした。'
                        );
                    }
                    this.progressIndex += 1;
                    return { type: 'progress', stage: event.stage };
                }
                if (event.type === 'result') {
                    if (
                        !event.payload
                        || typeof event.payload !== 'object'
                    ) {
                        throw new AnalysisUiError(
                            '分析結果を正しく受信できませんでした。'
                        );
                    }
                    this.terminal = true;
                    return { type: 'result', payload: event.payload };
                }
                if (event.type === 'error' && typeof event.error === 'string') {
                    this.terminal = true;
                    return { type: 'error', error: event.error };
                }
                throw new AnalysisUiError(
                    '分析結果を正しく受信できませんでした。'
                );
            }
        }

        class AnalysisRequestSession {
            constructor(controller) {
                this.controller = controller;
                this.reader = null;
                this.readerCancelPromise = null;
                this.cancelled = false;
                this.succeeded = false;
                this.eventState = new AnalysisEventStateMachine();
            }

            attachReader(reader) {
                if (this.reader && this.reader !== reader) {
                    throw new AnalysisUiError(
                        '分析結果を正しく受信できませんでした。'
                    );
                }
                this.reader = reader;
                if (this.cancelled) {
                    void this.cancelReader();
                }
            }

            cancelReader() {
                if (!this.reader) {
                    return Promise.resolve();
                }
                if (!this.readerCancelPromise) {
                    this.readerCancelPromise = Promise.resolve()
                        .then(() => this.reader.cancel())
                        .catch(() => {});
                }
                return this.readerCancelPromise;
            }

            async cancel() {
                if (this.succeeded) return;
                this.cancelled = true;
                if (!this.controller.signal.aborted) {
                    this.controller.abort();
                }
                await this.cancelReader();
            }

            async finishSuccess() {
                if (this.controller.signal.aborted) {
                    throw new DOMException('Analysis aborted', 'AbortError');
                }
                this.succeeded = true;
                await this.cancelReader();
            }
        }

        function analysisSessionCanMutateUi(session) {
            return (
                activeAnalysisSession === session
                && !session.cancelled
            );
        }

        async function dispatchAnalysisEventForSession(event, session) {
            if (!analysisSessionCanMutateUi(session)) {
                await session.cancel();
                return { stale: true, terminal: false };
            }
            return {
                stale: false,
                terminal: handleAnalysisEvent(event, session.eventState)
            };
        }
        /* ANALYSIS_STATE_MACHINES_END */
        let analysisTipTimer = null;
        let longWaitTimer = null;
        let activeAnalysisSession = null;

        // Nav functions
        function showScreen(screenId) {
            const screens = document.querySelectorAll('.screen');
            screens.forEach(screen => {
                screen.classList.remove('active');
                screen.setAttribute('aria-hidden', 'true');
            });
            const nextScreen = document.getElementById(screenId);
            nextScreen.classList.add('active');
            nextScreen.setAttribute('aria-hidden', 'false');
            nextScreen.scrollTop = 0;

            requestAnimationFrame(() => {
                const screenTitle = nextScreen.querySelector('[data-screen-title]');
                if (screenTitle) {
                    screenTitle.focus({ preventScroll: true });
                }
            });
        }

        btnCamera.addEventListener('click', () => {
            errorDiv.style.display = 'none';
            cameraInput.click();
            if (!/Mobi|Android|iPhone/i.test(navigator.userAgent)) {
                errorDiv.textContent = "このブラウザではカメラ起動が制限される場合があります。ライブラリから選択してください。";
                errorDiv.style.display = "block";
            }
        });

        btnLibrary.addEventListener('click', () => {
            errorDiv.style.display = 'none';
            libraryInput.click();
        });

        cameraInput.addEventListener('change', handleFileSelect);
        libraryInput.addEventListener('change', handleFileSelect);

        function handleFileSelect(event) {
            const file = event.target.files[0];
            if (!file) return;

            selectedFile = file;
            errorDiv.style.display = 'none';

            // Show selected photo in Screen 2 immediately
            const reader = new FileReader();
            reader.onload = function(e) {
                document.getElementById('result-large-preview').src = e.target.result;
            };
            reader.readAsDataURL(file);

            // Move directly to Screen 2
            showScreen('screen-result');

            // Reset Screen 2 state to "Analyzing"
            document.getElementById('screen2-title').textContent = "写真確認中";
            document.getElementById('result-analyzing-container').style.display = 'block';
            document.getElementById('result-completed-container').style.display = 'none';

            // Run analysis immediately
            uploadAndAnalyze(selectedFile);
        }

        // Clear preview / reset to home
        function clearPreview() {
            selectedFile = null;
            cameraInput.value = '';
            libraryInput.value = '';
            document.getElementById('result-large-preview').src = '';
            errorDiv.style.display = 'none';
        }

        function renderAnalysisTip(tip) {
            document.getElementById('analysis-tip').textContent = tip;
        }

        function setAnalysisStage(stage) {
            const order = ['intake', 'vision', 'organize'];
            const activeIndex = order.indexOf(stage);
            if (activeIndex < 0) return;

            order.forEach((name, index) => {
                const step = document.getElementById(`analysis-stage-${name}`);
                step.className = 'analysis-stage';
                step.removeAttribute('aria-current');
                if (index < activeIndex) {
                    step.classList.add('completed');
                } else if (index === activeIndex) {
                    step.classList.add('active');
                    step.setAttribute('aria-current', 'step');
                }
            });
            document.getElementById('analysis-stage-message').textContent = (
                analysisStageMessages[stage]
            );
        }

        function completeAnalysisStages() {
            ['intake', 'vision', 'organize'].forEach(name => {
                const step = document.getElementById(`analysis-stage-${name}`);
                step.className = 'analysis-stage completed';
                step.removeAttribute('aria-current');
            });
            document.getElementById('analysis-stage-message').textContent = (
                '結果の準備ができました'
            );
        }

        function startWaitingExperience() {
            stopWaitingExperience();
            setAnalysisStage('intake');
            let tipIndex = 0;
            renderAnalysisTip(analysisTips[tipIndex]);
            analysisTipTimer = window.setInterval(() => {
                tipIndex = (tipIndex + 1) % analysisTips.length;
                renderAnalysisTip(analysisTips[tipIndex]);
            }, 5000);
            longWaitTimer = window.setTimeout(() => {
                document.getElementById('analysis-long-wait').hidden = false;
            }, 20000);
        }

        function stopWaitingExperience() {
            window.clearInterval(analysisTipTimer);
            window.clearTimeout(longWaitTimer);
            analysisTipTimer = null;
            longWaitTimer = null;
            document.getElementById('analysis-long-wait').hidden = true;
        }

        function cancelActiveAnalysis() {
            const session = activeAnalysisSession;
            if (session) {
                if (activeAnalysisSession === session) {
                    activeAnalysisSession = null;
                }
                void session.cancel();
            }
            stopWaitingExperience();
        }

        function analysisErrorMessage(errorCode) {
            if (errorCode === 'gemini_unavailable') {
                return '解析サービスは現在利用できません。時間をおいてもう一度お試しください。';
            }
            if (errorCode === 'invalid_upload') {
                return '画像または入力内容を確認して、もう一度お試しください。';
            }
            return '分析を完了できませんでした。もう一度お試しください。';
        }

        function handleAnalysisEvent(event, eventState) {
            const accepted = eventState.accept(event);
            if (accepted.type === 'progress') {
                if (accepted.stage === 'intake_complete') {
                    setAnalysisStage('vision');
                } else if (accepted.stage === 'vision_complete') {
                    setAnalysisStage('organize');
                }
                return false;
            }
            if (accepted.type === 'result') {
                completeAnalysisStages();
                stopWaitingExperience();
                renderResults(accepted.payload);
                return true;
            }
            if (accepted.type === 'error') {
                stopWaitingExperience();
                throw new AnalysisUiError(analysisErrorMessage(accepted.error));
            }
            throw new AnalysisUiError('分析結果を正しく受信できませんでした。');
        }

        async function uploadAndAnalyze(file) {
            cancelActiveAnalysis();
            const session = new AnalysisRequestSession(new AbortController());
            activeAnalysisSession = session;
            let reader = null;
            startWaitingExperience();
            const formData = new FormData();
            formData.append('image', file);
            formData.append('room_hint', 'auto');

            try {
                const response = await fetch('/analyze/stream', {
                    method: 'POST',
                    body: formData,
                    headers: { 'Accept': 'application/x-ndjson' },
                    signal: session.controller.signal
                });

                if (!response.ok) {
                    throw new AnalysisUiError('分析サービスとの通信に失敗しました。');
                }
                const contentType = response.headers.get('content-type') || '';
                if (!contentType.includes('application/x-ndjson') || !response.body) {
                    throw new AnalysisUiError('分析結果を正しく受信できませんでした。');
                }

                reader = response.body.getReader();
                session.attachReader(reader);
                const decoder = new TextDecoder();
                let buffer = '';
                while (true) {
                    const { value, done } = await reader.read();
                    if (!analysisSessionCanMutateUi(session)) {
                        await session.cancel();
                        return;
                    }
                    buffer += decoder.decode(
                        value || new Uint8Array(),
                        { stream: !done }
                    );
                    const lines = buffer.split('\\n');
                    buffer = lines.pop() || '';
                    if (done && buffer.trim()) {
                        lines.push(buffer);
                        buffer = '';
                    }
                    for (const line of lines) {
                        if (!line.trim()) continue;
                        if (!analysisSessionCanMutateUi(session)) {
                            await session.cancel();
                            return;
                        }
                        let event;
                        try {
                            event = JSON.parse(line);
                        } catch (_parseError) {
                            throw new AnalysisUiError(
                                '分析結果を正しく受信できませんでした。'
                            );
                        }
                        const eventOutcome = await dispatchAnalysisEventForSession(
                            event,
                            session
                        );
                        if (eventOutcome.stale) return;
                        if (eventOutcome.terminal) {
                            await session.finishSuccess();
                            return;
                        }
                    }
                    if (done) break;
                }
                throw new AnalysisUiError('分析結果を受信できませんでした。');
            } catch (err) {
                await session.cancel();
                if (err && err.name === 'AbortError') return;
                if (activeAnalysisSession !== session) return;
                console.error('analysis_request_failed');
                clearPreview();
                showScreen('screen-home');
                errorDiv.textContent = (
                    err instanceof AnalysisUiError
                        ? err.message
                        : '分析エラーが発生しました。'
                );
                errorDiv.style.display = 'block';
            } finally {
                if (!session.succeeded) {
                    await session.cancel();
                }
                if (activeAnalysisSession === session) {
                    activeAnalysisSession = null;
                    stopWaitingExperience();
                }
            }
        }

        function countItems(markdown) {
            if (!markdown) return 0;
            const matches = markdown.match(/###/g);
            return matches ? matches.length : 0;
        }

        const SAFE_MARKDOWN_TAGS = new Set([
            'H2', 'H3', 'P', 'UL', 'OL', 'LI', 'STRONG', 'EM', 'BR', 'CODE'
        ]);

        function renderSafeMarkdown(element, markdown) {
            const template = document.createElement('template');
            const parsedMarkdown = marked.parse(
                typeof markdown === 'string' ? markdown : ''
            );
            template.innerHTML = parsedMarkdown;

            const elements = [...template.content.querySelectorAll('*')];
            for (const node of elements) {
                if (!SAFE_MARKDOWN_TAGS.has(node.tagName)) {
                    node.replaceWith(document.createTextNode(node.textContent || ''));
                    continue;
                }
                for (const attribute of [...node.attributes]) {
                    node.removeAttribute(attribute.name);
                }
            }

            element.replaceChildren(template.content.cloneNode(true));
        }

        function renderResults(payload) {
            const isNotApplicable = payload.is_not_applicable === true || payload.is_home_environment === false;
            const resultSummary = document.querySelector('.result-summary');
            const notAppContainer = document.getElementById('not-applicable-container');
            const notAppMsg = document.getElementById('not-applicable-message');
            const imagesList = document.querySelector('.result-images-list');
            const confirmationNote = document.getElementById('confirmation-items-note');
            const confirmationTitle = document.getElementById('confirmation-items-title');
            const currentImageTitle = document.getElementById('result-current-image-title');
            const currentImage = document.getElementById('result-annotated-img');
            const improvementCard = document.getElementById('result-improvement-image-card');
            const confirmationItems = Array.isArray(payload.confirmation_items) ? payload.confirmation_items : [];
            const findings = Array.isArray(payload.findings) ? payload.findings : [];
            const count = findings.length;
            const hasVisibleFindings = findings.length > 0;

            renderAnalysisModeBanner(payload);

            // Keep visible hazards and unresolved on-site checks as separate counts.
            document.getElementById('risk-count').textContent = count + '件';
            document.getElementById('confirmation-count').textContent = confirmationItems.length + '件';
            const assessmentBadge = document.getElementById('assessment-badge');
            const assessmentStatus = payload.assessment_status;
            if (assessmentStatus === 'visible_risks_found') {
                assessmentBadge.textContent = `注意箇所あり（${getRiskLabel(payload.overall_risk_level)}）`;
                assessmentBadge.className = 'assessment-badge assessment-visible';
            } else if (assessmentStatus === 'needs_on_site_confirmation') {
                assessmentBadge.textContent = '現地確認が必要';
                assessmentBadge.className = 'assessment-badge assessment-confirm';
            } else if (assessmentStatus === 'no_visible_risks_found') {
                assessmentBadge.textContent = '写真内で検出なし';
                assessmentBadge.className = 'assessment-badge assessment-clear';
            } else {
                assessmentBadge.textContent = '判定保留';
                assessmentBadge.className = 'assessment-badge assessment-confirm';
            }

            if (isNotApplicable) {
                notAppMsg.textContent = payload.not_applicable_reason_ja || "この写真では確認結果を表示できません。";
                notAppContainer.style.display = 'block';
                resultSummary.style.display = 'none';
                imagesList.style.display = 'none';
                confirmationNote.hidden = true;
                btnShowSuggestions.style.display = 'none';
            } else {
                notAppContainer.style.display = 'none';
                resultSummary.style.display = 'grid';
                imagesList.style.display = 'flex';
                btnShowSuggestions.style.display = hasVisibleFindings ? '' : 'none';

                confirmationNote.hidden = confirmationItems.length === 0;
                confirmationTitle.textContent = (
                    `写真だけでは確認できない項目：${confirmationItems.length}件`
                );
                renderSafeMarkdown(document.getElementById('confirmation-items-body'), payload.confirmation_items_markdown);
                currentImageTitle.textContent = hasVisibleFindings
                    ? '写真で確認できた注意箇所'
                    : '確認した写真（位置を特定できる注意箇所はありません）';
                currentImage.alt = hasVisibleFindings
                    ? '赤枠で写真内の可視の注意箇所を示した写真'
                    : '確認対象として使用した写真。位置を特定できる注意箇所の表示はありません';
                improvementCard.hidden = !hasVisibleFindings;

                // Set Images
                currentImage.src = 'data:image/png;base64,' + payload.annotated_image_base64;
                document.getElementById('result-improvement-img').src = 'data:image/png;base64,' + payload.improvement_image_base64;
            }

            // Parse Markdown in an inert template, then append only allowlisted nodes.
            renderSafeMarkdown(document.getElementById('action-family-content'), payload.family_actions_markdown);
            renderSafeMarkdown(document.getElementById('action-care-content'), payload.care_manager_actions_markdown);
            renderSafeMarkdown(document.getElementById('action-contractor-content'), payload.contractor_actions_markdown);
            renderSafeMarkdown(document.getElementById('risk-details-content'), payload.risk_summary_markdown);

            // Set dynamic counts in headers
            const famCount = countItems(payload.family_actions_markdown);
            document.getElementById('family-count').textContent = famCount ? `(${famCount}件)` : '';

            const cCount = countItems(payload.care_manager_actions_markdown);
            document.getElementById('care-count').textContent = cCount ? `(${cCount}件)` : '';

            const conCount = countItems(payload.contractor_actions_markdown);
            document.getElementById('contractor-count').textContent = conCount ? `(${conCount}件)` : '';

            // Keep the safest immediate actions open and the other tiers collapsed.
            document.querySelectorAll('.accordion-card').forEach(card => {
                const header = card.querySelector('.accordion-card-header');
                const content = document.getElementById(header.getAttribute('aria-controls'));
                const shouldOpen = card.classList.contains('family-card');
                card.classList.toggle('open', shouldOpen);
                header.setAttribute('aria-expanded', String(shouldOpen));
                content.hidden = !shouldOpen;
            });

            // Update Debug Panel
            updateDebugPanel(payload);

            stopWaitingExperience();
            
            // Switch title and transition to completed layout inside Screen 2
            document.getElementById('screen2-title').textContent = "安全チェック結果";
            document.getElementById('result-analyzing-container').style.display = 'none';
            document.getElementById('result-completed-container').style.display = 'block';
        }

        function renderAnalysisModeBanner(payload) {
            const banner = document.getElementById('analysis-mode-banner');
            const mode = typeof payload.mode === 'string' ? payload.mode : '';
            let text = '実行モードを確認できません';
            let style = 'mode-warning';

            if (mode === 'gemini') {
                text = 'Gemini解析結果';
                style = 'mode-gemini';
            } else if (mode === 'mock') {
                text = 'モック結果（AI実解析ではありません）';
                style = 'mode-mock';
            } else if (mode === 'local_mock') {
                text = 'ローカルモック結果（AI実解析ではありません）';
                style = 'mode-mock';
            } else if (mode.startsWith('gemini_fallback(')) {
                text = 'フォールバック結果（Gemini解析として扱わないでください）';
                style = 'mode-warning';
            } else if (mode.startsWith('gemini_partial(')) {
                text = '部分解析（補完に失敗したため安全判定として扱わないでください）';
                style = 'mode-warning';
            }

            banner.textContent = text;
            banner.className = 'analysis-mode-banner ' + style;
        }

        function updateDebugPanel(payload) {
            const urlParams = new URLSearchParams(window.location.search);
            const isDebug = urlParams.get('debug') === '1';
            
            const panels = document.querySelectorAll('.debug-panel');
            panels.forEach(panel => {
                panel.style.display = isDebug ? 'block' : 'none';
            });
            
            if (isDebug && payload) {
                const mode = payload.mode || 'N/A';
                const analysisId = payload.analysis_id || 'N/A';
                const model = payload.model || 'N/A';
                const count = payload.findings ? payload.findings.length : 0;
                const isHome = payload.is_home_environment !== false;
                
                document.querySelectorAll('.debug-mode').forEach(el => el.textContent = mode);
                document.querySelectorAll('.debug-analysis-id').forEach(el => el.textContent = analysisId);
                document.querySelectorAll('.debug-model').forEach(el => el.textContent = model);
                document.querySelectorAll('.debug-finding-count').forEach(el => el.textContent = count);
                document.querySelectorAll('.debug-is-home').forEach(el => el.textContent = isHome ? 'True' : 'False');
            }
        }

        function getRiskLabel(risk) {
            if (risk === 'low') return '低';
            if (risk === 'medium') return '中';
            if (risk === 'high') return '高';
            return '中';
        }

        // Accordion Card Toggle Handler
        document.querySelectorAll('.accordion-card-header').forEach(header => {
            header.addEventListener('click', () => {
                const card = header.closest('.accordion-card');
                const contentId = header.getAttribute('aria-controls');
                const content = document.getElementById(contentId);
                const willOpen = header.getAttribute('aria-expanded') !== 'true';
                card.classList.toggle('open', willOpen);
                header.setAttribute('aria-expanded', String(willOpen));
                content.hidden = !willOpen;
            });
        });

        // Navigate between result and action cards
        btnShowSuggestions.addEventListener('click', () => {
            showScreen('screen-suggestions');
        });

        btnBackToResult.addEventListener('click', () => {
            showScreen('screen-result');
        });

        // Reset flow
        function resetApp() {
            cancelActiveAnalysis();
            clearPreview();
            updateDebugPanel(null);
            showScreen('screen-home');
        }

        btnBackHomes.forEach(btn => {
            btn.addEventListener('click', resetApp);
        });
        window.addEventListener('pagehide', cancelActiveAnalysis);
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                cancelActiveAnalysis();
            }
        });
    </script>
</body>
</html>
"""


FRONTEND_REQUIRE_REAL_GEMINI = os.getenv("REQUIRE_REAL_GEMINI", "false").strip().lower() in {"1", "true", "yes", "on"}


def _positive_timeout_env(name: str, default: float | str) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


_analysis_timeout_fallback = _positive_timeout_env("ANALYSIS_TIMEOUT", 120.0)
SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS = _positive_timeout_env(
    "SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS", _analysis_timeout_fallback
)
SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS = _positive_timeout_env(
    "SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS", 30.0
)
_proxy_timeout_override = os.getenv("SUMAI_AGENT_TIMEOUT_SECONDS", "").strip()
SUMAI_AGENT_TIMEOUT_SECONDS = (
    _positive_timeout_env("SUMAI_AGENT_TIMEOUT_SECONDS", 0.0)
    if _proxy_timeout_override
    else SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS + SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS
)
_required_proxy_timeout = (
    SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS + SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS
)
if SUMAI_AGENT_TIMEOUT_SECONDS < _required_proxy_timeout:
    raise ValueError(
        "SUMAI_AGENT_TIMEOUT_SECONDS must be at least "
        "SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS plus "
        "SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS"
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        await close_backend_client()


app = FastAPI(title="SumaiGuard Web", lifespan=lifespan)


def backend_client() -> httpx.AsyncClient:
    global _backend_client
    if _backend_client is None:
        _backend_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                SUMAI_AGENT_TIMEOUT_SECONDS,
                connect=min(10.0, SUMAI_AGENT_TIMEOUT_SECONDS / 2),
            )
        )
    return _backend_client


async def close_backend_client() -> None:
    """Close the reusable backend client before its event loop is discarded."""
    global _backend_client
    client = _backend_client
    _backend_client = None
    if client is None:
        return
    try:
        await client.aclose()
    except Exception as exc:
        logger.warning("backend_client_close_failed", extra={"failure_type": type(exc).__name__})


def _safe_backend_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": "gemini_unavailable",
            "message": "Real Gemini analysis is required but unavailable.",
        },
    )


def _safe_backend_client_error(status_code: int) -> JSONResponse:
    if status_code in {400, 422}:
        content = {
            "error": "invalid_upload",
            "message": "画像または入力内容が無効です。内容を確認して、もう一度お試しください。",
        }
    else:
        content = {
            "error": "backend_request_rejected",
            "message": "分析リクエストを処理できませんでした。入力内容を確認してください。",
        }
    return JSONResponse(status_code=status_code, content=content)


def _ndjson_line(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _ndjson_error(error: str, message: str) -> bytes:
    return _ndjson_line(
        {
            "type": "error",
            "error": error,
            "message": message,
        }
    )


def _ndjson_result(payload: dict[str, Any]) -> bytes:
    return _ndjson_line({"type": "result", "payload": payload})


class _UpstreamStreamProtocolError(Exception):
    """Internal marker whose text is never logged or returned."""


_SAFE_UPSTREAM_ERRORS = {
    "gemini_unavailable": "解析サービスは現在利用できません。",
    "invalid_upload": "画像または入力内容を確認してください。",
    "analysis_failed": "分析を完了できませんでした。",
}
_EXPECTED_PROGRESS = ("intake_complete", "vision_complete")


def _safe_stream_failure(
    image_bytes: bytes,
    room_hint: str,
    reason: str,
) -> bytes:
    if FRONTEND_REQUIRE_REAL_GEMINI:
        return _ndjson_error(
            "analysis_failed",
            "分析を完了できませんでした。",
        )
    return _ndjson_result(
        _build_local_mock(
            image_bytes,
            room_hint,
            reason,
        )
    )


def _validate_upstream_event(
    event: object,
    *,
    progress_index: int,
) -> tuple[bytes, int, bool]:
    if not isinstance(event, dict):
        raise _UpstreamStreamProtocolError()
    event_type = event.get("type")
    if event_type == "progress":
        if (
            progress_index >= len(_EXPECTED_PROGRESS)
            or event.get("stage") != _EXPECTED_PROGRESS[progress_index]
        ):
            raise _UpstreamStreamProtocolError()
        stage = _EXPECTED_PROGRESS[progress_index]
        return (
            _ndjson_line({"type": "progress", "stage": stage}),
            progress_index + 1,
            False,
        )
    if event_type == "error":
        error_code = event.get("error")
        if not isinstance(error_code, str):
            raise _UpstreamStreamProtocolError()
        safe_message = _SAFE_UPSTREAM_ERRORS.get(error_code)
        if safe_message is None:
            raise _UpstreamStreamProtocolError()
        return (
            _ndjson_error(error_code, safe_message),
            progress_index,
            True,
        )
    if event_type == "result":
        if progress_index != len(_EXPECTED_PROGRESS):
            raise _UpstreamStreamProtocolError()
        try:
            response = WireAnalysisResponse.model_validate(event.get("payload"))
        except Exception as exc:
            raise _UpstreamStreamProtocolError() from exc
        return (
            _ndjson_result(response.model_dump(mode="json")),
            progress_index,
            True,
        )
    raise _UpstreamStreamProtocolError()


async def _validated_upstream_stream(
    response: httpx.Response,
) -> AsyncIterator[tuple[bytes, bool]]:
    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/x-ndjson":
        raise _UpstreamStreamProtocolError()

    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    buffer = ""
    progress_index = 0
    async for chunk in response.aiter_bytes():
        if not chunk:
            continue
        try:
            buffer += decoder.decode(chunk, final=False)
        except UnicodeDecodeError as exc:
            raise _UpstreamStreamProtocolError() from exc
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, UnicodeError) as exc:
                raise _UpstreamStreamProtocolError() from exc
            encoded, progress_index, terminal = _validate_upstream_event(
                event,
                progress_index=progress_index,
            )
            if terminal:
                try:
                    await response.aclose()
                except Exception:
                    pass
            yield encoded, terminal
            if terminal:
                return

    try:
        buffer += decoder.decode(b"", final=True)
    except UnicodeDecodeError as exc:
        raise _UpstreamStreamProtocolError() from exc
    # A final non-newline-terminated fragment is not an NDJSON record and is
    # intentionally discarded before the Web emits its own safe terminal.
    if buffer:
        raise _UpstreamStreamProtocolError()
    raise _UpstreamStreamProtocolError()


async def _proxy_analysis_stream(
    image_bytes: bytes,
    filename: str,
    content_type: str,
    room_hint: str,
) -> AsyncIterator[bytes]:
    """Forward one trusted Agent stream without polling or duplicate analysis."""
    files = {"image": (filename, image_bytes, content_type)}
    data = {
        "room_hint": room_hint,
        "mock": "true" if FRONTEND_MOCK else "false",
    }
    terminal_sent = False
    try:
        async with backend_client().stream(
            "POST",
            f"{SUMAI_AGENT_URL}/analyze/stream",
            data=data,
            files=files,
        ) as response:
            if response.status_code == 200:
                async for line, terminal in _validated_upstream_stream(
                    response
                ):
                    terminal_sent = terminal
                    yield line
                    if terminal_sent:
                        return
                raise _UpstreamStreamProtocolError()

            if response.status_code in {400, 422}:
                yield _ndjson_error(
                    "invalid_upload",
                    "画像または入力内容を確認してください。",
                )
                return

            if 400 <= response.status_code < 500:
                yield _ndjson_error(
                    "backend_request_rejected",
                    "分析リクエストを処理できませんでした。",
                )
                return

            if (
                FRONTEND_REQUIRE_REAL_GEMINI
                or response.status_code == 503
            ):
                yield _ndjson_error(
                    "gemini_unavailable",
                    "解析サービスは現在利用できません。",
                )
                return

            if 500 <= response.status_code < 600:
                yield _ndjson_result(
                    _build_local_mock(
                        image_bytes,
                        room_hint,
                        "backend_http_error",
                    )
                )
                return

            yield _ndjson_error(
                "backend_invalid_response",
                "分析サービスから有効な応答を受け取れませんでした。",
            )
            terminal_sent = True
    except _UpstreamStreamProtocolError as exc:
        logger.warning(
            "backend_stream_protocol_error",
            extra={"failure_type": type(exc).__name__},
        )
        if not terminal_sent:
            yield _safe_stream_failure(
                image_bytes,
                room_hint,
                "backend_invalid_stream",
            )
    except Exception as exc:
        logger.warning(
            "backend_stream_failed",
            extra={"failure_type": type(exc).__name__},
        )
        if not terminal_sent:
            if FRONTEND_REQUIRE_REAL_GEMINI:
                yield _ndjson_error(
                    "gemini_unavailable",
                    "解析サービスは現在利用できません。",
                )
            else:
                yield _ndjson_result(
                    _build_local_mock(
                        image_bytes,
                        room_hint,
                        "backend_unreachable",
                    )
                )


@app.get("/", response_class=HTMLResponse)
def get_home():
    return HTMLResponse(content=INDEX_HTML)


@app.post("/analyze")
async def analyze(
    image: UploadFile = File(...),
    room_hint: str = Form("auto"),
):
    """Proxy requests to sumai-agent backend with a local mock fallback if unreachable."""
    image_bytes = await image.read()

    # Call sumai-agent backend
    try:
        files = {"image": (image.filename or "photo.png", image_bytes, image.content_type or "image/png")}
        data = {"room_hint": room_hint, "mock": "true" if FRONTEND_MOCK else "false"}
        response = await backend_client().post(
            f"{SUMAI_AGENT_URL}/analyze", data=data, files=files
        )

        if response.status_code == 200:
            try:
                return JSONResponse(content=response.json())
            except Exception as exc:
                if FRONTEND_REQUIRE_REAL_GEMINI:
                    return _safe_backend_unavailable()
                logger.warning(
                    "backend_invalid_json", extra={"failure_type": type(exc).__name__}
                )
                payload = _build_local_mock(image_bytes, room_hint, "backend_invalid_response")
                return JSONResponse(content=payload)

        # Client errors describe this request, not backend availability. Preserve
        # their status without trusting or forwarding the upstream body.
        if 400 <= response.status_code < 500:
            logger.warning(
                "backend_request_rejected",
                extra={"status_code": response.status_code},
            )
            return _safe_backend_client_error(response.status_code)

        # A backend 503 always indicates that the strict provider path failed.
        # Its response body is not trusted because it may contain provider details.
        if FRONTEND_REQUIRE_REAL_GEMINI or response.status_code == 503:
            return _safe_backend_unavailable()

        if 500 <= response.status_code < 600:
            logger.warning(
                "backend_non_200", extra={"status_code": response.status_code}
            )
            payload = _build_local_mock(image_bytes, room_hint, "backend_http_error")
            return JSONResponse(content=payload)

        logger.warning(
            "backend_invalid_status", extra={"status_code": response.status_code}
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": "backend_invalid_response",
                "message": "分析サービスから有効な応答を受け取れませんでした。",
            },
        )

    except httpx.RequestError as exc:
        if FRONTEND_REQUIRE_REAL_GEMINI:
            return _safe_backend_unavailable()
        logger.warning("backend_call_failed", extra={"failure_type": type(exc).__name__})
        payload = _build_local_mock(image_bytes, room_hint, "backend_unreachable")
        return JSONResponse(content=payload)


@app.post("/analyze/stream")
async def analyze_stream(
    image: UploadFile = File(...),
    room_hint: str = Form("auto"),
) -> StreamingResponse:
    image_bytes = await image.read()
    return StreamingResponse(
        _proxy_analysis_stream(
            image_bytes,
            image.filename or "photo.png",
            image.content_type or "image/png",
            room_hint,
        ),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/ready")
def ready() -> dict[str, str]:
    return {"status": "ok"}


def _build_local_mock(image_bytes: bytes, room_hint: str, reason: str) -> dict[str, Any]:
    """Return a neutral abstention when the analysis backend is unreachable."""
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        image = Image.new("RGB", (800, 600), (15, 16, 32))

    image_base64 = _to_base64_png(image)
    pixel_payload = (
        image.mode.encode("ascii")
        + image.width.to_bytes(4, "big")
        + image.height.to_bytes(4, "big")
        + image.tobytes()
    )
    pixel_digest = hashlib.sha256(pixel_payload).hexdigest()
    result_identity = {
        "execution_mode": "local_mock_abstention",
        "inference_config_version": "1.0.6",
        "model": "N/A",
        "ontology_version": "1.0.1",
        "pixel_digest": pixel_digest,
        "preprocess_version": "1.0.0",
        "room_hint": room_hint,
        "schema_version": "2.2.0",
    }
    result_key = hashlib.sha256(
        json.dumps(
            result_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    not_applicable_reason = (
        "解析バックエンドに接続できないため、安全上の判定を保留しました。"
        f"再接続後に解析してください（{reason[:120]}）。"
    )
    semantic_hash = hashlib.sha256(
        json.dumps(
            {
                "action_plan": {
                    "care_manager_purchase": [],
                    "contractor_construction": [],
                    "family_no_cost": [],
                },
                "confirmation_items": [],
                "findings": [],
                "is_home_environment": True,
                "not_applicable_reason_ja": not_applicable_reason,
                "room_type": "auto",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    neutral_report = (
        "## 判定保留\n\n"
        f"{not_applicable_reason}\n\n"
        "この表示は写真の安全性を評価した結果ではありません。"
    )
    empty_actions = "## 表示なし\n\n判定保留中のため、行動候補を表示していません。"
    return {
        "analysis_id": f"local_{uuid.uuid4().hex}",
        "room_type": "auto",
        "assessment_status": "not_applicable",
        "overall_risk_level": "low",
        "mode": "local_mock",
        "is_home_environment": True,
        "is_not_applicable": True,
        "not_applicable_reason_ja": not_applicable_reason,
        "findings": [],
        "confirmation_items": [],
        "action_plan": {
            "family_no_cost": [],
            "care_manager_purchase": [],
            "contractor_construction": [],
        },
        "annotated_image_base64": image_base64,
        "improvement_image_base64": image_base64,
        "risk_summary_markdown": neutral_report,
        "confirmation_items_markdown": (
            "## 写真だけでは確認できない項目\n\n"
            "判定保留中のため、項目は表示していません。"
        ),
        "family_actions_markdown": empty_actions,
        "care_manager_actions_markdown": empty_actions,
        "contractor_actions_markdown": empty_actions,
        "disclaimer_ja": DISCLAIMER,
        "model": "N/A",
        "result_key": result_key,
        "semantic_hash": semantic_hash,
        "schema_version": "2.2.0",
        "ontology_version": "1.0.1",
        "preprocess_version": "1.0.0",
        "inference_config_version": "1.0.6",
        "stage_timings_ms": {
            "intake": 0,
            "memo_lookup": 0,
            "vision": 0,
            "ontology": 0,
            "render": 0,
            "report": 0,
            "serialize": 0,
            "total": 0,
        },
    }


def _to_base64_png(image: Image.Image) -> str:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return base64.b64encode(output.getvalue()).decode("ascii")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=SUMAI_WEB_PORT, reload=True)
