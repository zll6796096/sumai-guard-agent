from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import verify_hackathon_video as verifier


REPO_ROOT = Path(__file__).resolve().parents[2]
IMPLEMENTATION_PLAN = (
    REPO_ROOT
    / "docs/superpowers/plans/2026-07-11-hackathon-submission-video.md"
)


def test_prohibited_text_scan_accepts_runtime_terms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = tmp_path / "renderer.py"
    manifest = tmp_path / "manifest.py"
    renderer.write_text("runtime-private-marker", encoding="utf-8")
    manifest.write_text("safe", encoding="utf-8")
    monkeypatch.setattr(verifier, "RENDERER", renderer)
    monkeypatch.setattr(verifier, "MANIFEST", manifest)

    with pytest.raises(AssertionError) as exc_info:
        verifier.verify_prohibited_text(
            "",
            extra_terms=("runtime-private-marker",),
        )

    failure_text = str(exc_info.value)
    assert "runtime-private-marker" not in failure_text
    assert "1 prohibited term" in failure_text


def test_runtime_private_terms_are_read_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        verifier.EXTRA_PROHIBITED_TERMS_ENV,
        " first-private-marker \n\nsecond-private-marker\n",
    )

    assert verifier.runtime_extra_prohibited_terms() == (
        "first-private-marker",
        "second-private-marker",
    )


def test_plan_verifier_example_redacts_matches_and_states_scan_scope() -> None:
    plan_text = IMPLEMENTATION_PLAN.read_text(encoding="utf-8")

    assert "assert term not in scan_text, term" not in plan_text
    assert 'f"{len(matches)} prohibited term(s)"' in plan_text
    assert "for path in (RENDERER, MANIFEST)" in plan_text
    assert "source/manifest/metadata only; pixel OCR is a separate audit" in plan_text


def test_tracked_files_do_not_commit_gmail_literals() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    offenders = []
    gmail_suffix = b"@" + b"gmail.com"
    for relative_path in tracked:
        if not relative_path:
            continue
        contents = (REPO_ROOT / relative_path.decode()).read_bytes().lower()
        if gmail_suffix in contents:
            offenders.append(relative_path.decode())

    assert offenders == []
