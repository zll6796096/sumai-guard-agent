from __future__ import annotations

import logging
from pathlib import Path

from app.models import RiskFinding, VisionResult
from app.ontology import OntologyRepository
from app.services.rule_engine import RuleEngine

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
        self.rule_engine = RuleEngine(ontology=self.ontology)

    def process(self, vision_result: VisionResult) -> list[RiskFinding]:
        room = vision_result.room_type
        if not vision_result.is_home_environment:
            logger.warning(
                "checklist_skipped_non_home",
                extra={"room_type": room},
            )
            return []
        if room == "auto":
            logger.warning(
                "checklist_skipped_auto_room",
                extra={"room_type": room},
            )
            return []
        if self.ontology.room(room) is None:
            logger.warning(
                "checklist_skipped_unknown_room",
                extra={"room_type": room},
            )
            return []

        # This compatibility adapter has no neutral confirmation return channel.
        # Legacy observations and missing_safety_features therefore cannot safely
        # become RiskFinding objects. Apply the shared visible-only policy gate to
        # the one legacy collection that can carry localized visible evidence.
        return self.rule_engine.apply(vision_result.visible_hazards, room)[0]
