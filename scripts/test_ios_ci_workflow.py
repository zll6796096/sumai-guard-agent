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
    assert "SumaiGuardDeviceSmoke" in commands
    assert "build-for-testing" in commands
    assert "validate_ios_build_settings.py" in commands
    linux_commands = "\n".join(
        step.get("run", "")
        for step in workflow["jobs"]["test"]["steps"]
        if isinstance(step, dict)
    )
    assert "scripts/test_validate_ios_signing.py" in linux_commands


def test_device_smoke_uses_release_like_testable_configuration() -> None:
    project = yaml.safe_load(
        (ROOT / "ios" / "project.yml").read_text(encoding="utf-8")
    )

    assert project["configs"]["DeviceSmoke"] == "release"
    app_target = project["targets"]["SumaiGuard"]
    assert (
        app_target["configFiles"]["DeviceSmoke"]
        == "SumaiGuard/Config/Release.xcconfig"
    )
    assert (
        app_target["settings"]["configs"]["DeviceSmoke"][
            "ENABLE_TESTABILITY"
        ]
        == "YES"
    )
    assert (
        project["schemes"]["SumaiGuardDeviceSmoke"]["test"]["config"]
        == "DeviceSmoke"
    )


def test_app_store_plan_enforces_signed_archive_and_exported_app_validation() -> None:
    plan = (
        ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-08-08-sumaiguard-app-store-release.md"
    ).read_text(encoding="utf-8")

    assert plan.count("scripts/validate_ios_signed_app.py") >= 2
    assert '--archive "$release_tmp/SumaiGuard.xcarchive"' in plan
    assert '--app "$exported_app"' in plan
