from __future__ import annotations

import logging
import time
import uuid

from fastapi import UploadFile
from PIL import Image

from app.models import AnalysisResponse, RiskFinding, RiskLevel, RoomType, VisionFacts, VisionResult
from app.services.gemini_vision import GeminiVisionService, mock_vision_result, normalize_room_hint
from app.services.checklist_engine import ChecklistEngine
from app.services.image_intake import read_and_sanitize_image
from app.services.report_renderer import ReportRenderer
from app.services.rule_engine import RuleEngine
from app.services.visual_renderer import VisualRenderer


logger = logging.getLogger("sumai.orchestrator")

DISCLAIMER_JA = (
    "POC版です。医療・介護・施工判断を代替しません。"
    "改善イメージはコミュニケーション用であり施工図ではありません。"
    "写真から正確な寸法や適用制度を判断するものではありません。"
)


class AnalysisOrchestrator:
    def __init__(self) -> None:
        self.vision = GeminiVisionService()
        self.checklist_engine = ChecklistEngine()
        self.rule_engine = RuleEngine()
        self.visual_renderer = VisualRenderer()
        self.report_renderer = ReportRenderer()

    async def analyze(self, upload: UploadFile, room_hint: str = "auto", mock: bool = False) -> AnalysisResponse:
        analysis_id = f"sumai_{uuid.uuid4().hex[:12]}"
        start_time = time.monotonic()
        normalized_hint = normalize_room_hint(room_hint)

        logger.info(
            "analysis_start",
            extra={
                "analysis_id": analysis_id,
                "room_hint": normalized_hint,
            },
        )

        raw_bytes = await upload.read()
        image, safe_png = read_and_sanitize_image(raw_bytes)

        vision_facts, mode = await self.vision.analyze(
            image_png=safe_png,
            room_hint=normalized_hint,
            force_mock=mock,
            analysis_id=analysis_id,
        )
        vision_result = _legacy_result_for_checklist(
            vision_facts,
            mode=mode,
            room_hint=normalized_hint,
        )
        checklist_findings = self.checklist_engine.process(vision_result)
        findings, action_plan = self.rule_engine.apply(
            checklist_findings, vision_result.room_type
        )
        overall_risk = overall_risk_level(findings)
        annotated, improvement = self.visual_renderer.render(image, findings, vision_result.room_type)
        reports = self.report_renderer.render(
            room_type=vision_result.room_type,
            overall_risk_level=overall_risk,
            findings=findings,
            action_plan=action_plan,
        )

        latency_ms = int((time.monotonic() - start_time) * 1000)
        model_name = "N/A" if mode == "mock" else __import__("app.config", fromlist=["settings"]).settings.gemini_model
        logger.info(
            "analysis_complete",
            extra={
                "analysis_id": analysis_id,
                "room_hint": normalized_hint,
                "mock_or_gemini": mode,
                "model": model_name,
                "number_of_findings": len(findings),
                "latency_ms": latency_ms,
            },
        )

        return AnalysisResponse(
            analysis_id=analysis_id,
            room_type=vision_result.room_type,
            overall_risk_level=overall_risk,
            findings=findings,
            action_plan=action_plan,
            annotated_image_base64=annotated,
            improvement_image_base64=improvement,
            disclaimer_ja=DISCLAIMER_JA,
            mode=mode,
            is_home_environment=vision_result.is_home_environment,
            not_applicable_reason_ja=vision_result.not_applicable_reason_ja,
            model=model_name,
            **reports,
        )


def overall_risk_level(findings: list[RiskFinding]) -> RiskLevel:
    if not findings:
        return "low"
    max_severity = max(finding.severity for finding in findings)
    if max_severity >= 4:
        return "high"
    if max_severity >= 2:
        return "medium"
    return "low"


def _legacy_result_for_checklist(
    vision_facts: VisionFacts | VisionResult,
    *,
    mode: str,
    room_hint: RoomType,
) -> VisionResult:
    """Temporary Task 2 bridge until Task 3 derives findings from relationships.

    Gemini facts intentionally do not become risk findings here.  The deterministic
    demo/fallback fixture remains available so the existing local mock UX and its
    regression tests retain their established behavior.  This is not a relationship
    inference engine and must be removed when the formal Task 3 engine is wired in.
    """
    if isinstance(vision_facts, VisionResult):
        # Supports existing callers that inject the legacy model during transition.
        return vision_facts
    if mode == "mock" or mode.startswith("gemini_fallback("):
        return mock_vision_result(room_hint)
    if vision_facts.environment != "home":
        return VisionResult(
            room_type="auto",
            is_home_environment=False,
            not_applicable_reason_ja="住宅内の安全確認対象ではない可能性があります。",
        )
    room_type: RoomType = (
        vision_facts.room_type if vision_facts.room_type != "unknown" else "auto"
    )
    return VisionResult(room_type=room_type, is_home_environment=True)


def image_from_png_bytes(image_bytes: bytes) -> Image.Image:
    image, _ = read_and_sanitize_image(image_bytes)
    return image
