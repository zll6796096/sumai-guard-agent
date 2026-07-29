from __future__ import annotations

import logging
from pathlib import Path

from app.models import RiskFinding, VisionResult
from app.ontology import OntologyRepository

logger = logging.getLogger("sumai.checklist_engine")


class ChecklistEngine:
    def __init__(
        self,
        checklists_path: Path | None = None,
        ontology: OntologyRepository | None = None,
    ) -> None:
        if checklists_path is not None and ontology is not None:
            raise ValueError("Pass either checklists_path or ontology, not both")
        self.checklists_path = checklists_path
        self.ontology = (
            ontology
            if ontology is not None
            else OntologyRepository.load(checklists_path)
            if checklists_path is not None
            else OntologyRepository.load_default()
        )

    def process(self, vision_result: VisionResult) -> list[RiskFinding]:
        findings: list[RiskFinding] = []
        room = vision_result.room_type
        room_checklist = self.ontology.room(room)
        if not room_checklist:
            logger.warning("No checklist found for room: %s", room)
            return vision_result.visible_hazards

        expected_features = room_checklist.get("expected_features", [])
        missing_map = {item.feature_key: item for item in vision_result.missing_safety_features}

        for feature in expected_features:
            if not isinstance(feature, dict):
                continue
            key = feature.get("key")
            missing_risk_type = feature.get("missing_risk_type")
            if not isinstance(key, str) or not isinstance(missing_risk_type, str):
                continue
            # A boolean legacy observation carries no location. Only an explicit
            # coordinate-backed MissingSafetyFeature can become a visual finding.
            if key not in missing_map:
                continue

            missing = missing_map[key]
            confidence = missing.confidence
            bbox = missing.bbox
            evidence = missing.evidence_ja
            if confidence < 0.60:
                continue

            rule = self.ontology.rule(room, key, "expected_feature")
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
                    ontology_key=rule.key,
                    ontology_rule_kind=rule.rule_kind,
                )
            )

        for finding in vision_result.visible_hazards:
            if finding.confidence < 0.45:
                continue
            try:
                rule = (
                    self.ontology.rule(
                        room, finding.ontology_key, finding.ontology_rule_kind
                    )
                    if finding.ontology_key and finding.ontology_rule_kind
                    else self.ontology.risk_rule(room, finding.risk_type)
                )
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
                        "ontology_key": rule.key,
                        "ontology_rule_kind": rule.rule_kind,
                    }
                )
            )

        return findings
