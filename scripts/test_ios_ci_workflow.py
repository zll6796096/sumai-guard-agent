from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_ci_contains_fail_closed_native_ios_job() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["ios-test"]

    assert job["runs-on"] == "macos-26"
    commands = "\n".join(
        step.get("run", "")
        for step in job["steps"]
        if isinstance(step, dict)
    )
    assert "NON_PRODUCTION_CI_FIXTURE" in commands
    assert "scripts/validate_ios_release.py" in commands
    assert "--allow-invalid-api-origin-for-ci" in commands
    assert "--expected-firebase-app-id" in commands
    assert "--allow-missing-firebase-config-for-ci" not in commands
    assert "xcodebuild" in commands
    assert "CODE_SIGNING_ALLOWED=NO" in commands
