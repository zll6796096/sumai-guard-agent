from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.models import BoundingBox, RiskFinding, RoomType, VisionResult, MissingSafetyFeature

logger = logging.getLogger("sumai.checklist_engine")


class ChecklistEngine:
    def __init__(self, checklists_path: Path | None = None) -> None:
        if checklists_path is None:
            checklists_path = Path(__file__).resolve().parents[1] / "knowledge_base" / "room_checklists.yaml"
        self.checklists_path = checklists_path
        self.checklists = self._load_checklists()

    def _load_checklists(self) -> dict[str, Any]:
        try:
            with self.checklists_path.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load room checklists: {e}")
            return {}

    def process(self, vision_result: VisionResult) -> list[RiskFinding]:
        findings: list[RiskFinding] = []
        room = vision_result.room_type

        # If not a valid room or doesn't exist in checklists, skip checklist logic but preserve visible hazards
        room_checklist = self.checklists.get(room)
        if not room_checklist:
            logger.warning(f"No checklist found for room: {room}")
            return vision_result.visible_hazards

        expected_features = room_checklist.get("expected_features", [])
        visible_hazards_checklist = room_checklist.get("visible_hazards", [])

        # Map expected features (check for missing features)
        missing_map = {m.feature_key: m for m in vision_result.missing_safety_features}
        for feature in expected_features:
            key = feature["key"]
            obs_val = vision_result.observations.get(key)

            # If Gemini explicitly says false, or if it is present in missing_safety_features list
            is_missing = (obs_val is False) or (key in missing_map)
            if not is_missing:
                continue

            # Find confidence, default to 0.80 if not explicitly defined in missing list
            confidence = 0.80
            bbox = BoundingBox(x=0.0, y=0.0, w=0.0, h=0.0)
            evidence = "写真内に対象項目が確認できません。"

            if key in missing_map:
                m_feat = missing_map[key]
                confidence = m_feat.confidence
                bbox = m_feat.bbox
                evidence = m_feat.evidence_ja
            elif obs_val is False:
                evidence = f"写真内に{feature['label_ja']}が確認できません。"

            # Filter by confidence
            if confidence < 0.60:
                continue

            needs_confirm = confidence < 0.75

            finding = RiskFinding(
                id=feature["missing_risk_type"],
                risk_type=feature["missing_risk_type"],
                label_ja=feature["missing_label_ja"],
                description_ja=f"写真内に{feature['label_ja']}が確認できず、高齢者の安全に影響を及ぼす可能性があります。",
                severity=feature["severity"],
                confidence=confidence,
                bbox=bbox,
                evidence_ja=evidence,
                basis_label_ja=feature["basis_label_ja"],
                basis_summary_ja=feature["basis_summary_ja"],
                needs_human_confirmation=needs_confirm,
            )
            findings.append(finding)

        # Map visible hazards
        # Map checklist hazards by key for quick lookup
        hazard_check_map = {h["key"]: h for h in visible_hazards_checklist}
        
        # 1. Process hazards from vision_result.visible_hazards
        for g_finding in vision_result.visible_hazards:
            if g_finding.confidence < 0.45:
                continue

            # Check if this hazard type maps to any checklist item in this room
            chk_hazard = None
            for h in visible_hazards_checklist:
                if h["risk_type"] == g_finding.risk_type:
                    chk_hazard = h
                    break

            if chk_hazard:
                # Enrich with checklist definitions
                enriched = g_finding.model_copy(
                    update={
                        "severity": chk_hazard["severity"],
                        "basis_label_ja": chk_hazard["basis_label_ja"],
                        "basis_summary_ja": chk_hazard["basis_summary_ja"],
                        "needs_human_confirmation": g_finding.confidence < 0.60
                    }
                )
                findings.append(enriched)
            else:
                # Preserve general hazards if confidence is high enough
                if g_finding.confidence >= 0.60:
                    findings.append(g_finding)

        # 2. Also check observations for true values that weren't captured in visible_hazards list
        existing_types = {f.risk_type for f in findings}
        for key, obs_val in vision_result.observations.items():
            if obs_val is True and key in hazard_check_map:
                chk_hazard = hazard_check_map[key]
                if chk_hazard["risk_type"] not in existing_types:
                    # Generate a finding based on checklist info
                    finding = RiskFinding(
                        id=chk_hazard["risk_type"],
                        risk_type=chk_hazard["risk_type"],
                        label_ja=chk_hazard["label_ja"],
                        description_ja=f"写真内に{chk_hazard['label_ja']}が観察され、転倒やつまずきのリスクがあります。",
                        severity=chk_hazard["severity"],
                        confidence=0.80,
                        bbox=BoundingBox(x=0.0, y=0.0, w=0.0, h=0.0),
                        evidence_ja=f"写真観察により{chk_hazard['label_ja']}が確認されました。",
                        basis_label_ja=chk_hazard["basis_label_ja"],
                        basis_summary_ja=chk_hazard["basis_summary_ja"],
                        needs_human_confirmation=False,
                    )
                    findings.append(finding)

        return findings
