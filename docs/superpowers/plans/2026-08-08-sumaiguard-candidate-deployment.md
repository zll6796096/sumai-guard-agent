# SumaiGuard Candidate-Only Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push the audited source, make Cloud Build create verifiable zero-traffic Cloud Run candidates, and require a separate drift-safe command before any production traffic changes.

**Architecture:** GitHub CI validates the exact source commit. Cloud Build tests, builds immutable images, deploys tagged agent and web candidates with 0% traffic, probes only safe endpoints, and emits sanitized candidate evidence. A separate promotion script verifies commit, digest, revision, configuration, production predecessors, deployment ownership, and Cloud Run resource versions before moving agent and web traffic. The script rolls back only while the same release still owns the deployment lock.

**Tech Stack:** Git, GitHub Actions, Python 3.12, Bash, Docker, Google Cloud Build, Artifact Registry, Cloud Run, Secret Manager, Firebase App Check.

---

## Scope and fixed decisions

- The implementation source branch is `main`; do not create a second release branch.
- Push the exact local commit and require GitHub CI success for the same SHA.
- Cloud Build is candidate-only and must never invoke `update-traffic` or replace a service with production traffic.
- The agent candidate uses `APP_CHECK_REQUIRED=true`, a validated Firebase app ID, strict Gemini mode, and Secret Manager.
- The public web candidate uses `PUBLIC_WEB_ANALYSIS_ENABLED=false`; local mock mode remains enabled.
- Candidate probes never upload a real home photo. They use operational endpoints and a deliberately unauthenticated empty analysis request.
- Production promotion remains blocked until Plan 2 records a successful real-device App Attest request against the exact candidate URL.
- Do not read, modify, stage, or delete `docs/preconsultation/`.
- Do not reset, stash, clean, or use `git add .`.

## Acceptance evidence

- `origin/main` contains the intended SHA and GitHub CI is green for that SHA.
- Candidate deployment changes neither service's 100% production revision.
- `candidate-evidence.json` binds build ID, commit, image digests, candidate revisions, tagged URLs, service accounts, configuration fingerprints, production predecessors, and resource versions.
- The agent candidate exposes `/health` and `/ready`, rejects missing App Check before body intake, and does not expose provider or credential details.
- The web candidate exposes `/`, `/ready`, `/privacy`, and `/support`, with public analysis disabled.
- Promotion rejects source drift, digest drift, foreign revisions, changed service resource versions, missing attested-device evidence, and changed deployment locks.
- A successful promotion leaves one intended 100% agent revision and one intended 100% web revision and produces rollback evidence.
- All repository tests and release-contract checks pass.

## Task 1: Push the exact audited source and gate on GitHub CI

**Files:**

- Verify only: entire tracked worktree
- Preserve: `docs/preconsultation/`

- [ ] **Step 1: Capture the local identity and cleanliness boundary**

Run:

```bash
git status --short --branch
git rev-parse HEAD
git diff --check
git ls-files --error-unmatch docs/preconsultation 2>/dev/null && exit 1 || true
```

Expected: `main` is ahead of `origin/main`; no tracked modification is present; `docs/preconsultation/` remains untracked; `git diff --check` is silent.

- [ ] **Step 2: Run the current full local gate before network mutation**

Run:

```bash
PATH="/Users/zhanglonglong/Projects/apps/.venv/bin:$PATH" ./scripts/test_all.sh
python scripts/test_cloudbuild_config.py
```

Expected: the full Python suite, frontend import, Compose validation, and Cloud Build contract pass with zero failures.

- [ ] **Step 3: Push only the current `main` tip**

Run:

```bash
release_sha="$(git rev-parse HEAD)"
git push origin "${release_sha}:refs/heads/main"
git ls-remote origin refs/heads/main
```

Expected: the remote SHA equals `release_sha`. A successful push is source synchronization only, not deployment authorization.

- [ ] **Step 4: Require CI success for the exact pushed SHA**

Run:

```bash
release_sha="$(git rev-parse HEAD)"
gh run list --workflow CI --commit "$release_sha" --limit 1 --json databaseId,headSha,status,conclusion,url
gh run watch "$(gh run list --workflow CI --commit "$release_sha" --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
```

Expected: `headSha` exactly equals `release_sha`, and conclusion is `success`. Stop if no exact-SHA run exists.

## Task 2: Turn the Cloud Build contract RED for candidate-only behavior

**Files:**

- Modify: `scripts/test_cloudbuild_config.py`
- Test: `scripts/test_cloudbuild_config.py`

- [ ] **Step 1: Replace promotion assumptions with candidate-only assertions**

Add structured step extraction and explicit negative checks:

```python
import yaml

config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
steps = {step["id"]: step for step in config["steps"]}
all_text = config_path.read_text(encoding="utf-8")

assert "promote" not in steps
assert "update-traffic" not in all_text
assert "--to-revisions" not in all_text
assert "deploy-agent-candidate" in steps
assert "deploy-web-candidate" in steps
assert "write-candidate-evidence" in steps
assert "APP_CHECK_REQUIRED=true" in all_text
assert "FIREBASE_APP_ID=${_FIREBASE_APP_ID}" in all_text
assert "PUBLIC_WEB_ANALYSIS_ENABLED=false" in all_text
assert "/health" in all_text
assert "/privacy" in all_text
assert "/support" in all_text
assert "X-Firebase-AppCheck" in all_text
```

Add `PyYAML==6.0.2` to the test installation command in `cloudbuild.yaml`, not to either runtime requirements file.

- [ ] **Step 2: Assert evidence completeness without secret data**

Add:

```python
for key in (
    "source_commit",
    "build_id",
    "agent_digest",
    "agent_revision",
    "agent_url",
    "agent_service_account",
    "agent_resource_version_before",
    "agent_resource_version_after",
    "agent_production_before",
    "web_digest",
    "web_revision",
    "web_url",
    "web_service_account",
    "web_resource_version_before",
    "web_resource_version_after",
    "web_production_before",
):
    assert key in all_text, key

for forbidden in ("GEMINI_API_KEY_VALUE", "firebase_token", "app_check_token"):
    assert forbidden not in all_text
```

- [ ] **Step 3: Run the contract and observe RED**

Run:

```bash
python scripts/test_cloudbuild_config.py
```

Expected: failure because the current config still contains `id: promote` and `update-traffic`.

- [ ] **Step 4: Commit the failing contract**

Run:

```bash
git add scripts/test_cloudbuild_config.py
git commit -m "test: require candidate-only Cloud Build"
```

## Task 3: Make Cloud Build candidate-only and emit sanitized evidence

**Files:**

- Modify: `cloudbuild.yaml`
- Modify: `scripts/test_cloudbuild_config.py`

- [ ] **Step 1: Add explicit release substitutions and fail-closed validation**

Extend substitutions:

```yaml
substitutions:
  _REGION: asia-northeast1
  _AR_REPO: apps
  _AGENT_SERVICE: sumai-agent
  _WEB_SERVICE: sumai-web
  _FIREBASE_APP_ID: ''
  _AGENT_SERVICE_ACCOUNT: ''
  _WEB_SERVICE_ACCOUNT: ''
```

At the start of candidate deployment, validate non-empty values and Firebase app ID shape:

```bash
test -n "${_AGENT_SERVICE_ACCOUNT}"
test -n "${_WEB_SERVICE_ACCOUNT}"
printf '%s' "${_FIREBASE_APP_ID}" | grep -Eq '^1:[0-9]+:ios:[0-9a-f]+$'
```

Do not put concrete account emails, project IDs, tokens, or Firebase IDs in the repository.

- [ ] **Step 2: Bind the agent candidate to production-safe configuration**

The `gcloud run deploy` call must retain `--no-traffic` and add:

```bash
--service-account="${_AGENT_SERVICE_ACCOUNT}" \
--update-env-vars="MOCK_MODE=false,REQUIRE_REAL_GEMINI=true,APP_CHECK_REQUIRED=true,FIREBASE_APP_ID=${_FIREBASE_APP_ID},GEMINI_MODEL=gemini-2.5-flash,LOG_LEVEL=INFO" \
--update-secrets=GEMINI_API_KEY=sumai-gemini-api-key:2
```

Read back the revision template and assert the service account, image digest, source label, deployment lock, App Check requirement, expected Firebase ID, strict Gemini settings, and Secret Manager reference.

- [ ] **Step 3: Bind the web candidate to disabled public analysis**

The web candidate must retain `--no-traffic` and use:

```bash
--service-account="${_WEB_SERVICE_ACCOUNT}" \
--update-env-vars="SUMAI_AGENT_URL=${agent_url},SUMAI_WEB_PORT=8080,MOCK_MODE=false,REQUIRE_REAL_GEMINI=true,PUBLIC_WEB_ANALYSIS_ENABLED=false,LOG_LEVEL=INFO"
```

Read back the web revision and assert the service account, immutable digest, `PUBLIC_WEB_ANALYSIS_ENABLED=false`, source commit, and deployment lock.

- [ ] **Step 4: Replace real-Gemini candidate upload with privacy-safe probes**

Remove `scripts/smoke_real_gemini.py` from Cloud Build. Probe the agent candidate:

```bash
curl -fsS --retry 8 --retry-all-errors --retry-delay 5 "$agent_url/health" > /workspace/agent-health.json
curl -fsS --retry 8 --retry-all-errors --retry-delay 5 "$agent_url/ready" > /workspace/agent-ready.json
status="$(curl -sS -o /workspace/agent-rejection.json -w '%{http_code}' \
  -X POST -F 'room_hint=auto' "$agent_url/api/v1/analyze")"
test "$status" = 401
python3 - <<'PY'
import json
from pathlib import Path

health = json.loads(Path('/workspace/agent-health.json').read_text())
rejection = json.loads(Path('/workspace/agent-rejection.json').read_text())
assert health['status'] == 'ok'
assert rejection['error']['code'] == 'APP_CHECK_INVALID'
PY
```

Probe web `/`, `/ready`, `/privacy`, and `/support`; assert 200 and `Cache-Control: no-store` for the public policy pages.

- [ ] **Step 5: Delete the entire `promote` step**

Remove `id: promote` and every production `update-traffic` command from `cloudbuild.yaml`. Candidate failure may remove candidate tags, but must not touch production revision percentages.

- [ ] **Step 6: Write a sanitized candidate evidence artifact**

Add a final `write-candidate-evidence` step using Python JSON serialization rather than sourcing untrusted text:

```python
evidence = {
    "schema_version": 1,
    "source_commit": os.environ["COMMIT_SHA"],
    "build_id": os.environ["BUILD_ID"],
    "project_id": os.environ["PROJECT_ID"],
    "region": os.environ["REGION"],
    "agent_digest": values["agent_digest"],
    "agent_revision": values["agent_revision"],
    "agent_url": values["agent_url"],
    "agent_service_account": values["agent_service_account"],
    "agent_resource_version_before": values["agent_resource_version_before"],
    "agent_resource_version_after": values["agent_resource_version_after"],
    "agent_production_before": values["agent_production_before"],
    "web_digest": values["web_digest"],
    "web_revision": values["web_revision"],
    "web_url": values["web_url"],
    "web_service_account": values["web_service_account"],
    "web_resource_version_before": values["web_resource_version_before"],
    "web_resource_version_after": values["web_resource_version_after"],
    "web_production_before": values["web_production_before"],
    "production_traffic_changed": False,
}
```

Store the artifact in the build's configured evidence bucket at `gs://$PROJECT_ID-sumai-release-evidence/candidates/$COMMIT_SHA/$BUILD_ID.json`. The bucket must use uniform access and a lifecycle/retention policy approved during the read-only cloud audit. The file must contain no token, image, report, provider output, secret name version value, or home content.

- [ ] **Step 7: Run GREEN checks**

Run:

```bash
python scripts/test_cloudbuild_config.py
git diff --check
```

Expected: both pass; `rg -n 'update-traffic|--to-revisions|id: promote' cloudbuild.yaml` returns no matches.

- [ ] **Step 8: Commit the candidate-only build**

Run:

```bash
git add cloudbuild.yaml scripts/test_cloudbuild_config.py
git commit -m "feat: make Cloud Build candidate only"
```

## Task 4: Add a drift-safe promotion command with unit tests

**Files:**

- Create: `scripts/promote-verified-candidate.sh`
- Create: `scripts/test_promote_verified_candidate.py`
- Modify: `scripts/test_all.sh`

- [ ] **Step 1: Write RED source-contract tests**

Test the script text and a fake `gcloud` executable. Cover nine named cases: missing attested-device evidence, source commit different from `origin/main`, agent digest drift, web digest drift, resource-version drift, changed production predecessor, agent-before-web ordering, rollback with a changed deployment lock, and dry-run traffic immutability. Each test launches the script with the fake CLI, asserts the exact nonzero/zero exit status, and checks the recorded command list for forbidden mutation.

The fake CLI records invocations in a temporary directory and returns fixed JSON fixtures. No test accesses Google Cloud.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest scripts/test_promote_verified_candidate.py -v
```

Expected: failure because the promotion script does not exist.

- [ ] **Step 3: Implement strict inputs and dry-run default**

The script must require:

```bash
: "${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
: "${SUMAI_CANDIDATE_EVIDENCE:?Set SUMAI_CANDIDATE_EVIDENCE}"
: "${SUMAI_DEVICE_EVIDENCE:?Set SUMAI_DEVICE_EVIDENCE}"
region="${SUMAI_REGION:-asia-northeast1}"
apply="${SUMAI_PROMOTE_APPLY:-false}"
```

Default behavior is read-only validation. Mutation requires `SUMAI_PROMOTE_APPLY=true` and a second exact confirmation value:

```bash
test "${SUMAI_PROMOTE_CONFIRM:-}" = "PROMOTE_VERIFIED_SUMAI_CANDIDATE"
```

The device evidence JSON must contain the same candidate `source_commit`, `agent_revision`, and `agent_url`, plus `app_attest_provider: AppAttestProvider`, `http_status: 200`, a UTC observation time, and a SHA-256 hash of the sanitized sample fixture. It must never contain a token, request body, response images, or report text.

- [ ] **Step 4: Verify identity before mutation**

Use `gcloud run services describe --format=json`, `gcloud artifacts docker images describe`, `git ls-remote origin refs/heads/main`, and candidate evidence to assert:

- remote `main` equals the candidate source commit;
- each revision image equals the recorded immutable digest;
- revision labels contain the same source commit and deployment lock;
- current 100% revisions equal the recorded predecessors;
- service `metadata.resourceVersion` values equal the recorded post-candidate values, while the recorded pre-deploy values remain rollback/audit evidence;
- service accounts and required environment/secret references match;
- candidate tags still resolve to the recorded revisions.

- [ ] **Step 5: Promote with conditional replacement and ownership-aware rollback**

Follow the repository's LifeSnap release pattern: fetch each service JSON, create a temporary replacement document carrying the observed `metadata.resourceVersion`, set the intended revision to 100%, and call:

```bash
gcloud run services replace "$agent_payload" --project "$GOOGLE_CLOUD_PROJECT" --region "$region"
```

After agent promotion, create a new web revision pointing to the stable agent URL, probe it at 0%, then conditionally replace web traffic. If a later step fails, roll back only if both current `deployment-lock` labels still equal the candidate source commit. Always save the prior revisions and rollback commands to sanitized evidence.

- [ ] **Step 6: Add the tests to the full gate and run GREEN**

Add this line after backend tests in `scripts/test_all.sh`:

```bash
python3 -m pytest scripts/test_promote_verified_candidate.py -v
```

Run:

```bash
bash -n scripts/promote-verified-candidate.sh
python -m pytest scripts/test_promote_verified_candidate.py -v
PATH="/Users/zhanglonglong/Projects/apps/.venv/bin:$PATH" ./scripts/test_all.sh
```

Expected: all pass without network access.

- [ ] **Step 7: Commit the promotion gate**

Run:

```bash
git add scripts/promote-verified-candidate.sh scripts/test_promote_verified_candidate.py scripts/test_all.sh
git commit -m "feat: add verified candidate promotion gate"
```

## Task 5: Retire alternate deployment paths

**Files:**

- Modify: `.github/workflows/deploy-cloudrun.yml`
- Modify: `scripts/deploy_all_cloudrun.sh`
- Modify: `scripts/deploy_sumai_agent.sh`
- Modify: `scripts/deploy_sumai_web.sh`
- Create: `scripts/test_deployment_entrypoints.py`
- Modify: `scripts/test_all.sh`

- [ ] **Step 1: Write RED tests for a single release implementation**

Assert:

```python
for path in legacy_scripts:
    text = path.read_text(encoding="utf-8")
    assert "gcloud run deploy" not in text
    assert "GEMINI_API_KEY" not in text
    assert "cloudbuild.yaml" in text

workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
workflow_text = workflow_path.read_text(encoding="utf-8")
assert "gcloud run deploy" not in workflow_text
assert "GEMINI_API_KEY" not in workflow_text
assert "gcloud builds submit" in workflow_text
assert "_FIREBASE_APP_ID" in workflow_text
```

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest scripts/test_deployment_entrypoints.py -v
```

Expected: failure because the workflow and scripts still perform source deploys.

- [ ] **Step 3: Make all entry points invoke the candidate contract only**

The shell scripts validate `GOOGLE_CLOUD_PROJECT`, `SUMAI_FIREBASE_APP_ID`, `SUMAI_AGENT_SERVICE_ACCOUNT`, and `SUMAI_WEB_SERVICE_ACCOUNT`, then call `gcloud builds submit --config cloudbuild.yaml` with those substitutions. They print that production traffic remains unchanged and point to `scripts/promote-verified-candidate.sh` as a separate gated command.

The GitHub workflow uses Workload Identity Federation only, accepts no credential JSON or Gemini key, checks out the requested immutable SHA, and submits the same `cloudbuild.yaml`. It never promotes traffic.

- [ ] **Step 4: Run GREEN and commit**

Run:

```bash
python -m pytest scripts/test_deployment_entrypoints.py -v
bash -n scripts/deploy_all_cloudrun.sh scripts/deploy_sumai_agent.sh scripts/deploy_sumai_web.sh
```

Then:

```bash
git add .github/workflows/deploy-cloudrun.yml scripts/deploy_all_cloudrun.sh scripts/deploy_sumai_agent.sh scripts/deploy_sumai_web.sh scripts/test_deployment_entrypoints.py scripts/test_all.sh
git commit -m "chore: retire direct Cloud Run deploy paths"
```

## Task 6: Make Cloud Run inspection safe and document the release boundary

**Files:**

- Modify: `scripts/check_cloudrun.sh`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/cloudrun_deployment.md`
- Create: `docs/release/sumaiguard-v1.0-app-store-release-gate.md`
- Modify: `apps/sumai_agent/tests/test_documentation_contract.py`

- [ ] **Step 1: Add RED documentation and script tests**

Require the docs to state `candidate-only`, `0% traffic`, `App Check`, `PUBLIC_WEB_ANALYSIS_ENABLED=false`, the process-local semantic memo boundary, and the separate promotion checkpoint. Require `check_cloudrun.sh` to probe `/health`, `/ready`, `/privacy`, and `/support`, and forbid `/status`, `/healthz`, or an image upload.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest apps/sumai_agent/tests/test_documentation_contract.py -v
```

Expected: failure on the new release-boundary assertions.

- [ ] **Step 3: Implement read-only inspection and truthful docs**

`scripts/check_cloudrun.sh` must require explicit service names/project/region, read current traffic and service accounts, and probe safe endpoints only. It must not print environment values, secret references, tokens, or upload a photo.

Create the release gate with these evidence states, each initially `NOT STARTED`:

```markdown
| Gate | State | Exact evidence |
|---|---|---|
| Source pushed | NOT STARTED | Exact remote SHA |
| GitHub CI | NOT STARTED | Exact-SHA run URL |
| Candidate deploy | NOT STARTED | Build ID and evidence URI |
| Real-device App Attest | NOT STARTED | Sanitized evidence hash |
| Production promotion | NOT STARTED | Revisions and rollback evidence |
| Archive / Export / Upload | NOT STARTED | Independent Apple evidence |
| App Review / Approval | NOT STARTED | Exact App Store Connect state |
| Manual release / Storefront | NOT STARTED | Direct Japan URL and observation |
```

Do not place project IDs, account emails, signed URLs, build tokens, or private Apple data in tracked documentation.

- [ ] **Step 4: Run GREEN and commit**

Run:

```bash
bash -n scripts/check_cloudrun.sh
python -m pytest apps/sumai_agent/tests/test_documentation_contract.py -v
```

Then stage only named files and commit:

```bash
git add scripts/check_cloudrun.sh README.md docs/architecture.md docs/cloudrun_deployment.md docs/release/sumaiguard-v1.0-app-store-release-gate.md apps/sumai_agent/tests/test_documentation_contract.py
git commit -m "docs: define candidate release evidence"
```

## Task 7: Run the complete local and GitHub gate

**Files:**

- Modify if needed: `.github/workflows/ci.yml`

- [ ] **Step 1: Add release contract checks to CI**

After the existing backend tests, run:

```yaml
- name: Validate release contracts
  run: |
    python scripts/test_cloudbuild_config.py
    python -m pytest scripts/test_promote_verified_candidate.py scripts/test_deployment_entrypoints.py -v
    bash -n scripts/promote-verified-candidate.sh scripts/check_cloudrun.sh
```

- [ ] **Step 2: Run all local gates**

Run:

```bash
PATH="/Users/zhanglonglong/Projects/apps/.venv/bin:$PATH" ./scripts/test_all.sh
python scripts/test_cloudbuild_config.py
bash -n scripts/promote-verified-candidate.sh scripts/check_cloudrun.sh
docker build -t sumai-agent:release-check apps/sumai_agent
docker build -t sumai-web:release-check apps/sumai_web
git diff --check
git status --short --branch
```

Expected: zero failures; only explicitly named implementation files are changed; `docs/preconsultation/` remains untracked and untouched.

- [ ] **Step 3: Commit CI wiring, push exact SHA, and wait**

Run:

```bash
git add .github/workflows/ci.yml
git commit -m "ci: verify release control contracts"
release_sha="$(git rev-parse HEAD)"
git push origin "${release_sha}:refs/heads/main"
gh run watch "$(gh run list --workflow CI --commit "$release_sha" --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
```

Expected: exact-SHA CI is green before Task 8.

## Task 8: Perform the read-only cloud audit and candidate deployment

**Files:**

- Update with sanitized evidence only: `docs/release/sumaiguard-v1.0-app-store-release-gate.md`

- [ ] **Step 1: Authenticate without storing credentials in the repository**

Run:

```bash
gcloud auth list
gcloud config get-value project
```

If no active account is present, stop and have the authorized operator run `gcloud auth login` in the local terminal. Do not copy access tokens or service-account keys into chat, files, shell history, or GitHub secrets.

- [ ] **Step 2: Audit production state read-only**

Capture sanitized evidence for both services:

```bash
gcloud run services describe sumai-agent --region asia-northeast1 --format=json > /tmp/sumai-agent-service.json
gcloud run services describe sumai-web --region asia-northeast1 --format=json > /tmp/sumai-web-service.json
gcloud logging buckets describe _Default --location=global --format=json > /tmp/sumai-logging-retention.json
gcloud secrets describe sumai-gemini-api-key --format='value(name,replication)'
```

Verify IAM, service accounts, unauthenticated invocation policy, traffic, resource versions, logging retention, Artifact Registry, evidence bucket policy, and current endpoints. Never print environment values or secret payloads.

- [ ] **Step 3: Submit the exact-SHA candidate build**

Run from a clean worktree at the exact remote `main` SHA:

```bash
GOOGLE_CLOUD_PROJECT="$(gcloud config get-value project)" \
SUMAI_FIREBASE_APP_ID="$SUMAI_FIREBASE_APP_ID" \
SUMAI_AGENT_SERVICE_ACCOUNT="$SUMAI_AGENT_SERVICE_ACCOUNT" \
SUMAI_WEB_SERVICE_ACCOUNT="$SUMAI_WEB_SERVICE_ACCOUNT" \
./scripts/deploy_all_cloudrun.sh
```

Expected: build succeeds and prints a candidate evidence URI. Do not run the promotion script.

- [ ] **Step 4: Prove production traffic did not change**

Compare the post-build 100% revisions and resource versions against the pre-build evidence. Candidate tags may exist; production revisions must be unchanged.

- [ ] **Step 5: Record the candidate gate and stop**

Update only sanitized gate fields: exact SHA, CI URL, Cloud Build ID, evidence URI, candidate revision names, and `Production traffic changed: false`. Commit and push that documentation change only after verifying it contains no secrets or signed URLs.

Plan 1 ends here. Production promotion is explicitly blocked until Plan 2 completes the real-device App Attest candidate test and the user confirms the separate production-promotion checkpoint.

## Final verification and handoff

Run:

```bash
git diff --check
git status --short --branch
git log --oneline --decorate -8
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

Report exact results for source push, CI, candidate build, candidate endpoints, production traffic unchanged, cloud audit, skipped promotion, remaining App Attest dependency, and the protected untracked directory.
