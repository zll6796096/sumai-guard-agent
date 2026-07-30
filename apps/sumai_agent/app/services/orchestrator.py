from __future__ import annotations

import asyncio
import logging
import time
import unicodedata
import uuid
from dataclasses import dataclass

from fastapi import UploadFile
from PIL import Image

from app.config import settings
from app.models import (
    ActionPlan,
    AnalysisResponse,
    ConfirmationItem,
    RiskFinding,
    RiskLevel,
    RoomType,
    VisionFacts,
)
from app.ontology import OntologyRepository
from app.services.canonicalization import (
    canonical_pixel_digest,
    canonicalize_confirmation_items,
    canonicalize_findings,
    normalize_signed_zero,
    result_key,
    semantic_hash,
)
from app.services.gemini_vision import GeminiVisionService, normalize_room_hint
from app.services.checklist_engine import ChecklistEngine
from app.services.image_intake import PREPROCESS_VERSION, read_and_sanitize_image
from app.services.relationship_engine import RelationshipEngine
from app.services.report_renderer import ReportRenderer
from app.services.result_memo import AsyncResultMemo
from app.services.rule_engine import RuleEngine
from app.services.visual_renderer import VisualRenderer


logger = logging.getLogger("sumai.orchestrator")

STAGE_TIMING_KEYS = (
    "intake",
    "memo_lookup",
    "vision",
    "ontology",
    "render",
    "report",
    "serialize",
    "total",
)

DISCLAIMER_JA = (
    "POC版です。医療・介護・施工判断を代替しません。"
    "改善イメージはコミュニケーション用であり施工図ではありません。"
    "写真から正確な寸法や適用制度を判断するものではありません。"
)


@dataclass
class ComputedAnalysis:
    """Structured semantic output only; request images remain outside the memo."""

    response_room: RoomType
    overall_risk: RiskLevel
    findings: list[RiskFinding]
    confirmation_items: list[ConfirmationItem]
    action_plan: ActionPlan
    reports: dict[str, str]
    mode: str
    model_name: str
    semantic_hash: str
    is_home_environment: bool
    not_applicable_reason_ja: str | None
    is_not_applicable: bool


class AnalysisOrchestrator:
    def __init__(
        self,
        *,
        vision: GeminiVisionService | None = None,
        result_memo: AsyncResultMemo[ComputedAnalysis] | None = None,
    ) -> None:
        self.vision = vision or GeminiVisionService()
        self.ontology = OntologyRepository.load_default()
        self.checklist_engine = ChecklistEngine(ontology=self.ontology)
        self.relationship_engine = RelationshipEngine(self.ontology)
        self.rule_engine = RuleEngine(ontology=self.ontology)
        self.visual_renderer = VisualRenderer()
        self.report_renderer = ReportRenderer()
        self.result_memo = result_memo or AsyncResultMemo(
            max_items=settings.result_memo_max_items,
            ttl_seconds=settings.result_memo_ttl_seconds,
        )

    async def aclose(self) -> None:
        await self.vision.aclose()

    async def analyze(self, upload: UploadFile, room_hint: str = "auto", mock: bool = False) -> AnalysisResponse:
        analysis_id = f"sumai_{uuid.uuid4().hex[:12]}"
        stage_timings_ms = _empty_stage_timings()
        normalized_hint = normalize_room_hint(room_hint)

        logger.info(
            "analysis_start",
            extra={
                "analysis_id": analysis_id,
                "room_hint": normalized_hint,
            },
        )

        intake_started = time.monotonic()
        raw_bytes = await upload.read()
        image, safe_png, pixel_digest = await asyncio.to_thread(_prepare_image, raw_bytes)
        stage_timings_ms["intake"] = elapsed_ms(intake_started)
        execution_mode = execution_mode_for_request(force_mock=mock)
        configured_model = settings.gemini_model
        stable_result_key = result_key(
            pixel_digest=pixel_digest,
            room_hint=normalized_hint,
            preprocess_version=PREPROCESS_VERSION,
            ontology_version=self.ontology.version,
            schema_version=self.ontology.schema_version,
            model=configured_model,
            inference_config_version=self.ontology.inference_config_version,
            execution_mode=execution_mode,
        )

        async def compute_semantics() -> tuple[ComputedAnalysis, bool]:
            factory_ran[0] = True
            vision_started = time.monotonic()
            vision_facts, mode = await self.vision.analyze(
                image_png=safe_png,
                room_hint=normalized_hint,
                force_mock=mock,
                analysis_id=analysis_id,
            )
            stage_timings_ms["vision"] = elapsed_ms(vision_started)

            ontology_started = time.monotonic()
            response_room: RoomType = (
                vision_facts.room_type
                if vision_facts.room_type in self.ontology.room_names
                else "auto"
            )
            findings: list[RiskFinding] = []
            confirmation_items: list[ConfirmationItem] = []
            action_plan = ActionPlan()
            is_home_environment = vision_facts.environment == "home"
            is_not_applicable = (
                not is_home_environment
                or vision_facts.room_type == "unknown"
                or vision_facts.not_applicable_reason_code is not None
            )
            if is_not_applicable:
                response_room = "auto"
            not_applicable_reason_ja = _not_applicable_reason(vision_facts, response_room)
            if not is_not_applicable:
                derivation = self.relationship_engine.derive(vision_facts)
                visible_findings = canonicalize_findings(
                    derivation.visible_findings
                )
                confirmation_items = canonicalize_confirmation_items(
                    derivation.confirmation_items
                )
                findings, action_plan = self.rule_engine.apply(
                    visible_findings, response_room
                )
            overall_risk = overall_risk_level(findings)
            model_name = "N/A" if mode == "mock" else configured_model
            stable_semantic_hash = semantic_hash(
                analysis_semantic_payload(
                    response_room,
                    findings,
                    action_plan,
                    confirmation_items=confirmation_items,
                    is_home_environment=is_home_environment,
                    not_applicable_reason_ja=not_applicable_reason_ja,
                )
            )
            stage_timings_ms["ontology"] = elapsed_ms(ontology_started)

            report_started = time.monotonic()
            if is_not_applicable:
                reports = self.report_renderer.render_not_applicable(
                    not_applicable_reason_ja or "写真から判定できません。"
                )
            else:
                reports = self.report_renderer.render(
                    room_type=response_room,
                    overall_risk_level=overall_risk,
                    findings=findings,
                    confirmation_items=confirmation_items,
                    action_plan=action_plan,
                )
            stage_timings_ms["report"] = elapsed_ms(report_started)
            return (
                ComputedAnalysis(
                    response_room=response_room,
                    overall_risk=overall_risk,
                    findings=findings,
                    confirmation_items=confirmation_items,
                    action_plan=action_plan,
                    reports=reports,
                    mode=mode,
                    model_name=model_name,
                    semantic_hash=stable_semantic_hash,
                    is_home_environment=is_home_environment,
                    not_applicable_reason_ja=not_applicable_reason_ja,
                    is_not_applicable=is_not_applicable,
                ),
                mode in {"mock", "gemini"},
            )

        # Only the factory owner records vision/ontology/report. Cached requests and
        # coalesced followers attribute their wait time to memo_lookup instead.
        factory_ran = [False]
        memo_started = time.monotonic()
        computed, memo_hit = await self.result_memo.get_or_compute(
            stable_result_key, compute_semantics
        )
        memo_elapsed = elapsed_ms(memo_started)
        if factory_ran[0]:
            stage_timings_ms["memo_lookup"] = max(
                0,
                memo_elapsed
                - stage_timings_ms["vision"]
                - stage_timings_ms["ontology"]
                - stage_timings_ms["report"],
            )
        else:
            stage_timings_ms["memo_lookup"] = memo_elapsed

        render_started = time.monotonic()
        if computed.is_not_applicable:
            annotated, improvement = await asyncio.to_thread(
                self.visual_renderer.render_not_applicable, image
            )
        else:
            annotated, improvement = await asyncio.to_thread(
                self.visual_renderer.render,
                image, computed.findings, computed.response_room
            )
        stage_timings_ms["render"] = elapsed_ms(render_started)
        _set_total(stage_timings_ms)

        response = AnalysisResponse(
            analysis_id=analysis_id,
            room_type=computed.response_room,
            overall_risk_level=computed.overall_risk,
            findings=computed.findings,
            confirmation_items=computed.confirmation_items,
            action_plan=computed.action_plan,
            annotated_image_base64=annotated,
            improvement_image_base64=improvement,
            disclaimer_ja=DISCLAIMER_JA,
            mode=computed.mode,
            is_home_environment=computed.is_home_environment,
            is_not_applicable=computed.is_not_applicable,
            not_applicable_reason_ja=computed.not_applicable_reason_ja,
            model=computed.model_name,
            result_key=stable_result_key,
            semantic_hash=computed.semantic_hash,
            schema_version=self.ontology.schema_version,
            ontology_version=self.ontology.version,
            preprocess_version=PREPROCESS_VERSION,
            inference_config_version=self.ontology.inference_config_version,
            stage_timings_ms=stage_timings_ms,
            **computed.reports,
        )
        response._cache_hit = memo_hit
        return response


def execution_mode_for_request(*, force_mock: bool) -> str:
    """Describe execution policy before provider work, for deterministic request identity."""
    if settings.require_real_gemini:
        return "strict_gemini"
    if force_mock:
        return "forced_mock"
    if settings.mock_mode:
        return "configured_mock"
    if not settings.gemini_api_key:
        return "missing_key_mock"
    return "gemini_with_fallback"


def analysis_semantic_payload(
    room_type: RoomType,
    findings: list[RiskFinding],
    action_plan: ActionPlan,
    *,
    confirmation_items: list[ConfirmationItem] | None = None,
    is_home_environment: bool = True,
    not_applicable_reason_ja: str | None = None,
) -> dict[str, object]:
    """Build semantic output only; request/presentation data are intentionally excluded."""
    payload = {
        "room_type": room_type.strip().lower(),
        "is_home_environment": is_home_environment,
        "not_applicable_reason_ja": (
            unicodedata.normalize("NFC", not_applicable_reason_ja).strip()
            if not_applicable_reason_ja is not None
            else None
        ),
        "findings": [
            finding.model_dump(mode="json", exclude={"display_bbox"})
            for finding in findings
        ],
        "confirmation_items": [
            item.model_dump(mode="json")
            for item in (confirmation_items or [])
        ],
        "action_plan": action_plan.model_dump(mode="json"),
    }
    return normalize_signed_zero(payload)


def overall_risk_level(findings: list[RiskFinding]) -> RiskLevel:
    if not findings:
        return "low"
    max_severity = max(finding.severity for finding in findings)
    if max_severity >= 4:
        return "high"
    if max_severity >= 2:
        return "medium"
    return "low"


def _not_applicable_reason(
    vision_facts: VisionFacts, response_room: RoomType
) -> str | None:
    if vision_facts.environment != "home":
        return "住宅内の安全確認対象ではない可能性があります。"
    if vision_facts.not_applicable_reason_code is not None:
        return "写真から十分に確認できないため、結果を表示していません。"
    if response_room == "auto":
        return "写真から確認対象の部屋を特定できないため、結果を表示していません。"
    return None


def image_from_png_bytes(image_bytes: bytes) -> Image.Image:
    image, _ = read_and_sanitize_image(image_bytes)
    return image


def elapsed_ms(start: float) -> int:
    """Return a non-negative monotonic elapsed duration rounded down to milliseconds."""
    return max(0, int((time.monotonic() - start) * 1000))


def _prepare_image(raw_bytes: bytes) -> tuple[Image.Image, bytes, str]:
    """Run image decoding, EXIF stripping, and pixel digesting off the event loop."""
    image, safe_png = read_and_sanitize_image(raw_bytes)
    return image, safe_png, canonical_pixel_digest(image)


def _empty_stage_timings() -> dict[str, int]:
    return {key: 0 for key in STAGE_TIMING_KEYS}


def _set_total(stage_timings_ms: dict[str, int]) -> None:
    """Sum instrumented app stages, excluding JSON encoding, socket, and network latency."""
    stage_timings_ms["total"] = sum(
        value for key, value in stage_timings_ms.items() if key != "total"
    )
