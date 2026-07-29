from __future__ import annotations

import logging

from app.models import BoundingBox, RiskFinding, VisionResult
from app.ontology import OntologyRepository

logger = logging.getLogger("sumai.checklist_engine")


class ChecklistEngine:
    def __init__(self) -> None:
        self.ontology = OntologyRepository.load_default()

    def process(self, vision_result: VisionResult) -> list[RiskFinding]:
        findings: list[RiskFinding] = []
        room = vision_result.room_type
        room_checklist = self.ontology.room(room)
        if not room_checklist:
            logger.warning("No checklist found for room: %s", room)
            return vision_result.visible_hazards

        expected_features = room_checklist.get("expected_features", [])
        visible_hazards = room_checklist.get("visible_hazards", [])
        missing_map = {item.feature_key: item for item in vision_result.missing_safety_features}

        for feature in expected_features:
            if not isinstance(feature, dict):
                continue
            key = feature.get("key")
            missing_risk_type = feature.get("missing_risk_type")
            if not isinstance(key, str) or not isinstance(missing_risk_type, str):
                continue
            observation = vision_result.observations.get(key)
            if observation is not False and key not in missing_map:
                continue

            confidence = 0.80
            bbox = BoundingBox(x=0.0, y=0.0, w=0.0, h=0.0)
            evidence = "写真内に対象項目が確認できません。"
            if key in missing_map:
                missing = missing_map[key]
                confidence = missing.confidence
                bbox = missing.bbox
                evidence = missing.evidence_ja
            elif observation is False:
                evidence = f"写真内に{feature.get('label_ja', '')}が確認できません。"
            if confidence < 0.60:
                continue

            rule = self.ontology.risk_rule(room, missing_risk_type)
            findings.append(
                RiskFinding(
                    id=rule.risk_type,
                    risk_type=rule.risk_type,
                    label_ja=rule.label_ja,
                    description_ja=(
                        f"写真内に{feature.get('label_ja', '')}が確認できず、"
                        "高齢者の安全に影響を及ぼす可能性があります。"
                    ),
                    severity=rule.severity,
                    confidence=confidence,
                    bbox=bbox,
                    evidence_ja=evidence,
                    basis_label_ja=rule.basis_label_ja,
                    basis_summary_ja=rule.basis_summary_ja,
                    needs_human_confirmation=confidence < 0.75,
                )
            )

        hazard_check_map = {
            item["key"]: item
            for item in visible_hazards
            if isinstance(item, dict) and isinstance(item.get("key"), str)
        }
        for finding in vision_result.visible_hazards:
            if finding.confidence < 0.45:
                continue
            try:
                rule = self.ontology.risk_rule(room, finding.risk_type)
            except KeyError:
                if finding.confidence >= 0.60:
                    findings.append(finding)
                continue
            findings.append(
                finding.model_copy(
                    update={
                        "severity": rule.severity,
                        "basis_label_ja": rule.basis_label_ja,
                        "basis_summary_ja": rule.basis_summary_ja,
                        "needs_human_confirmation": finding.confidence < 0.60,
                    }
                )
            )

        existing_types = {finding.risk_type for finding in findings}
        for key, observation in vision_result.observations.items():
            if observation is not True or key not in hazard_check_map:
                continue
            risk_type = hazard_check_map[key].get("risk_type")
            if not isinstance(risk_type, str) or risk_type in existing_types:
                continue
            rule = self.ontology.risk_rule(room, risk_type)
            findings.append(
                RiskFinding(
                    id=rule.risk_type,
                    risk_type=rule.risk_type,
                    label_ja=rule.label_ja,
                    description_ja=(
                        f"写真内に{rule.label_ja}が観察され、"
                        "転倒やつまずきのリスクがあります。"
                    ),
                    severity=rule.severity,
                    confidence=0.80,
                    bbox=BoundingBox(x=0.0, y=0.0, w=0.0, h=0.0),
                    evidence_ja=f"写真観察により{rule.label_ja}が確認されました。",
                    basis_label_ja=rule.basis_label_ja,
                    basis_summary_ja=rule.basis_summary_ja,
                    needs_human_confirmation=False,
                )
            )
        return findings
