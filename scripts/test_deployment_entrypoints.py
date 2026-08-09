from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-cloudrun.yml"
ALL_SCRIPT = ROOT / "scripts" / "deploy_all_cloudrun.sh"
AGENT_SCRIPT = ROOT / "scripts" / "deploy_sumai_agent.sh"
WEB_SCRIPT = ROOT / "scripts" / "deploy_sumai_web.sh"
TEST_ALL = ROOT / "scripts" / "test_all.sh"
LEGACY_ENTRYPOINTS = (ALL_SCRIPT, AGENT_SCRIPT, WEB_SCRIPT)

PROJECT = "sumai-prod-123"
FIREBASE_APP_ID = "1:123456789:ios:abcdef0123456789"
AGENT_ACCOUNT = "sumai-agent-runtime@sumai-prod-123.iam.gserviceaccount.com"
WEB_ACCOUNT = "sumai-web-runtime@sumai-prod-123.iam.gserviceaccount.com"
AGENT_PREDECESSOR_ACCOUNT = "123456789-compute@developer.gserviceaccount.com"
WEB_PREDECESSOR_ACCOUNT = "123456789-compute@developer.gserviceaccount.com"
MIGRATION_CONFIRMATION = "MIGRATE_TO_DEDICATED_RUNTIME_SAS"
REGION = "asia-northeast1"
AR_REPO = "sumai-images"
AGENT_SERVICE = "sumai-agent"
WEB_SERVICE = "sumai-web"


def run(
    *args: str,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=check,
        text=True,
        capture_output=True,
    )


def git(*args: str, cwd: Path) -> str:
    return run("git", *args, cwd=cwd).stdout.strip()


def required_env() -> dict[str, str]:
    return {
        "GOOGLE_CLOUD_PROJECT": PROJECT,
        "SUMAI_FIREBASE_APP_ID": FIREBASE_APP_ID,
        "SUMAI_AGENT_SERVICE_ACCOUNT": AGENT_ACCOUNT,
        "SUMAI_WEB_SERVICE_ACCOUNT": WEB_ACCOUNT,
        "SUMAI_EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT": (
            AGENT_PREDECESSOR_ACCOUNT
        ),
        "SUMAI_EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT": (
            WEB_PREDECESSOR_ACCOUNT
        ),
        "SUMAI_SERVICE_ACCOUNT_MIGRATION_CONFIRM": MIGRATION_CONFIRMATION,
        "SUMAI_REGION": REGION,
        "SUMAI_AR_REPO": AR_REPO,
        "SUMAI_AGENT_SERVICE": AGENT_SERVICE,
        "SUMAI_WEB_SERVICE": WEB_SERVICE,
    }


FAKE_GCLOUD = r'''#!/usr/bin/env python3
import hashlib
import json
import os
import stat
import sys
import tarfile
from pathlib import Path

state = Path(os.environ["FAKE_GCLOUD_STATE"])
args = sys.argv[1:]
(state / "calls.json").write_text(json.dumps(args), encoding="utf-8")
if args[:2] != ["builds", "submit"] or len(args) < 3:
    raise SystemExit("only candidate Cloud Build submission is allowed")

archive = Path(args[2])
config_arg = next((arg for arg in args if arg.startswith("--config=")), None)
if config_arg is None:
    raise SystemExit("immutable Cloud Build config is required")
config = Path(config_arg.removeprefix("--config="))
if os.environ.get("FAKE_MUTATE_LIVE_CONFIG") == "1":
    (Path(os.environ["FAKE_REPO"]) / "cloudbuild.yaml").write_text(
        "steps:\n  - id: mutable-worktree-config\n",
        encoding="utf-8",
    )
with tarfile.open(archive) as handle:
    members = sorted(member.name for member in handle.getmembers())
record = {
    "archive": str(archive),
    "archive_mode": stat.S_IMODE(archive.stat().st_mode),
    "archive_exists_during_submit": archive.is_file(),
    "members": members,
    "config": str(config),
    "config_mode": stat.S_IMODE(config.stat().st_mode),
    "config_exists_during_submit": config.is_file(),
    "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
    "temp_dir_mode": stat.S_IMODE(config.parent.stat().st_mode),
}
(state / "archive.json").write_text(json.dumps(record), encoding="utf-8")
print("build-candidate-123")
'''


def make_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    remote = tmp_path / "origin.git"
    fake_bin = tmp_path / "fake-bin"
    repo.mkdir()
    fake_bin.mkdir()

    git("init", "--bare", str(remote), cwd=tmp_path)
    git("init", "-b", "main", cwd=repo)
    git("config", "user.name", "Deployment Test", cwd=repo)
    git("config", "user.email", "deployment-test@example.invalid", cwd=repo)

    (repo / "scripts").mkdir()
    script = repo / "scripts" / "deploy_all_cloudrun.sh"
    script.write_text(ALL_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(0o755)
    (repo / "cloudbuild.yaml").write_text("steps: []\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    git("add", "cloudbuild.yaml", "tracked.txt", cwd=repo)
    git("commit", "-m", "fixture", cwd=repo)
    git("remote", "add", "origin", str(remote), cwd=repo)
    git("push", "-u", "origin", "main", cwd=repo)

    fake_gcloud = fake_bin / "gcloud"
    fake_gcloud.write_text(FAKE_GCLOUD, encoding="utf-8")
    fake_gcloud.chmod(0o755)
    return repo, remote, fake_bin


def run_entrypoint(
    repo: Path,
    fake_bin: Path,
    *,
    overrides: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    state = repo.parent / "fake-gcloud-state"
    state.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(required_env())
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "FAKE_GCLOUD_STATE": str(state),
            "FAKE_REPO": str(repo),
            "TMPDIR": str(repo.parent),
        }
    )
    for key, value in (overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return run(
        str(repo / "scripts" / "deploy_all_cloudrun.sh"),
        cwd=repo.parent,
        env=env,
        check=False,
    )


def fake_state(repo: Path, name: str) -> Any:
    return json.loads(
        (repo.parent / "fake-gcloud-state" / name).read_text(encoding="utf-8")
    )


def workflow_data() -> dict[str, Any]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def workflow_on(data: dict[str, Any]) -> Any:
    # PyYAML 1.1 parses the unquoted GitHub Actions key `on` as True.
    return data.get("on", data.get(True))


def test_legacy_entrypoints_are_candidate_only_cloudbuild_paths() -> None:
    forbidden = re.compile(
        r"gcloud\s+run\s+deploy\b|"
        r"gcloud\s+run\s+services\s+(?:replace|update|update-traffic)\b|"
        r"--source\s+apps/|GEMINI_API_KEY|credentials_json|GCP_SA_KEY",
        re.IGNORECASE,
    )
    for path in LEGACY_ENTRYPOINTS:
        text = path.read_text(encoding="utf-8")
        assert path.stat().st_mode & stat.S_IXUSR, path
        assert text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
        assert "cloudbuild.yaml" in text
        assert "candidate-only" in text.lower()
        assert "no production traffic" in text.lower()
        assert not forbidden.search(text), path
        assert not re.search(r"^\s*(?:eval|source)\s", text, re.MULTILINE)


def test_compatibility_wrappers_only_exec_the_paired_submitter() -> None:
    for path in (AGENT_SCRIPT, WEB_SCRIPT):
        text = path.read_text(encoding="utf-8")
        assert 'exec "$ROOT_DIR/scripts/deploy_all_cloudrun.sh"' in text
        assert "deploy only" not in text.lower()
        assert "partial" in text.lower()
        assert text.count("gcloud") == 0


def test_workflow_is_manual_keyless_candidate_only() -> None:
    data = workflow_data()
    dispatch = workflow_on(data)["workflow_dispatch"]
    assert dispatch in (None, {})
    assert data["permissions"] == {"contents": "read", "id-token": "write"}
    assert data["concurrency"]["cancel-in-progress"] is False

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "candidate-only" in text.lower()
    assert "cloudbuild.yaml" in text
    assert "_FIREBASE_APP_ID" in text
    assert "_AGENT_SERVICE_ACCOUNT" in text
    assert "_WEB_SERVICE_ACCOUNT" in text
    assert "SUMAI_EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT" in text
    assert "SUMAI_EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT" in text
    assert "SUMAI_SERVICE_ACCOUNT_MIGRATION_CONFIRM" in text
    assert "SUMAI_ALLOWED_SERVICE_ACCOUNT_DOMAIN" not in text
    assert "scripts/deploy_all_cloudrun.sh" in text
    assert "promote-verified-candidate" not in text
    assert "GEMINI_API_KEY" not in text
    assert "GCP_SA_KEY" not in text
    assert "credentials_json" not in text
    assert not re.search(
        r"gcloud\s+run\s+(?:deploy|services\s+(?:replace|update|update-traffic))",
        text,
        re.IGNORECASE,
    )


def test_workflow_uses_current_wif_actions_and_exact_main_revision() -> None:
    steps = workflow_data()["jobs"]["candidate"]["steps"]
    checkout = next(step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@"))
    auth_steps = [
        step
        for step in steps
        if str(step.get("uses", "")).startswith("google-github-actions/auth@")
    ]
    setup = next(
        step
        for step in steps
        if str(step.get("uses", "")).startswith("google-github-actions/setup-gcloud@")
    )
    run_text = "\n".join(str(step.get("run", "")) for step in steps)

    assert checkout["uses"] == "actions/checkout@v7"
    assert checkout["with"] == {"ref": "main", "fetch-depth": 0}
    assert len(auth_steps) == 1
    assert auth_steps[0]["uses"] == "google-github-actions/auth@v3"
    assert set(auth_steps[0]["with"]) == {
        "project_id",
        "workload_identity_provider",
        "service_account",
    }
    assert setup["uses"] == "google-github-actions/setup-gcloud@v3"
    assert "GITHUB_REF" in run_text and "refs/heads/main" in run_text
    assert "GITHUB_SHA" in run_text and "git rev-parse HEAD" in run_text


def test_test_all_runs_deployment_tests_after_promotion_tests() -> None:
    text = TEST_ALL.read_text(encoding="utf-8")
    promotion = "python3 -m pytest scripts/test_promote_verified_candidate.py -v"
    deployment = "python3 -m pytest scripts/test_deployment_entrypoints.py -v"
    assert promotion in text
    assert deployment in text
    assert text.index(promotion) < text.index(deployment)


def test_submitter_passes_exact_immutable_archive_config_and_substitutions(
    tmp_path: Path,
) -> None:
    repo, _remote, fake_bin = make_repo(tmp_path)
    protected = repo / "docs" / "preconsultation" / "private.txt"
    protected.parent.mkdir(parents=True)
    protected.write_text("must never be archived\n", encoding="utf-8")
    head = git("rev-parse", "HEAD", cwd=repo)
    expected_config = run(
        "git", "show", f"{head}:cloudbuild.yaml", cwd=repo
    ).stdout.encode("utf-8")

    result = run_entrypoint(
        repo,
        fake_bin,
        overrides={"FAKE_MUTATE_LIVE_CONFIG": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert "candidate-only" in result.stdout.lower()
    assert "no production traffic" in result.stdout.lower()
    assert "build-candidate-123" in result.stdout

    call = fake_state(repo, "calls.json")
    assert call[:2] == ["builds", "submit"]
    assert call[2] not in {".", str(repo)}
    assert call[2].endswith("/source.tar.gz")
    assert call[3].startswith("--config=")
    archive_path = Path(call[2])
    config_path = Path(call[3].removeprefix("--config="))
    assert config_path.name == "cloudbuild.yaml"
    assert config_path != repo / "cloudbuild.yaml"
    assert config_path.parent == archive_path.parent
    assert call[4:] == [
        f"--project={PROJECT}",
        f"--region={REGION}",
        "--substitutions="
        f"COMMIT_SHA={head},SHORT_SHA={head[:7]},"
        f"_REGION={REGION},_AR_REPO={AR_REPO},"
        f"_AGENT_SERVICE={AGENT_SERVICE},_WEB_SERVICE={WEB_SERVICE},"
        f"_FIREBASE_APP_ID={FIREBASE_APP_ID},"
        f"_AGENT_SERVICE_ACCOUNT={AGENT_ACCOUNT},"
        f"_WEB_SERVICE_ACCOUNT={WEB_ACCOUNT},"
        "_EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT="
        f"{AGENT_PREDECESSOR_ACCOUNT},"
        "_EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT="
        f"{WEB_PREDECESSOR_ACCOUNT},"
        f"_SERVICE_ACCOUNT_MIGRATION_CONFIRM={MIGRATION_CONFIRMATION}",
        "--async",
        "--format=value(id)",
    ]

    archive = fake_state(repo, "archive.json")
    assert archive["archive_mode"] == 0o600
    assert archive["archive_exists_during_submit"] is True
    assert archive["members"] == ["cloudbuild.yaml", "tracked.txt"]
    assert archive["config_mode"] == 0o600
    assert archive["config_exists_during_submit"] is True
    assert archive["temp_dir_mode"] == 0o700
    assert archive["config_sha256"] == hashlib.sha256(expected_config).hexdigest()
    assert (repo / "cloudbuild.yaml").read_text(encoding="utf-8") == (
        "steps:\n  - id: mutable-worktree-config\n"
    )
    assert not archive_path.exists()
    assert not config_path.exists()
    assert not config_path.parent.exists()


@pytest.mark.parametrize(
    "missing",
    [
        "GOOGLE_CLOUD_PROJECT",
        "SUMAI_FIREBASE_APP_ID",
        "SUMAI_AGENT_SERVICE_ACCOUNT",
        "SUMAI_WEB_SERVICE_ACCOUNT",
        "SUMAI_EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT",
        "SUMAI_EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT",
        "SUMAI_SERVICE_ACCOUNT_MIGRATION_CONFIRM",
    ],
)
def test_missing_required_environment_fails_before_gcloud(
    tmp_path: Path, missing: str
) -> None:
    repo, _remote, fake_bin = make_repo(tmp_path)
    result = run_entrypoint(repo, fake_bin, overrides={missing: None})
    assert result.returncode != 0
    assert missing in result.stderr
    assert not (repo.parent / "fake-gcloud-state" / "calls.json").exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("GOOGLE_CLOUD_PROJECT", "UPPER_project"),
        ("SUMAI_FIREBASE_APP_ID", "firebase-app-id"),
        (
            "SUMAI_AGENT_SERVICE_ACCOUNT",
            "sumai-agent-runtime@other-project.iam.gserviceaccount.com",
        ),
        (
            "SUMAI_AGENT_SERVICE_ACCOUNT",
            "other-runtime@sumai-prod-123.iam.gserviceaccount.com",
        ),
        (
            "SUMAI_EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT",
            "not-a-service-account",
        ),
        ("SUMAI_REGION", "asia-northeast1;printf-danger"),
        ("SUMAI_AR_REPO", "../images"),
        ("SUMAI_AGENT_SERVICE", "sumai_agent"),
        ("SUMAI_WEB_SERVICE", "sumai/web"),
    ],
)
def test_unsafe_configuration_fails_before_gcloud(
    tmp_path: Path, key: str, value: str
) -> None:
    repo, _remote, fake_bin = make_repo(tmp_path)
    result = run_entrypoint(repo, fake_bin, overrides={key: value})
    assert result.returncode != 0
    assert key in result.stderr
    assert not (repo.parent / "fake-gcloud-state" / "calls.json").exists()


def test_cross_project_service_account_domain_is_rejected_even_when_requested(
    tmp_path: Path,
) -> None:
    repo, _remote, fake_bin = make_repo(tmp_path)
    domain = "shared-identity.iam.gserviceaccount.com"
    result = run_entrypoint(
        repo,
        fake_bin,
        overrides={
            "SUMAI_ALLOWED_SERVICE_ACCOUNT_DOMAIN": domain,
            "SUMAI_AGENT_SERVICE_ACCOUNT": f"sumai-agent-runtime@{domain}",
            "SUMAI_WEB_SERVICE_ACCOUNT": f"sumai-web-runtime@{domain}",
        },
    )
    assert result.returncode != 0
    assert "SUMAI_AGENT_SERVICE_ACCOUNT" in result.stderr
    assert not (repo.parent / "fake-gcloud-state" / "calls.json").exists()


@pytest.mark.parametrize(
    "confirmation",
    [None, "yes", "MIGRATE_RUNTIME_SAS"],
)
def test_runtime_service_account_migration_requires_exact_confirmation(
    tmp_path: Path,
    confirmation: str | None,
) -> None:
    repo, _remote, fake_bin = make_repo(tmp_path)
    result = run_entrypoint(
        repo,
        fake_bin,
        overrides={"SUMAI_SERVICE_ACCOUNT_MIGRATION_CONFIRM": confirmation},
    )
    assert result.returncode != 0
    assert "SUMAI_SERVICE_ACCOUNT_MIGRATION_CONFIRM" in result.stderr
    assert not (repo.parent / "fake-gcloud-state" / "calls.json").exists()


def test_non_main_branch_fails_before_gcloud(tmp_path: Path) -> None:
    repo, _remote, fake_bin = make_repo(tmp_path)
    git("switch", "-c", "feature", cwd=repo)
    result = run_entrypoint(repo, fake_bin)
    assert result.returncode != 0
    assert "main" in result.stderr
    assert not (repo.parent / "fake-gcloud-state" / "calls.json").exists()


@pytest.mark.parametrize("staged", [False, True])
def test_dirty_tracked_or_index_state_fails_before_gcloud(
    tmp_path: Path, staged: bool
) -> None:
    repo, _remote, fake_bin = make_repo(tmp_path)
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    if staged:
        git("add", "tracked.txt", cwd=repo)
    result = run_entrypoint(repo, fake_bin)
    assert result.returncode != 0
    assert "clean" in result.stderr.lower()
    assert not (repo.parent / "fake-gcloud-state" / "calls.json").exists()


def test_remote_main_mismatch_fails_before_gcloud(tmp_path: Path) -> None:
    repo, _remote, fake_bin = make_repo(tmp_path)
    (repo / "tracked.txt").write_text("next commit\n", encoding="utf-8")
    git("add", "tracked.txt", cwd=repo)
    git("commit", "-m", "local only", cwd=repo)
    result = run_entrypoint(repo, fake_bin)
    assert result.returncode != 0
    assert "origin main" in result.stderr.lower()
    assert not (repo.parent / "fake-gcloud-state" / "calls.json").exists()
