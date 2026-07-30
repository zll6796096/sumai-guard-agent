from __future__ import annotations

import sys
from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(autouse=True)
def _fresh_process_local_memo_for_endpoint_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """The application memo is intentionally process-local, so tests get a fresh process state."""
    from app import main
    from app.services.orchestrator import AnalysisOrchestrator

    monkeypatch.setattr(main, "orchestrator", AnalysisOrchestrator())
