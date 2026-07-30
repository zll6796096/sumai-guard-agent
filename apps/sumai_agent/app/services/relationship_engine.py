from __future__ import annotations

from app.models import BoundingBox, RiskFinding, VisionFacts
from app.ontology import OntologyRepository


def _is_full_frame_placeholder(bbox: BoundingBox) -> bool:
    return (
        bbox.x <= 0.01
        and bbox.y <= 0.01
        and bbox.x + bbox.w >= 0.99
        and bbox.y + bbox.h >= 0.99
    )


class RelationshipEngine:
    """Maps typed visual evidence to ontology-scoped findings deterministically."""

    def __init__(self, ontology: OntologyRepository) -> None:
        self.ontology = ontology

    def derive(self, facts: VisionFacts) -> list[RiskFinding]:
        if facts.environment != "home" or facts.room_type not in self.ontology.room_names:
            return []

        entity_refs = [entity.ref for entity in facts.entities]
        feature_keys = [feature.feature_key for feature in facts.feature_observations]
        visible_regions = set(facts.visible_regions)
        if (
            len(entity_refs) != len(set(entity_refs))
            or len(feature_keys) != len(set(feature_keys))
            or not visible_regions <= set(self.ontology.visible_region_keys)
        ):
            return []
        valid_reference_objects = set(entity_refs) | visible_regions
        if any(
            relationship.subject not in set(entity_refs)
            or relationship.object not in valid_reference_objects
            for relationship in facts.relationships
        ):
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
        relationship_triples = {
            (relationship.subject, relationship.predicate, relationship.object)
            for relationship in facts.relationships
        }

        for entity in facts.entities:
            if (
                entity.ontology_key not in visible_hazards
                or entity.visibility != "clear"
                or _is_full_frame_placeholder(entity.bbox)
                or not any(
                    (
                        entity.ref,
                        self.ontology.required_predicate(entity.ontology_key),
                        target,
                    )
                    in relationship_triples
                    for target in self.ontology.required_targets(entity.ontology_key)
                )
            ):
                continue
            rule = self.ontology.rule(
                room, entity.ontology_key, "visible_hazard"
            )
            findings.append(
                RiskFinding(
                    id="pending",
                    risk_type=rule.risk_type,
                    label_ja=rule.label_ja,
                    description_ja=f"{rule.label_ja}が写真で確認されました。",
                    severity=rule.severity,
                    confidence=entity.model_score,
                    bbox=entity.bbox,
                    display_bbox=None,
                    evidence_source_ids=list(rule.evidence_source_ids),
                    evidence_ja="写真内の表示範囲に可視の根拠があります。",
                    basis_label_ja=rule.basis_label_ja,
                    basis_summary_ja=rule.basis_summary_ja,
                    needs_human_confirmation=entity.model_score < 0.60,
                    ontology_key=rule.key,
                    ontology_rule_kind=rule.rule_kind,
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
                or _is_full_frame_placeholder(feature.evidence_bbox)
            ):
                continue
            rule = self.ontology.rule(
                room, feature.feature_key, "expected_feature"
            )
            expected_feature_label = str(
                expected_features[feature.feature_key]["label_ja"]
            )
            findings.append(
                RiskFinding(
                    id="pending",
                    risk_type=rule.risk_type,
                    label_ja=rule.label_ja,
                    description_ja=(
                        "写真で十分に表示された範囲では、"
                        f"{expected_feature_label}を確認できませんでした。"
                    ),
                    severity=rule.severity,
                    confidence=feature.model_score,
                    bbox=feature.evidence_bbox,
                    display_bbox=None,
                    evidence_source_ids=list(rule.evidence_source_ids),
                    evidence_ja=(
                        f"写真内で{expected_feature_label}を確認する対象範囲が表示されています。"
                        "この範囲は不存在や設置位置を示すものではありません。"
                    ),
                    basis_label_ja=rule.basis_label_ja,
                    basis_summary_ja=rule.basis_summary_ja,
                    # One photo can support a cautious non-detection, but it
                    # cannot prove absence or determine whether/where to install.
                    needs_human_confirmation=True,
                    ontology_key=rule.key,
                    ontology_rule_kind=rule.rule_kind,
                )
            )
        return findings
