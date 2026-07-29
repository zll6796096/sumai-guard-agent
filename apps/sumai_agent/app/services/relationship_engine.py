from __future__ import annotations

from app.models import RiskFinding, VisionFacts
from app.ontology import OntologyRepository


class RelationshipEngine:
    """Maps typed visual evidence to ontology-scoped findings deterministically."""

    def __init__(self, ontology: OntologyRepository) -> None:
        self.ontology = ontology

    def derive(self, facts: VisionFacts) -> list[RiskFinding]:
        if facts.environment != "home" or facts.room_type not in self.ontology.room_names:
            return []

        room = facts.room_type
        room_data = self.ontology.room(room)
        if room_data is None:
            return []
        findings: list[RiskFinding] = []
        visible_hazards = {
            item["key"]: item
            for item in room_data["visible_hazards"]
        }
        relationship_pairs = {
            (relationship.subject, relationship.predicate)
            for relationship in facts.relationships
        }

        for entity in facts.entities:
            if (
                entity.ontology_key not in visible_hazards
                or entity.visibility != "clear"
                or (entity.ref, self.ontology.required_predicate(entity.ontology_key))
                not in relationship_pairs
            ):
                continue
            risk_type = visible_hazards[entity.ontology_key]["risk_type"]
            rule = self.ontology.risk_rule(room, risk_type)
            findings.append(
                RiskFinding(
                    id="pending",
                    risk_type=rule.risk_type,
                    label_ja=rule.label_ja,
                    description_ja=f"{rule.label_ja}が写真で確認されました。",
                    severity=rule.severity,
                    confidence=entity.model_score,
                    bbox=entity.bbox,
                    evidence_ja="写真内の表示範囲に可視の根拠があります。",
                    basis_label_ja=rule.basis_label_ja,
                    basis_summary_ja=rule.basis_summary_ja,
                    needs_human_confirmation=entity.model_score < 0.60,
                )
            )

        expected_features = {
            item["key"]: item
            for item in room_data["expected_features"]
        }
        for feature in facts.feature_observations:
            if (
                feature.feature_key not in expected_features
                or feature.state != "absent_with_full_coverage"
                or feature.evidence_bbox is None
            ):
                continue
            risk_type = expected_features[feature.feature_key]["missing_risk_type"]
            rule = self.ontology.risk_rule(room, risk_type)
            findings.append(
                RiskFinding(
                    id="pending",
                    risk_type=rule.risk_type,
                    label_ja=rule.label_ja,
                    description_ja=(
                        f"写真で十分に表示された範囲では、{rule.label_ja}を確認できませんでした。"
                    ),
                    severity=rule.severity,
                    confidence=feature.model_score,
                    bbox=feature.evidence_bbox,
                    evidence_ja="写真内の十分に表示された範囲に可視の根拠があります。",
                    basis_label_ja=rule.basis_label_ja,
                    basis_summary_ja=rule.basis_summary_ja,
                    needs_human_confirmation=feature.model_score < 0.60,
                )
            )
        return findings
