from __future__ import annotations

import json
import os
import stat
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "promote-verified-candidate.sh"
SOURCE_SHA = "a" * 40
OTHER_SHA = "b" * 40
AGENT_DIGEST = "sha256:" + "1" * 64
WEB_DIGEST = "sha256:" + "2" * 64
BUILD_ID = "build1234"
PROJECT = "sumai-prod-123"
REGION = "asia-northeast1"
AGENT_SERVICE = "sumai-agent"
WEB_SERVICE = "sumai-web"
AGENT_PREDECESSOR = "sumai-agent-00041-old"
WEB_PREDECESSOR = "sumai-web-00037-old"
AGENT_CANDIDATE = "sumai-agent-00042-can"
WEB_CANDIDATE = "sumai-web-00038-can"
AGENT_CANDIDATE_URL = "https://candidate-agent.example.run.app"
WEB_CANDIDATE_URL = "https://candidate-web.example.run.app"
AGENT_STABLE_URL = "https://sumai-agent.example.run.app"
WEB_STABLE_URL = "https://sumai-web.example.run.app"
AGENT_ACCOUNT = "sumai-agent-runtime@sumai-prod-123.iam.gserviceaccount.com"
WEB_ACCOUNT = "sumai-web-runtime@sumai-prod-123.iam.gserviceaccount.com"
CANDIDATE_TAG = "candidate-aaaaaaa-buil"
AGENT_REF = (
    f"{REGION}-docker.pkg.dev/{PROJECT}/apps/{AGENT_SERVICE}@{AGENT_DIGEST}"
)
WEB_REF = (
    f"{REGION}-docker.pkg.dev/{PROJECT}/apps/{WEB_SERVICE}@{WEB_DIGEST}"
)
AGENT_RV_BEFORE = "100"
AGENT_RV_AFTER = "101"
WEB_RV_BEFORE = "200"
WEB_RV_AFTER = "201"
FOREIGN_AGENT_REVISION = "sumai-agent-00040-foreign"
FOREIGN_WEB_REVISION = "sumai-web-00036-foreign"
FOREIGN_AGENT_TAG = "audit-agent"
FOREIGN_WEB_TAG = "audit-web"


def env_rows(values: dict[str, str]) -> list[dict[str, str]]:
    return [{"name": key, "value": value} for key, value in values.items()]


def agent_env() -> list[dict[str, Any]]:
    return env_rows(
        {
            "MOCK_MODE": "false",
            "REQUIRE_REAL_GEMINI": "true",
            "APP_CHECK_REQUIRED": "true",
            "FIREBASE_APP_ID": "1:123456789:ios:abcdef0123456789",
            "GEMINI_MODEL": "gemini-2.5-flash",
            "LOG_LEVEL": "INFO",
        }
    ) + [
        {
            "name": "GEMINI_API_KEY",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "sumai-gemini-api-key",
                    "key": "2",
                }
            },
        }
    ]


def web_env(agent_url: str = AGENT_CANDIDATE_URL) -> list[dict[str, str]]:
    return env_rows(
        {
            "SUMAI_AGENT_URL": agent_url,
            "SUMAI_WEB_PORT": "8080",
            "MOCK_MODE": "false",
            "REQUIRE_REAL_GEMINI": "true",
            "PUBLIC_WEB_ANALYSIS_ENABLED": "false",
            "LOG_LEVEL": "INFO",
        }
    )


def revision(
    name: str,
    image: str,
    service_account: str,
    env: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "apiVersion": "serving.knative.dev/v1",
        "kind": "Revision",
        "metadata": {
            "name": name,
            "labels": {
                "source-commit": SOURCE_SHA,
                "deployment-lock": SOURCE_SHA,
            },
            "annotations": {"autoscaling.knative.dev/maxScale": "20"},
        },
        "spec": {
            "serviceAccountName": service_account,
            "timeoutSeconds": 120,
            "containerConcurrency": 80,
            "containers": [
                {
                    "image": image,
                    "ports": [{"containerPort": 8080}],
                    "resources": {
                        "limits": {"cpu": "1", "memory": "1Gi"}
                    },
                    "env": env,
                }
            ],
        },
        "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "imageDigest": image,
        },
    }


def predecessor_revision(name: str, service_account: str) -> dict[str, Any]:
    return revision(
        name,
        f"{REGION}-docker.pkg.dev/{PROJECT}/apps/old@sha256:{'9' * 64}",
        service_account,
        env_rows({"MOCK_MODE": "false"}),
    )


def service(
    name: str,
    resource_version: str,
    predecessor: str,
    candidate: str,
    candidate_url: str,
    stable_url: str,
    candidate_revision: dict[str, Any],
) -> dict[str, Any]:
    template = {
        "metadata": {
            "labels": {
                "source-commit": SOURCE_SHA,
                "deployment-lock": SOURCE_SHA,
            },
            "annotations": candidate_revision["metadata"]["annotations"],
        },
        "spec": candidate_revision["spec"],
    }
    return {
        "apiVersion": "serving.knative.dev/v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": PROJECT,
            "resourceVersion": resource_version,
            "labels": {
                "app": "sumai-guard",
                "managed-by": "cloud-build",
                "source-commit": SOURCE_SHA,
                "deployment-lock": SOURCE_SHA,
            },
            "annotations": {"run.googleapis.com/ingress": "all"},
        },
        "spec": {
            "template": template,
            "traffic": [
                {"revisionName": predecessor, "percent": 100},
                {
                    "revisionName": candidate,
                    "percent": 0,
                    "tag": CANDIDATE_TAG,
                },
            ],
        },
        "status": {
            "url": stable_url,
            "conditions": [{"type": "Ready", "status": "True"}],
            "traffic": [
                {"revisionName": predecessor, "percent": 100},
                {
                    "revisionName": candidate,
                    "percent": 0,
                    "tag": CANDIDATE_TAG,
                    "url": candidate_url,
                },
            ],
        },
    }


def candidate_evidence() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_commit": SOURCE_SHA,
        "build_id": BUILD_ID,
        "project_id": PROJECT,
        "region": REGION,
        "agent_digest": AGENT_DIGEST,
        "agent_revision": AGENT_CANDIDATE,
        "agent_url": AGENT_CANDIDATE_URL,
        "agent_service_account": AGENT_ACCOUNT,
        "agent_resource_version_before": AGENT_RV_BEFORE,
        "agent_resource_version_after": AGENT_RV_AFTER,
        "agent_production_before": AGENT_PREDECESSOR,
        "web_digest": WEB_DIGEST,
        "web_revision": WEB_CANDIDATE,
        "web_url": WEB_CANDIDATE_URL,
        "web_service_account": WEB_ACCOUNT,
        "web_resource_version_before": WEB_RV_BEFORE,
        "web_resource_version_after": WEB_RV_AFTER,
        "web_production_before": WEB_PREDECESSOR,
        "production_traffic_changed": False,
    }


def device_evidence() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_commit": SOURCE_SHA,
        "agent_revision": AGENT_CANDIDATE,
        "agent_url": AGENT_CANDIDATE_URL,
        "app_attest_provider": "AppAttestProvider",
        "http_status": 200,
        "observed_at": "2026-08-09T01:02:03Z",
        "synthetic_sample_sha256": "3" * 64,
    }


FAKE_GCLOUD = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
args = sys.argv[1:]
with (state / "calls.log").open("a", encoding="utf-8") as handle:
    handle.write("gcloud " + " ".join(args) + "\n")

def service_path(name):
    return state / "services" / f"{name}.json"

def revision_path(name):
    return state / "revisions" / f"{name}.json"

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

def advance_async(name):
    pending_path = state / f"async-{name}.json"
    if not pending_path.exists():
        return
    pending = load(pending_path)
    operation = pending["operation"]
    count_path = state / f"async-{operation}-reads"
    count = int(count_path.read_text()) + 1 if count_path.exists() else 1
    count_path.write_text(str(count), encoding="utf-8")
    remaining = pending["remaining"]
    if remaining > 0:
        pending["remaining"] = remaining - 1
        save(pending_path, pending)
        return
    save(service_path(name), pending["desired"])
    pending_path.unlink()

if args[:3] == ["run", "services", "describe"]:
    advance_async(args[3])
    print(service_path(args[3]).read_text(encoding="utf-8"), end="")
elif args[:3] == ["run", "revisions", "describe"]:
    print(revision_path(args[3]).read_text(encoding="utf-8"), end="")
elif args[:4] == ["artifacts", "docker", "images", "describe"]:
    requested = args[4]
    artifacts = load(state / "artifacts.json")
    print(json.dumps(artifacts[requested]))
elif args[:2] == ["auth", "print-access-token"]:
    print(os.environ["FAKE_ACCESS_TOKEN"])
elif args[:3] == ["run", "services", "replace"]:
    # Cloud SDK 574 refreshes the service and can silently overwrite the caller's
    # resourceVersion. Keep this dangerous behavior in the fake so a production
    # regression to gcloud replace cannot receive false CAS confidence.
    payload_path = Path(args[3])
    payload = load(payload_path)
    name = payload["metadata"]["name"]
    current_path = service_path(name)
    current = load(current_path)
    payload["metadata"]["resourceVersion"] = current["metadata"]["resourceVersion"]
    current["metadata"] = payload["metadata"]
    current["spec"] = payload["spec"]
    save(current_path, current)
    (state / "old-gcloud-replace-used").write_text("unsafe refresh\n")
    print(json.dumps(current))
elif args[:2] == ["run", "deploy"]:
    (state / "old-gcloud-deploy-used").write_text("unsafe deploy\n")
    raise SystemExit("gcloud deploy is forbidden")
else:
    print("unexpected fake gcloud call: " + " ".join(args), file=sys.stderr)
    raise SystemExit(97)
'''


FAKE_GIT = r'''#!/usr/bin/env python3
import os
import sys
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
args = sys.argv[1:]
with (state / "calls.log").open("a", encoding="utf-8") as handle:
    handle.write("git " + " ".join(args) + "\n")
if args == ["ls-remote", "--exit-code", "origin", "refs/heads/main"]:
    print(os.environ["FAKE_REMOTE_SHA"] + "\trefs/heads/main")
else:
    raise SystemExit(98)
'''


FAKE_SLEEP = r'''#!/usr/bin/env python3
import os
import sys
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
with (state / "calls.log").open("a", encoding="utf-8") as handle:
    handle.write("sleep " + " ".join(sys.argv[1:]) + "\n")
if len(sys.argv) != 2 or not sys.argv[1].isdigit():
    raise SystemExit(96)
'''


FAKE_CURL = r'''#!/usr/bin/env python3
import copy
import json
import os
import stat
import sys
import time
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
args = sys.argv[1:]
url = args[-1]
with (state / "calls.log").open("a", encoding="utf-8") as handle:
    handle.write("curl " + " ".join(args) + "\n")

def option(name):
    for index, value in enumerate(args):
        if value == name and index + 1 < len(args):
            return args[index + 1]
        if value.startswith(name + "="):
            return value.partition("=")[2]
    return None

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")

def service_path(name):
    return state / "services" / f"{name}.json"

def revision_path(name):
    return state / "revisions" / f"{name}.json"

def next_rv():
    counter_path = state / "rv-counter"
    counter = int(counter_path.read_text()) + 1
    counter_path.write_text(str(counter))
    return str(counter)

def production_revision(traffic):
    matches = [row.get("revisionName") for row in traffic if row.get("percent") == 100]
    return matches[0] if len(matches) == 1 else None

def deployment_lock(value):
    return value.get("metadata", {}).get("labels", {}).get("deployment-lock")

def is_promotion_lock(value):
    return isinstance(value, str) and value.startswith("promote-") and len(value) == 40

def status_traffic(spec_traffic, service_name, previous=None):
    previous_urls = {
        (row.get("tag"), row.get("revisionName")): row.get("url")
        for row in (previous or [])
        if row.get("tag") and row.get("url")
    }
    rows = []
    for target in spec_traffic:
        row = copy.deepcopy(target)
        if target.get("tag"):
            row["url"] = previous_urls.get(
                (target.get("tag"), target.get("revisionName")),
                f"https://{target['tag']}---{service_name}.example.run.app",
            )
        rows.append(row)
    return rows

def inject_race(current_path, current, marker_name, *, steal_lock):
    marker = state / marker_name
    if marker.exists():
        return current
    marker.write_text("injected\n", encoding="utf-8")
    current["metadata"]["resourceVersion"] = next_rv()
    if steal_lock:
        current["metadata"]["labels"]["deployment-lock"] = "promote-" + "f" * 32
    save(current_path, current)
    return current

def mutate_web_foreign(*, safe):
    path = service_path("sumai-web")
    service = load(path)
    service["metadata"]["resourceVersion"] = next_rv()
    service["metadata"]["labels"]["deployment-lock"] = "foreign-web"
    revision = os.environ["FAKE_WEB_PREDECESSOR"] if safe else os.environ["FAKE_WEB_CANDIDATE"]
    traffic = []
    for existing in service["spec"]["traffic"]:
        if existing.get("tag"):
            row = copy.deepcopy(existing)
            row["percent"] = 100 if row.get("revisionName") == revision else 0
            traffic.append(row)
    if not any(row.get("percent") == 100 for row in traffic):
        traffic.insert(0, {"revisionName": revision, "percent": 100})
    service["spec"]["traffic"] = traffic
    service["status"]["traffic"] = status_traffic(
        traffic, "sumai-web", service["status"].get("traffic", [])
    )
    save(path, service)

failure = os.environ.get("FAKE_CURL_FAIL_SUBSTRING", "")
if failure and failure in url:
    if os.environ.get("FAKE_FOREIGN_LOCK_ON_FAIL") == "1":
        for name in ("sumai-agent", "sumai-web"):
            path = state / "services" / f"{name}.json"
            service = json.loads(path.read_text(encoding="utf-8"))
            service["metadata"]["labels"]["deployment-lock"] = "foreign"
            path.write_text(json.dumps(service) + "\n", encoding="utf-8")
    if os.environ.get("FAKE_FOREIGN_AGENT_LOCK_ON_FAIL") == "1":
        path = state / "services" / "sumai-agent.json"
        service = json.loads(path.read_text(encoding="utf-8"))
        service["metadata"]["labels"]["deployment-lock"] = "foreign-agent"
        path.write_text(json.dumps(service) + "\n", encoding="utf-8")
    if os.environ.get("FAKE_FOREIGN_WEB_SAFE_ON_FAIL") == "1":
        mutate_web_foreign(safe=True)
    if os.environ.get("FAKE_FOREIGN_WEB_UNSAFE_ON_FAIL") == "1":
        mutate_web_foreign(safe=False)
    print("probe failed", file=sys.stderr)
    raise SystemExit(22)

output = option("--output") or option("-o")
headers = option("--dump-header") or option("-D")
api_prefix = (
    f"https://{os.environ['FAKE_REGION']}-run.googleapis.com/"
    f"apis/serving.knative.dev/v1/namespaces/{os.environ['FAKE_PROJECT']}/services/"
)
if url.startswith(api_prefix):
    name = url.removeprefix(api_prefix)
    if name not in {"sumai-agent", "sumai-web"} or "/" in name:
        raise SystemExit("unsafe Cloud Run API URL")
    if option("--request") != "PUT":
        raise SystemExit("Cloud Run API mutation must use PUT")
    config_raw = option("--config")
    data_raw = option("--data-binary")
    if not config_raw or not data_raw or not data_raw.startswith("@") or not output:
        raise SystemExit("Cloud Run API request is incomplete")
    config = Path(config_raw)
    if stat.S_IMODE(config.stat().st_mode) != 0o600:
        raise SystemExit("unsafe auth config mode")
    expected_auth = f'header = "Authorization: Bearer {os.environ["FAKE_ACCESS_TOKEN"]}"'
    if config.read_text(encoding="utf-8").strip() != expected_auth:
        raise SystemExit("invalid API authorization")
    if stat.S_IMODE(Path(output).stat().st_mode) != 0o600:
        raise SystemExit("unsafe API response mode")
    payload = load(Path(data_raw[1:]))
    current_path = service_path(name)
    requested_lock = deployment_lock(payload)
    requested_production = production_revision(payload.get("spec", {}).get("traffic", []))
    requested_template_name = payload.get("spec", {}).get("template", {}).get("metadata", {}).get("name")
    is_claim_request = (
        is_promotion_lock(requested_lock)
        and requested_production == (
            os.environ["FAKE_AGENT_PREDECESSOR"]
            if name == "sumai-agent" else os.environ["FAKE_WEB_PREDECESSOR"]
        )
        and not requested_template_name
    )
    wait_path_raw = os.environ.get("FAKE_WAIT_BEFORE_AGENT_CLAIM", "")
    if name == "sumai-agent" and wait_path_raw and is_claim_request:
        wait_path = Path(wait_path_raw)
        wait_path.with_suffix(".ready").write_text("ready\n", encoding="utf-8")
        deadline = time.monotonic() + 30
        while not wait_path.with_suffix(".release").exists():
            if time.monotonic() >= deadline:
                raise SystemExit("timed out waiting before agent claim")
            time.sleep(0.02)
    current = load(current_path)
    is_claim = (
        is_claim_request
        and deployment_lock(current) == os.environ["FAKE_SOURCE_SHA"]
        and payload.get("spec") == current.get("spec")
    )
    is_agent_cutover = (
        name == "sumai-agent"
        and is_promotion_lock(requested_lock)
        and requested_production == os.environ["FAKE_AGENT_CANDIDATE"]
    )
    is_final_web_create = (
        name == "sumai-web"
        and is_promotion_lock(requested_lock)
        and isinstance(requested_template_name, str)
        and requested_template_name.startswith("sumai-web-final-")
        and requested_production == os.environ["FAKE_WEB_PREDECESSOR"]
        and current.get("spec", {}).get("template", {}).get("metadata", {}).get("name")
            != requested_template_name
    )
    is_web_cutover = (
        name == "sumai-web"
        and is_promotion_lock(requested_lock)
        and requested_production not in (None, os.environ["FAKE_WEB_PREDECESSOR"])
    )
    current_production = production_revision(current.get("spec", {}).get("traffic", []))
    is_agent_rollback = (
        name == "sumai-agent"
        and is_promotion_lock(requested_lock)
        and requested_production == os.environ["FAKE_AGENT_PREDECESSOR"]
        and current_production == os.environ["FAKE_AGENT_CANDIDATE"]
    )
    payload_name = Path(data_raw[1:]).name
    operation = None
    if payload_name == "agent-promotion-payload.json":
        operation = "agent-cutover"
    elif payload_name == "web-promotion-payload.json":
        operation = "web-cutover"
    elif payload_name == "rollback-web-payload.json":
        operation = "web-rollback"
    elif payload_name == "rollback-agent-payload.json":
        operation = "agent-rollback"
    if name == "sumai-web" and is_claim and os.environ.get("FAKE_RACE_WEB_CLAIM") == "1":
        current = inject_race(current_path, current, "race-web-claim", steal_lock=True)
        if os.environ.get("FAKE_STEAL_AGENT_ON_WEB_CLAIM") == "1":
            agent_path = service_path("sumai-agent")
            agent = load(agent_path)
            agent["metadata"]["resourceVersion"] = next_rv()
            agent["metadata"]["labels"]["deployment-lock"] = "promote-" + "e" * 32
            save(agent_path, agent)
    if is_agent_cutover and os.environ.get("FAKE_RACE_AGENT_CUTOVER") == "1":
        current = inject_race(current_path, current, "race-agent-cutover", steal_lock=True)
    if is_final_web_create and os.environ.get("FAKE_RACE_FINAL_WEB_CREATE") == "1":
        current = inject_race(current_path, current, "race-final-web-create", steal_lock=False)
    if is_web_cutover and os.environ.get("FAKE_RACE_WEB_CUTOVER") == "1":
        current = inject_race(current_path, current, "race-web-cutover", steal_lock=True)
    if is_web_cutover and os.environ.get("FAKE_RV_RACE_WEB_CUTOVER") == "1":
        current = inject_race(current_path, current, "rv-race-web-cutover", steal_lock=False)
    if is_agent_rollback and os.environ.get("FAKE_RACE_AGENT_ROLLBACK") == "1":
        current = inject_race(current_path, current, "race-agent-rollback", steal_lock=False)
    if payload.get("metadata", {}).get("resourceVersion") != current.get("metadata", {}).get("resourceVersion"):
        conflict_status = os.environ.get("FAKE_API_CONFLICT_STATUS", "409")
        if conflict_status not in {"409", "412"}:
            raise SystemExit("invalid fake conflict status")
        Path(output).write_text(
            json.dumps({"error": {"code": int(conflict_status), "message": "conflict"}}) + "\n"
        )
        print(conflict_status, end="")
        raise SystemExit(0)
    snapshots = state / "replace-payloads"
    snapshots.mkdir(exist_ok=True)
    number = len(list(snapshots.glob("*.json"))) + 1
    save(snapshots / f"{number:02d}-{name}.json", payload)
    previous_current = copy.deepcopy(current)
    previous_status_traffic = current.get("status", {}).get("traffic", [])
    current["metadata"] = copy.deepcopy(payload["metadata"])
    current["metadata"]["resourceVersion"] = next_rv()
    current["spec"] = copy.deepcopy(payload["spec"])
    current["status"]["conditions"] = [{"type": "Ready", "status": "True"}]
    current["status"]["traffic"] = status_traffic(
        current["spec"]["traffic"], name, previous_status_traffic
    )
    if is_final_web_create:
        template = current["spec"]["template"]
        revision = {
            "apiVersion": "serving.knative.dev/v1",
            "kind": "Revision",
            "metadata": {
                "name": requested_template_name,
                "labels": copy.deepcopy(template.get("metadata", {}).get("labels", {})),
                "annotations": copy.deepcopy(template.get("metadata", {}).get("annotations", {})),
            },
            "spec": copy.deepcopy(template["spec"]),
            "status": {
                "conditions": [{"type": "Ready", "status": "True"}],
                "imageDigest": template["spec"]["containers"][0]["image"],
            },
        }
        runtime_drift = os.environ.get("FAKE_DEPLOY_RUNTIME_DRIFT", "")
        if runtime_drift == "command":
            revision["spec"]["containers"][0].pop("command", None)
        elif runtime_drift == "args":
            revision["spec"]["containers"][0]["args"] = ["unsafe"]
        elif runtime_drift == "probe":
            revision["spec"]["containers"][0]["startupProbe"]["periodSeconds"] = 99
        elif runtime_drift == "resources":
            revision["spec"]["containers"][0]["resources"]["limits"]["memory"] = "2Gi"
        save(revision_path(requested_template_name), revision)
        current["status"]["latestCreatedRevisionName"] = requested_template_name
        (state / "final-revision.txt").write_text(requested_template_name)
    pending_path = state / f"async-{name}.json"
    pending_path.unlink(missing_ok=True)
    delay_reads = 0
    if operation is not None:
        delay_raw = os.environ.get(
            "FAKE_ASYNC_" + operation.upper().replace("-", "_") + "_READS",
            "0",
        )
        if not delay_raw.isdigit():
            raise SystemExit("invalid fake async delay")
        delay_reads = int(delay_raw)
    if delay_reads:
        intermediate = previous_current
        intermediate["metadata"] = copy.deepcopy(current["metadata"])
        save(current_path, intermediate)
        save(
            pending_path,
            {
                "operation": operation,
                "remaining": delay_reads,
                "desired": current,
            },
        )
    else:
        save(current_path, current)
    wait_after_claim_raw = os.environ.get("FAKE_WAIT_AFTER_AGENT_CLAIM", "")
    if name == "sumai-agent" and is_claim and wait_after_claim_raw:
        wait_after_claim = Path(wait_after_claim_raw)
        wait_after_claim.with_suffix(".ready").write_text("ready\n", encoding="utf-8")
        deadline = time.monotonic() + 30
        while not wait_after_claim.with_suffix(".release").exists():
            if time.monotonic() >= deadline:
                raise SystemExit("timed out waiting after agent claim")
            time.sleep(0.02)
    if (
        name == "sumai-web"
        and not is_claim
        and requested_production == os.environ["FAKE_WEB_PREDECESSOR"]
        and not is_final_web_create
        and os.environ.get("FAKE_FOREIGN_AGENT_LOCK_AFTER_WEB_ROLLBACK") == "1"
    ):
        agent_path = service_path("sumai-agent")
        agent = load(agent_path)
        agent["metadata"]["labels"]["deployment-lock"] = "foreign"
        save(agent_path, agent)
    post_promotion_drift = os.environ.get("FAKE_AGENT_POST_PROMOTION_DRIFT")
    if is_agent_cutover and post_promotion_drift == "config":
        revision_file = revision_path(os.environ["FAKE_AGENT_CANDIDATE"])
        revision_value = load(revision_file)
        revision_value["spec"]["containers"][0]["env"][0]["value"] = "true"
        save(revision_file, revision_value)
    if is_agent_cutover and post_promotion_drift == "artifact":
        artifact_file = state / "artifacts.json"
        artifacts = load(artifact_file)
        artifacts[os.environ["FAKE_AGENT_REF"]]["image_summary"]["digest"] = "sha256:" + "f" * 64
        save(artifact_file, artifacts)
    Path(output).write_text(json.dumps(current) + "\n")
    if is_final_web_create and os.environ.get("FAKE_DEPLOY_FAIL_AFTER_MUTATION") == "1":
        raise SystemExit(55)
    print("200", end="")
    raise SystemExit(0)

if output:
    path = Path(output)
    if url.endswith("/ready") or url.endswith("/health"):
        path.write_text('{"status":"ok"}\n', encoding="utf-8")
    else:
        path.write_text("<html>safe policy page</html>\n", encoding="utf-8")
if headers:
    Path(headers).write_text(
        "HTTP/2 200\r\nCache-Control: private, no-store\r\n\r\n",
        encoding="iso-8859-1",
    )
if option("--write-out") is not None or option("-w") is not None:
    print("200", end="")
'''


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.fake_bin = root / "bin"
        self.candidate_path = root / "candidate.json"
        self.device_path = root / "device.json"
        self.output_path = root / "promotion.json"
        self.candidate = candidate_evidence()
        self.device = device_evidence()
        agent_candidate = revision(
            AGENT_CANDIDATE, AGENT_REF, AGENT_ACCOUNT, agent_env()
        )
        web_candidate = revision(
            WEB_CANDIDATE, WEB_REF, WEB_ACCOUNT, web_env()
        )
        web_candidate["metadata"]["annotations"].update(
            {
                "run.googleapis.com/cpu-throttling": "true",
                "run.googleapis.com/startup-cpu-boost": "false",
            }
        )
        web_candidate["spec"]["volumes"] = [
            {"name": "runtime-data", "emptyDir": {"medium": "Memory"}}
        ]
        web_container = web_candidate["spec"]["containers"][0]
        web_container.update(
            {
                "command": ["python3"],
                "args": ["-m", "sumai_web.app"],
                "startupProbe": {
                    "httpGet": {"path": "/ready", "port": 8080},
                    "periodSeconds": 2,
                    "failureThreshold": 30,
                },
                "livenessProbe": {
                    "httpGet": {"path": "/ready", "port": 8080},
                    "periodSeconds": 10,
                },
                "volumeMounts": [
                    {"name": "runtime-data", "mountPath": "/tmp/runtime"}
                ],
            }
        )
        self.services = {
            AGENT_SERVICE: service(
                AGENT_SERVICE,
                AGENT_RV_AFTER,
                AGENT_PREDECESSOR,
                AGENT_CANDIDATE,
                AGENT_CANDIDATE_URL,
                AGENT_STABLE_URL,
                agent_candidate,
            ),
            WEB_SERVICE: service(
                WEB_SERVICE,
                WEB_RV_AFTER,
                WEB_PREDECESSOR,
                WEB_CANDIDATE,
                WEB_CANDIDATE_URL,
                WEB_STABLE_URL,
                web_candidate,
            ),
        }
        self.revisions = {
            AGENT_CANDIDATE: agent_candidate,
            WEB_CANDIDATE: web_candidate,
            AGENT_PREDECESSOR: predecessor_revision(
                AGENT_PREDECESSOR, AGENT_ACCOUNT
            ),
            WEB_PREDECESSOR: predecessor_revision(
                WEB_PREDECESSOR, WEB_ACCOUNT
            ),
        }
        self.artifacts = {
            AGENT_REF: {"image_summary": {"digest": AGENT_DIGEST}},
            WEB_REF: {"image_summary": {"digest": WEB_DIGEST}},
        }

    def write(self) -> None:
        (self.state / "services").mkdir(parents=True)
        (self.state / "revisions").mkdir()
        self.fake_bin.mkdir()
        for name, payload in self.services.items():
            self.write_json(self.state / "services" / f"{name}.json", payload)
        for name, payload in self.revisions.items():
            self.write_json(self.state / "revisions" / f"{name}.json", payload)
        self.write_json(self.state / "artifacts.json", self.artifacts)
        (self.state / "rv-counter").write_text("300", encoding="utf-8")
        self.write_evidence()
        for name, body in {
            "gcloud": FAKE_GCLOUD,
            "git": FAKE_GIT,
            "curl": FAKE_CURL,
            "sleep": FAKE_SLEEP,
        }.items():
            path = self.fake_bin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)

    def write_evidence(self) -> None:
        self.write_json(self.candidate_path, self.candidate)
        self.write_json(self.device_path, self.device)

    @staticmethod
    def write_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    def environment(
        self,
        *,
        apply: bool = False,
        confirm: str | None = None,
        extra_env: dict[str, str] | None = None,
        device_path: Path | None = None,
        output_path: Path | None = None,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{self.fake_bin}{os.pathsep}{env['PATH']}",
                "TMPDIR": str(self.root),
                "FAKE_STATE": str(self.state),
                "FAKE_SOURCE_SHA": SOURCE_SHA,
                "FAKE_PROJECT": PROJECT,
                "FAKE_REGION": REGION,
                "FAKE_ACCESS_TOKEN": "ya29.fake-promotion-token-never-log-this-value",
                "FAKE_REMOTE_SHA": SOURCE_SHA,
                "FAKE_AGENT_CANDIDATE": AGENT_CANDIDATE,
                "FAKE_AGENT_PREDECESSOR": AGENT_PREDECESSOR,
                "FAKE_AGENT_REF": AGENT_REF,
                "FAKE_WEB_CANDIDATE": WEB_CANDIDATE,
                "FAKE_WEB_PREDECESSOR": WEB_PREDECESSOR,
                "GOOGLE_CLOUD_PROJECT": PROJECT,
                "SUMAI_CANDIDATE_EVIDENCE": str(self.candidate_path),
                "SUMAI_DEVICE_EVIDENCE": str(
                    device_path if device_path is not None else self.device_path
                ),
                "SUMAI_PROMOTE_APPLY": "true" if apply else "false",
            }
        )
        if apply:
            env["SUMAI_PROMOTION_EVIDENCE"] = str(output_path or self.output_path)
        if confirm is not None:
            env["SUMAI_PROMOTE_CONFIRM"] = confirm
        if extra_env:
            env.update(extra_env)
        return env

    def run(
        self,
        *,
        apply: bool = False,
        confirm: str | None = None,
        extra_env: dict[str, str] | None = None,
        device_path: Path | None = None,
        output_path: Path | None = None,
        script_path: Path = SCRIPT,
    ) -> subprocess.CompletedProcess[str]:
        env = self.environment(
            apply=apply,
            confirm=confirm,
            extra_env=extra_env,
            device_path=device_path,
            output_path=output_path,
        )
        return subprocess.run(
            ["bash", str(script_path)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def start(
        self,
        *,
        output_path: Path,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.Popen[str]:
        env = self.environment(
            apply=True,
            confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
            extra_env=extra_env,
            output_path=output_path,
        )
        return subprocess.Popen(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def calls(self) -> list[str]:
        path = self.state / "calls.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def replacement_payloads(self) -> list[dict[str, Any]]:
        directory = self.state / "replace-payloads"
        if not directory.exists():
            return []
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        ]

    def api_put_calls(self) -> list[str]:
        return [
            call
            for call in self.calls()
            if call.startswith("curl ")
            and "-run.googleapis.com/apis/serving.knative.dev/" in call
        ]

    def current_service(self, name: str) -> dict[str, Any]:
        return json.loads(
            (self.state / "services" / f"{name}.json").read_text(
                encoding="utf-8"
            )
        )

    def async_read_count(self, operation: str) -> int:
        path = self.state / f"async-{operation}-reads"
        return int(path.read_text(encoding="utf-8")) if path.exists() else 0


@pytest.fixture
def gate(tmp_path: Path) -> Fixture:
    fixture = Fixture(tmp_path)
    fixture.write()
    return fixture


def assert_failed_without_mutation(result: subprocess.CompletedProcess[str], gate: Fixture) -> None:
    assert result.returncode != 0, result.stdout + result.stderr
    assert gate.api_put_calls() == []
    assert not any(
        call.startswith("gcloud run deploy ")
        or call.startswith("gcloud run services replace ")
        or " update-traffic " in call
        or call.startswith("gcloud storage ")
        for call in gate.calls()
    )


def assert_no_mutating_gcloud(gate: Fixture) -> None:
    assert not any(
        call.startswith("gcloud run deploy ")
        or call.startswith("gcloud run services replace ")
        or call.startswith("gcloud run services update ")
        or " update-traffic " in call
        for call in gate.calls()
    )
    assert not (gate.state / "old-gcloud-replace-used").exists()
    assert not (gate.state / "old-gcloud-deploy-used").exists()


def add_foreign_zero_tag(
    gate: Fixture,
    service_name: str,
    revision_name: str,
    tag: str,
) -> None:
    service_value = gate.services[service_name]
    service_value["spec"]["traffic"].append(
        {"revisionName": revision_name, "percent": 0, "tag": tag}
    )
    service_value["status"]["traffic"].append(
        {
            "revisionName": revision_name,
            "percent": 0,
            "tag": tag,
            "url": f"https://{tag}---{service_name}.example.run.app",
        }
    )
    gate.write_json(
        gate.state / "services" / f"{service_name}.json", service_value
    )


def service_lock(gate: Fixture, service_name: str) -> str:
    return gate.current_service(service_name)["metadata"]["labels"][
        "deployment-lock"
    ]


def traffic_by_tag(service_value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["tag"]: row
        for row in service_value["spec"]["traffic"]
        if row.get("tag")
    }


def test_missing_attested_device_evidence_fails_closed(gate: Fixture) -> None:
    result = gate.run(device_path=gate.root / "missing-device.json")
    assert_failed_without_mutation(result, gate)
    assert "device_evidence=INVALID" in result.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_commit", OTHER_SHA),
        ("agent_revision", "sumai-agent-99999-other"),
        ("agent_url", "https://other-agent.example.run.app"),
    ],
)
def test_device_evidence_must_match_candidate(
    gate: Fixture, field: str, value: str
) -> None:
    gate.device[field] = value
    gate.write_evidence()
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "evidence_binding=INVALID" in result.stderr


def test_source_must_equal_origin_main(gate: Fixture) -> None:
    result = gate.run(extra_env={"FAKE_REMOTE_SHA": OTHER_SHA})
    assert_failed_without_mutation(result, gate)
    assert "origin_main=DRIFT" in result.stderr
    assert "git ls-remote --exit-code origin refs/heads/main" in gate.calls()


@pytest.mark.parametrize(
    "override",
    [
        {"GOOGLE_CLOUD_PROJECT": "unsafe/project"},
        {"SUMAI_REGION": "asia_northeast1"},
    ],
)
def test_cloud_run_api_target_components_fail_before_any_external_call(
    gate: Fixture, override: dict[str, str]
) -> None:
    result = gate.run(extra_env=override)
    assert result.returncode != 0
    assert gate.calls() == []
    assert "cloud_run_api_target=INVALID" in result.stderr


@pytest.mark.parametrize("component", ["agent", "web"])
def test_artifact_or_revision_digest_drift_is_rejected(
    gate: Fixture, component: str
) -> None:
    revision_name = AGENT_CANDIDATE if component == "agent" else WEB_CANDIDATE
    gate.revisions[revision_name]["spec"]["containers"][0]["image"] = (
        f"{REGION}-docker.pkg.dev/{PROJECT}/apps/{component}@sha256:{'f' * 64}"
    )
    gate.write_json(
        gate.state / "revisions" / f"{revision_name}.json",
        gate.revisions[revision_name],
    )
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "candidate_state=INVALID" in result.stderr


def test_candidate_tag_or_revision_drift_is_rejected(gate: Fixture) -> None:
    gate.services[AGENT_SERVICE]["status"]["traffic"][1]["revisionName"] = (
        "sumai-agent-99999-other"
    )
    gate.write_json(
        gate.state / "services" / f"{AGENT_SERVICE}.json",
        gate.services[AGENT_SERVICE],
    )
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "candidate_state=INVALID" in result.stderr


def test_resource_version_drift_is_rejected(gate: Fixture) -> None:
    gate.services[WEB_SERVICE]["metadata"]["resourceVersion"] = "999"
    gate.write_json(
        gate.state / "services" / f"{WEB_SERVICE}.json",
        gate.services[WEB_SERVICE],
    )
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "resource_version=DRIFT" in result.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent_resource_version_before", "rv-100"),
        ("agent_resource_version_after", ""),
        ("agent_resource_version_before", AGENT_RV_AFTER),
        ("agent_resource_version_before", "102"),
        ("web_resource_version_before", WEB_RV_AFTER),
        ("web_resource_version_before", "202"),
    ],
)
def test_candidate_resource_versions_must_be_decimal_and_strictly_advance(
    gate: Fixture, field: str, value: str
) -> None:
    gate.candidate[field] = value
    gate.write_evidence()
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "candidate_evidence=INVALID" in result.stderr


def test_production_predecessor_drift_is_rejected(gate: Fixture) -> None:
    gate.services[AGENT_SERVICE]["spec"]["traffic"][0]["revisionName"] = (
        "sumai-agent-00043-foreign"
    )
    gate.services[AGENT_SERVICE]["status"]["traffic"][0]["revisionName"] = (
        "sumai-agent-00043-foreign"
    )
    gate.write_json(
        gate.state / "services" / f"{AGENT_SERVICE}.json",
        gate.services[AGENT_SERVICE],
    )
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "predecessor=DRIFT" in result.stderr


@pytest.mark.parametrize(
    "mutate",
    [
        lambda fixture: fixture.revisions[AGENT_CANDIDATE]["spec"].__setitem__(
            "serviceAccountName", "other@sumai-prod-123.iam.gserviceaccount.com"
        ),
        lambda fixture: fixture.revisions[AGENT_CANDIDATE]["spec"]["containers"][0][
            "env"
        ][0].__setitem__("value", "true"),
        lambda fixture: fixture.services[WEB_SERVICE]["metadata"]["labels"].__setitem__(
            "deployment-lock", OTHER_SHA
        ),
        lambda fixture: fixture.revisions[AGENT_CANDIDATE]["spec"]["containers"][0][
            "env"
        ][-1].__setitem__("value", "plaintext-secret"),
    ],
)
def test_service_account_config_lock_or_plaintext_secret_drift_is_rejected(
    gate: Fixture, mutate: Callable[[Fixture], None]
) -> None:
    mutate(gate)
    for name, payload in gate.services.items():
        gate.write_json(gate.state / "services" / f"{name}.json", payload)
    for name, payload in gate.revisions.items():
        gate.write_json(gate.state / "revisions" / f"{name}.json", payload)
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "candidate_state=INVALID" in result.stderr


@pytest.mark.parametrize(
    "mutate",
    [
        lambda fixture: fixture.revisions[AGENT_CANDIDATE]["spec"]["containers"][0][
            "env"
        ].append({"name": "EXTRA_SETTING", "value": "safe-looking"}),
        lambda fixture: fixture.revisions[WEB_CANDIDATE]["spec"]["containers"][0][
            "env"
        ].append(
            {
                "name": "EXTRA_SECRET",
                "valueFrom": {
                    "secretKeyRef": {"name": "unexpected", "key": "1"}
                },
            }
        ),
        lambda fixture: fixture.revisions[WEB_CANDIDATE]["spec"]["containers"][0][
            "env"
        ].pop(),
        lambda fixture: fixture.revisions[AGENT_CANDIDATE]["spec"]["containers"][0][
            "env"
        ].append({"name": "MOCK_MODE", "value": "false"}),
    ],
)
def test_candidate_environment_and_secret_sets_are_exact(
    gate: Fixture, mutate: Callable[[Fixture], None]
) -> None:
    mutate(gate)
    for name, payload in gate.services.items():
        gate.write_json(gate.state / "services" / f"{name}.json", payload)
    for name, payload in gate.revisions.items():
        gate.write_json(gate.state / "revisions" / f"{name}.json", payload)
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "candidate_state=INVALID" in result.stderr


def candidate_env_row(
    gate: Fixture, revision_name: str, env_name: str
) -> dict[str, Any]:
    rows = gate.revisions[revision_name]["spec"]["containers"][0]["env"]
    return next(row for row in rows if row.get("name") == env_name)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda gate: candidate_env_row(
            gate, WEB_CANDIDATE, "SUMAI_WEB_PORT"
        ).__setitem__("unexpected", "value"),
        lambda gate: candidate_env_row(
            gate, WEB_CANDIDATE, "SUMAI_WEB_PORT"
        ).__setitem__("value", 8080),
        lambda gate: candidate_env_row(
            gate, WEB_CANDIDATE, "SUMAI_WEB_PORT"
        ).__setitem__(
            "valueFrom", {"secretKeyRef": {"name": "mixed", "key": "1"}}
        ),
        lambda gate: candidate_env_row(
            gate, AGENT_CANDIDATE, "GEMINI_API_KEY"
        ).__setitem__("unexpected", "value"),
        lambda gate: candidate_env_row(
            gate, AGENT_CANDIDATE, "GEMINI_API_KEY"
        ).__setitem__("value", "mixed-plaintext"),
        lambda gate: candidate_env_row(
            gate, AGENT_CANDIDATE, "GEMINI_API_KEY"
        )["valueFrom"].__setitem__("unexpected", {}),
        lambda gate: candidate_env_row(
            gate, AGENT_CANDIDATE, "GEMINI_API_KEY"
        )["valueFrom"]["secretKeyRef"].__setitem__("unexpected", "value"),
        lambda gate: candidate_env_row(
            gate, AGENT_CANDIDATE, "GEMINI_API_KEY"
        )["valueFrom"]["secretKeyRef"].__setitem__("key", 2),
    ],
)
def test_candidate_env_and_secret_rows_reject_non_exact_nested_schemas(
    gate: Fixture, mutate: Callable[[Fixture], None]
) -> None:
    mutate(gate)
    for name, payload in gate.services.items():
        gate.write_json(gate.state / "services" / f"{name}.json", payload)
    for name, payload in gate.revisions.items():
        gate.write_json(gate.state / "revisions" / f"{name}.json", payload)
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "candidate_state=INVALID" in result.stderr


def test_unexpected_positive_traffic_target_is_rejected(gate: Fixture) -> None:
    for location in ("spec", "status"):
        gate.services[AGENT_SERVICE][location]["traffic"].append(
            {
                "revisionName": FOREIGN_AGENT_REVISION,
                "percent": 5,
                "tag": FOREIGN_AGENT_TAG,
            }
        )
    gate.write_json(
        gate.state / "services" / f"{AGENT_SERVICE}.json",
        gate.services[AGENT_SERVICE],
    )
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "candidate_state=INVALID" in result.stderr


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("authorization_header", "Bearer top-secret-token"),
        ("request_body", "base64 image content"),
        ("home_report", "private action content"),
    ],
)
def test_forbidden_evidence_fields_and_values_are_rejected_without_leak(
    gate: Fixture, key: str, value: str
) -> None:
    gate.device[key] = value
    gate.write_evidence()
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "sensitive_evidence=REJECTED" in result.stderr
    assert value not in result.stdout
    assert value not in result.stderr


def test_dry_run_performs_validation_and_probes_but_never_mutates(gate: Fixture) -> None:
    result = gate.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "promotion_mode=DRY_RUN" in result.stdout
    assert "proposed_agent_revision=" + AGENT_CANDIDATE in result.stdout
    assert "proposed_web_digest=" + WEB_DIGEST in result.stdout
    assert gate.api_put_calls() == []
    assert not any(
        call.startswith("gcloud run deploy ")
        or call.startswith("gcloud run services replace ")
        or " update-traffic " in call
        or call.startswith("gcloud storage ")
        for call in gate.calls()
    )
    assert any(AGENT_CANDIDATE_URL + "/health" in call for call in gate.calls())
    assert any(WEB_CANDIDATE_URL + "/support" in call for call in gate.calls())


def test_service_ownership_labels_bind_revisions_without_assuming_revision_labels(
    gate: Fixture,
) -> None:
    for revision_name in (AGENT_CANDIDATE, WEB_CANDIDATE):
        gate.revisions[revision_name]["metadata"]["labels"] = {
            "serving.knative.dev/service": (
                AGENT_SERVICE if revision_name == AGENT_CANDIDATE else WEB_SERVICE
            )
        }
        gate.write_json(
            gate.state / "revisions" / f"{revision_name}.json",
            gate.revisions[revision_name],
        )
    result = gate.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "validation=PASS" in result.stdout


@pytest.mark.parametrize("confirmation", [None, "yes", "PROMOTE_VERIFIED_CANDIDATE"])
def test_apply_requires_exact_confirmation(
    gate: Fixture, confirmation: str | None
) -> None:
    result = gate.run(apply=True, confirm=confirmation)
    assert_failed_without_mutation(result, gate)
    assert "promotion_confirmation=INVALID" in result.stderr


def test_apply_claims_both_services_with_random_invocation_lock_before_cutover(
    gate: Fixture,
) -> None:
    original_specs = {
        name: json.loads(json.dumps(value["spec"]))
        for name, value in gate.services.items()
    }
    result = gate.run(
        apply=True, confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payloads = gate.replacement_payloads()
    assert len(payloads) == 5
    agent_claim, web_claim = payloads[:2]
    agent_lock = agent_claim["metadata"]["labels"]["deployment-lock"]
    web_lock = web_claim["metadata"]["labels"]["deployment-lock"]
    assert agent_lock == web_lock
    assert agent_lock != SOURCE_SHA
    assert len(agent_lock) == 40
    assert agent_lock.startswith("promote-")
    assert set(agent_lock.removeprefix("promote-")) <= set("0123456789abcdef")
    for payload, name, initial_rv in (
        (agent_claim, AGENT_SERVICE, AGENT_RV_AFTER),
        (web_claim, WEB_SERVICE, WEB_RV_AFTER),
    ):
        assert payload["metadata"]["resourceVersion"] == initial_rv
        assert payload["metadata"]["labels"] == {
            **gate.services[name]["metadata"]["labels"],
            "deployment-lock": agent_lock,
        }
        assert payload["spec"] == original_specs[name]
    assert service_lock(gate, AGENT_SERVICE) == agent_lock
    assert service_lock(gate, WEB_SERVICE) == agent_lock
    assert agent_lock.removeprefix("promote-")[:10] in payloads[3]["spec"][
        "template"
    ]["metadata"]["name"]
    assert_no_mutating_gcloud(gate)


def test_second_claim_resource_version_conflict_restores_only_owned_first_claim(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={"FAKE_RACE_WEB_CLAIM": "1"},
    )
    assert result.returncode != 0
    assert [
        payload["metadata"]["name"] for payload in gate.replacement_payloads()
    ] == [AGENT_SERVICE, AGENT_SERVICE]
    assert service_lock(gate, AGENT_SERVICE) == SOURCE_SHA
    assert service_lock(gate, WEB_SERVICE) == "promote-" + "f" * 32
    assert "claim_restore=PASS" in result.stderr
    assert sum("web-claim-payload.json" in call for call in gate.api_put_calls()) == 1
    assert "cloud_run_api=CONFLICT" in result.stderr


def test_second_claim_conflict_never_restores_first_claim_after_owner_changes(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={
            "FAKE_RACE_WEB_CLAIM": "1",
            "FAKE_STEAL_AGENT_ON_WEB_CLAIM": "1",
        },
    )
    assert result.returncode != 0
    assert len(gate.replacement_payloads()) == 1
    assert service_lock(gate, AGENT_SERVICE) == "promote-" + "e" * 32
    assert service_lock(gate, WEB_SERVICE) == "promote-" + "f" * 32
    assert "claim_restore=REFUSED" in result.stderr


def test_same_source_concurrent_loser_cannot_rollback_winner(gate: Fixture) -> None:
    wait_path = gate.root / "stale-claim"
    loser = gate.start(
        output_path=gate.root / "loser-evidence.json",
        extra_env={"FAKE_WAIT_BEFORE_AGENT_CLAIM": str(wait_path)},
    )
    ready_path = wait_path.with_suffix(".ready")
    deadline = time.monotonic() + 20
    while not ready_path.exists():
        if loser.poll() is not None:
            stdout, stderr = loser.communicate()
            pytest.fail(f"loser exited before claim barrier: {stdout}{stderr}")
        if time.monotonic() >= deadline:
            loser.kill()
            pytest.fail("timed out waiting for stale claim barrier")
        time.sleep(0.02)

    winner = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        output_path=gate.root / "winner-evidence.json",
    )
    assert winner.returncode == 0, winner.stdout + winner.stderr
    winner_lock = service_lock(gate, AGENT_SERVICE)
    assert winner_lock == service_lock(gate, WEB_SERVICE)
    assert winner_lock != SOURCE_SHA

    wait_path.with_suffix(".release").write_text("release\n", encoding="utf-8")
    loser_stdout, loser_stderr = loser.communicate(timeout=20)
    assert loser.returncode != 0, loser_stdout + loser_stderr
    assert service_lock(gate, AGENT_SERVICE) == winner_lock
    assert service_lock(gate, WEB_SERVICE) == winner_lock
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_CANDIDATE


def test_same_source_stale_loser_cannot_release_the_winners_partial_claim(
    gate: Fixture,
) -> None:
    first_before = gate.root / "first-before-claim"
    first_after = gate.root / "first-after-claim"
    second_before = gate.root / "second-before-claim"
    first = gate.start(
        output_path=gate.root / "first-evidence.json",
        extra_env={
            "FAKE_WAIT_BEFORE_AGENT_CLAIM": str(first_before),
            "FAKE_WAIT_AFTER_AGENT_CLAIM": str(first_after),
        },
    )
    second = gate.start(
        output_path=gate.root / "second-evidence.json",
        extra_env={"FAKE_WAIT_BEFORE_AGENT_CLAIM": str(second_before)},
    )

    def wait_for(path: Path, process: subprocess.Popen[str]) -> None:
        deadline = time.monotonic() + 20
        while not path.exists():
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                pytest.fail(f"process exited before barrier: {stdout}{stderr}")
            if time.monotonic() >= deadline:
                pytest.fail(f"timed out waiting for {path.name}")
            time.sleep(0.02)

    try:
        wait_for(first_before.with_suffix(".ready"), first)
        wait_for(second_before.with_suffix(".ready"), second)
        first_before.with_suffix(".release").write_text(
            "release\n", encoding="utf-8"
        )
        wait_for(first_after.with_suffix(".ready"), first)
        winner_lock = service_lock(gate, AGENT_SERVICE)
        assert winner_lock.startswith("promote-")

        second_before.with_suffix(".release").write_text(
            "release\n", encoding="utf-8"
        )
        second_stdout, second_stderr = second.communicate(timeout=20)
        assert second.returncode != 0, second_stdout + second_stderr
        assert service_lock(gate, AGENT_SERVICE) == winner_lock
        assert "claim_restore=PASS" in second_stderr

        first_after.with_suffix(".release").write_text(
            "release\n", encoding="utf-8"
        )
        first_stdout, first_stderr = first.communicate(timeout=20)
        assert first.returncode == 0, first_stdout + first_stderr
        assert service_lock(gate, AGENT_SERVICE) == winner_lock
        assert service_lock(gate, WEB_SERVICE) == winner_lock
    finally:
        for barrier in (first_before, first_after, second_before):
            barrier.with_suffix(".release").write_text(
                "release\n", encoding="utf-8"
            )
        for process in (first, second):
            if process.poll() is None:
                process.kill()
                process.communicate()


def test_conditional_payloads_preserve_templates_and_use_fresh_resource_versions(
    gate: Fixture,
) -> None:
    original_agent_template = gate.services[AGENT_SERVICE]["spec"]["template"]
    result = gate.run(
        apply=True, confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payloads = gate.replacement_payloads()
    assert len(payloads) == 5
    agent_payload = payloads[2]
    final_revision_payload = payloads[3]
    web_payload = payloads[4]
    assert agent_payload["metadata"]["resourceVersion"].isdigit()
    assert agent_payload["spec"]["template"] == original_agent_template
    assert traffic_by_tag({"spec": agent_payload["spec"]})[CANDIDATE_TAG] == {
        "revisionName": AGENT_CANDIDATE,
        "percent": 100,
        "tag": CANDIDATE_TAG,
    }
    assert web_payload["metadata"]["resourceVersion"].isdigit()
    assert int(web_payload["metadata"]["resourceVersion"]) > int(
        final_revision_payload["metadata"]["resourceVersion"]
    )
    assert web_payload["spec"]["template"]["spec"]["containers"][0][
        "env"
    ] != gate.services[WEB_SERVICE]["spec"]["template"]["spec"]["containers"][0][
        "env"
    ]


def test_apply_promotes_agent_before_final_web_and_rebinds_stable_agent_url(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True, confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = gate.calls()
    api_put_indices = [
        index
        for index, call in enumerate(calls)
        if call.startswith("curl ")
        and "-run.googleapis.com/apis/serving.knative.dev/" in call
    ]
    assert len(api_put_indices) == 5
    assert api_put_indices == sorted(api_put_indices)
    payloads = gate.replacement_payloads()
    assert [payload["metadata"]["name"] for payload in payloads] == [
        AGENT_SERVICE,
        WEB_SERVICE,
        AGENT_SERVICE,
        WEB_SERVICE,
        WEB_SERVICE,
    ]
    final_name = (gate.state / "final-revision.txt").read_text(encoding="utf-8")
    final = json.loads(
        (gate.state / "revisions" / f"{final_name}.json").read_text(
            encoding="utf-8"
        )
    )
    final_env = {
        row["name"]: row["value"]
        for row in final["spec"]["containers"][0]["env"]
    }
    assert final_env["SUMAI_AGENT_URL"] == AGENT_STABLE_URL
    assert final_env["PUBLIC_WEB_ANALYSIS_ENABLED"] == "false"
    assert not any("/api/v1/analyze" in call for call in calls)
    assert_no_mutating_gcloud(gate)


def test_final_web_deploy_preserves_complete_candidate_runtime_configuration(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True, confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    final_name = (gate.state / "final-revision.txt").read_text(encoding="utf-8")
    final = json.loads(
        (gate.state / "revisions" / f"{final_name}.json").read_text(
            encoding="utf-8"
        )
    )
    candidate = gate.revisions[WEB_CANDIDATE]
    candidate_container = candidate["spec"]["containers"][0]
    final_container = final["spec"]["containers"][0]
    for key in (
        "command",
        "args",
        "ports",
        "resources",
        "startupProbe",
        "livenessProbe",
        "volumeMounts",
    ):
        assert final_container[key] == candidate_container[key]
    assert final["spec"]["volumes"] == candidate["spec"]["volumes"]
    assert final["metadata"]["annotations"] == candidate["metadata"]["annotations"]


def test_dry_run_rejects_unsupported_extra_candidate_container(
    gate: Fixture,
) -> None:
    containers = gate.revisions[WEB_CANDIDATE]["spec"]["containers"]
    containers.append(json.loads(json.dumps(containers[0])))
    for name, payload in gate.services.items():
        gate.write_json(gate.state / "services" / f"{name}.json", payload)
    for name, payload in gate.revisions.items():
        gate.write_json(gate.state / "revisions" / f"{name}.json", payload)
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "candidate_state=INVALID" in result.stderr


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda container, spec: container.__setitem__("command", "python3"),
            id="command-scalar",
        ),
        pytest.param(
            lambda container, spec: container.__setitem__("args", ["-m", 7]),
            id="args-non-string",
        ),
        pytest.param(
            lambda container, spec: container.__setitem__(
                "startupProbe", "invalid"
            ),
            id="probe-scalar",
        ),
        pytest.param(
            lambda container, spec: container["startupProbe"].__setitem__(
                "httpGet", "invalid"
            ),
            id="http-get-scalar",
        ),
        pytest.param(
            lambda container, spec: container["startupProbe"][
                "httpGet"
            ].__setitem__("port", "8080"),
            id="probe-port-string",
        ),
        pytest.param(
            lambda container, spec: container["volumeMounts"][0].__setitem__(
                "mountPath", 7
            ),
            id="numeric-mount-path",
        ),
        pytest.param(
            lambda container, spec: spec["volumes"][0].__setitem__(
                "emptyDir", "Memory"
            ),
            id="empty-dir-scalar",
        ),
        pytest.param(
            lambda container, spec: container["startupProbe"][
                "httpGet"
            ].__setitem__("unknown", "value"),
            id="unknown-http-get-key",
        ),
        pytest.param(
            lambda container, spec: spec.__setitem__("timeoutSeconds", True),
            id="bool-as-int",
        ),
        pytest.param(
            lambda container, spec: container["startupProbe"]["httpGet"].__setitem__(
                "httpHeaders", [{"name": "X-Test", "value": 7}]
            ),
            id="malformed-http-header",
        ),
        pytest.param(
            lambda container, spec: spec["volumes"].append(
                {
                    "name": "secret-data",
                    "secret": {
                        "secretName": "runtime-secret",
                        "items": [{"key": 7, "path": "value"}],
                    },
                }
            ),
            id="malformed-secret-item",
        ),
        pytest.param(
            lambda container, spec: spec.__setitem__("volumes", {}),
            id="volumes-mapping",
        ),
        pytest.param(
            lambda container, spec: container["resources"].__setitem__(
                "unsupported", {}
            ),
            id="unknown-resources-key",
        ),
        pytest.param(
            lambda container, spec: container.__setitem__(
                "unsupportedRuntimeField", "value"
            ),
            id="unknown-container-key",
        ),
    ],
)
def test_dry_run_rejects_malformed_candidate_runtime_shape(
    gate: Fixture, mutate: Callable[[dict[str, Any], dict[str, Any]], None]
) -> None:
    spec = gate.revisions[WEB_CANDIDATE]["spec"]
    mutate(spec["containers"][0], spec)
    for name, payload in gate.services.items():
        gate.write_json(gate.state / "services" / f"{name}.json", payload)
    for name, payload in gate.revisions.items():
        gate.write_json(gate.state / "revisions" / f"{name}.json", payload)
    result = gate.run()
    assert_failed_without_mutation(result, gate)
    assert "candidate_state=INVALID" in result.stderr


def test_supported_nested_runtime_schema_survives_final_deep_equality(
    gate: Fixture,
) -> None:
    spec = gate.revisions[WEB_CANDIDATE]["spec"]
    container = spec["containers"][0]
    container["ports"] = [
        {"containerPort": 8080, "name": "http1", "protocol": "TCP"}
    ]
    container["resources"] = {
        "limits": {"cpu": "1", "memory": "1Gi"},
        "requests": {"cpu": "1", "memory": "1Gi"},
    }
    container["startupProbe"] = {
        "httpGet": {
            "path": "/ready",
            "port": 8080,
            "scheme": "HTTP",
            "httpHeaders": [{"name": "X-Probe", "value": "startup"}],
        },
        "initialDelaySeconds": 0,
        "timeoutSeconds": 1,
        "periodSeconds": 2,
        "successThreshold": 1,
        "failureThreshold": 30,
    }
    container["livenessProbe"] = {
        "grpc": {"port": 8080, "service": "sumai.Web"},
        "timeoutSeconds": 1,
        "periodSeconds": 10,
        "failureThreshold": 3,
    }
    spec["volumes"] = [
        {"name": "runtime-data", "emptyDir": {"medium": "Memory", "sizeLimit": "64Mi"}},
        {
            "name": "secret-data",
            "secret": {
                "secretName": "runtime-secret",
                "defaultMode": 0o440,
                "items": [{"key": "latest", "path": "value", "mode": 0o440}],
            },
        },
        {
            "name": "cloudsql-data",
            "cloudSqlInstance": {
                "instances": ["sumai-prod-123:asia-northeast1:runtime"]
            },
        },
        {
            "name": "nfs-data",
            "nfs": {
                "server": "10.0.0.2",
                "path": "/exports/runtime",
                "readOnly": True,
            },
        },
    ]
    container["volumeMounts"] = [
        {"name": "runtime-data", "mountPath": "/tmp/runtime"},
        {
            "name": "secret-data",
            "mountPath": "/var/run/secret",
            "readOnly": True,
            "subPath": "value",
        },
        {"name": "cloudsql-data", "mountPath": "/cloudsql"},
        {"name": "nfs-data", "mountPath": "/mnt/nfs", "readOnly": True},
    ]
    for name, payload in gate.services.items():
        gate.write_json(gate.state / "services" / f"{name}.json", payload)
    for name, payload in gate.revisions.items():
        gate.write_json(gate.state / "revisions" / f"{name}.json", payload)

    result = gate.run(
        apply=True, confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_supported_tcp_socket_probe_schema_passes_dry_run(gate: Fixture) -> None:
    container = gate.revisions[WEB_CANDIDATE]["spec"]["containers"][0]
    container["livenessProbe"] = {
        "tcpSocket": {"port": 8080},
        "timeoutSeconds": 1,
        "periodSeconds": 10,
        "failureThreshold": 3,
    }
    for name, payload in gate.services.items():
        gate.write_json(gate.state / "services" / f"{name}.json", payload)
    for name, payload in gate.revisions.items():
        gate.write_json(gate.state / "revisions" / f"{name}.json", payload)
    result = gate.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "validation=PASS" in result.stdout


@pytest.mark.parametrize("drift", ["command", "args", "probe", "resources"])
def test_final_web_runtime_drift_fails_before_web_traffic_and_rolls_back_agent(
    gate: Fixture, drift: str
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={"FAKE_DEPLOY_RUNTIME_DRIFT": drift},
    )
    assert result.returncode != 0
    assert [
        payload["metadata"]["name"] for payload in gate.replacement_payloads()
    ] == [AGENT_SERVICE, WEB_SERVICE, AGENT_SERVICE, WEB_SERVICE, AGENT_SERVICE]
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_PREDECESSOR
    assert gate.current_service(WEB_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == WEB_PREDECESSOR
    assert "rollback_result=PASS" in result.stderr


@pytest.mark.parametrize("drift", ["config", "artifact"])
def test_post_agent_promotion_drift_fails_before_any_web_mutation(
    gate: Fixture, drift: str
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={"FAKE_AGENT_POST_PROMOTION_DRIFT": drift},
    )
    assert result.returncode != 0
    assert not any(
        "final-web-service-payload.json" in call for call in gate.api_put_calls()
    )
    assert [
        payload["metadata"]["name"] for payload in gate.replacement_payloads()
    ] == [AGENT_SERVICE, WEB_SERVICE, AGENT_SERVICE, AGENT_SERVICE]
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_PREDECESSOR


def test_agent_cutover_lock_and_resource_version_race_never_overwrites_winner(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={"FAKE_RACE_AGENT_CUTOVER": "1"},
    )
    assert result.returncode != 0
    assert service_lock(gate, AGENT_SERVICE) == "promote-" + "f" * 32
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_PREDECESSOR
    assert sum("agent-promotion-payload.json" in call for call in gate.api_put_calls()) == 1
    assert "cloud_run_api=CONFLICT" in result.stderr
    assert "rollback_refused=DEPLOYMENT_LOCK_OR_IDENTITY_MISMATCH" in result.stderr


def test_web_cutover_foreign_lock_at_predecessor_allows_owned_agent_rollback(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={"FAKE_RACE_WEB_CUTOVER": "1"},
    )
    assert result.returncode != 0
    assert service_lock(gate, WEB_SERVICE) == "promote-" + "f" * 32
    assert gate.current_service(WEB_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == WEB_PREDECESSOR
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_PREDECESSOR
    evidence = json.loads(gate.output_path.read_text(encoding="utf-8"))
    assert evidence["rollback_results"] == {
        "agent": "PASS",
        "web": "ALREADY_PREDECESSOR_FOREIGN_LOCK",
    }
    assert evidence["rollback_result"] == "PARTIAL"
    assert "rollback_refused=DEPLOYMENT_LOCK_OR_IDENTITY_MISMATCH" in result.stderr


def test_web_cutover_resource_version_race_uses_fresh_versions_for_rollback(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={"FAKE_RV_RACE_WEB_CUTOVER": "1"},
    )
    assert result.returncode != 0
    assert gate.current_service(WEB_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == WEB_PREDECESSOR
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_PREDECESSOR
    assert sum("web-promotion-payload.json" in call for call in gate.api_put_calls()) == 1
    assert "rollback_result=PASS" in result.stderr


def test_foreign_zero_percent_tags_survive_claims_and_both_promotions(
    gate: Fixture,
) -> None:
    add_foreign_zero_tag(
        gate, AGENT_SERVICE, FOREIGN_AGENT_REVISION, FOREIGN_AGENT_TAG
    )
    add_foreign_zero_tag(
        gate, WEB_SERVICE, FOREIGN_WEB_REVISION, FOREIGN_WEB_TAG
    )
    result = gate.run(
        apply=True, confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payloads = gate.replacement_payloads()
    assert traffic_by_tag({"spec": payloads[0]["spec"]})[FOREIGN_AGENT_TAG] == {
        "revisionName": FOREIGN_AGENT_REVISION,
        "percent": 0,
        "tag": FOREIGN_AGENT_TAG,
    }
    assert traffic_by_tag({"spec": payloads[1]["spec"]})[FOREIGN_WEB_TAG] == {
        "revisionName": FOREIGN_WEB_REVISION,
        "percent": 0,
        "tag": FOREIGN_WEB_TAG,
    }
    agent_tags = traffic_by_tag(gate.current_service(AGENT_SERVICE))
    web_tags = traffic_by_tag(gate.current_service(WEB_SERVICE))
    assert agent_tags[FOREIGN_AGENT_TAG]["revisionName"] == FOREIGN_AGENT_REVISION
    assert agent_tags[FOREIGN_AGENT_TAG]["percent"] == 0
    assert web_tags[FOREIGN_WEB_TAG]["revisionName"] == FOREIGN_WEB_REVISION
    assert web_tags[FOREIGN_WEB_TAG]["percent"] == 0


def test_foreign_zero_percent_tags_survive_web_then_agent_rollback(
    gate: Fixture,
) -> None:
    add_foreign_zero_tag(
        gate, AGENT_SERVICE, FOREIGN_AGENT_REVISION, FOREIGN_AGENT_TAG
    )
    add_foreign_zero_tag(
        gate, WEB_SERVICE, FOREIGN_WEB_REVISION, FOREIGN_WEB_TAG
    )
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={"FAKE_CURL_FAIL_SUBSTRING": WEB_STABLE_URL + "/support"},
    )
    assert result.returncode != 0
    for service_name, tag, revision_name in (
        (AGENT_SERVICE, FOREIGN_AGENT_TAG, FOREIGN_AGENT_REVISION),
        (WEB_SERVICE, FOREIGN_WEB_TAG, FOREIGN_WEB_REVISION),
    ):
        target = traffic_by_tag(gate.current_service(service_name))[tag]
        assert target["revisionName"] == revision_name
        assert target["percent"] == 0
    assert "rollback_result=PASS" in result.stderr


def test_candidate_final_and_production_safe_endpoints_are_probed(gate: Fixture) -> None:
    result = gate.run(
        apply=True, confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = gate.calls()
    final_revision = (gate.state / "final-revision.txt").read_text()
    final_tag = next(
        row["tag"]
        for row in gate.current_service(WEB_SERVICE)["spec"]["traffic"]
        if row.get("revisionName") == final_revision
    )
    final_url = f"https://{final_tag}---sumai-web.example.run.app"
    for url in (
        AGENT_CANDIDATE_URL + "/health",
        WEB_CANDIDATE_URL + "/privacy",
        AGENT_STABLE_URL + "/ready",
        final_url + "/",
        final_url + "/ready",
        final_url + "/privacy",
        final_url + "/support",
        WEB_STABLE_URL + "/privacy",
        WEB_STABLE_URL + "/support",
    ):
        assert any(url in call for call in calls), (url, calls)
    assert final_revision.startswith("sumai-web-final-")


def test_failure_rolls_back_web_then_agent_only_while_release_locks_match(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={"FAKE_CURL_FAIL_SUBSTRING": WEB_STABLE_URL + "/support"},
    )
    assert result.returncode != 0
    payloads = gate.replacement_payloads()
    assert [payload["metadata"]["name"] for payload in payloads] == [
        AGENT_SERVICE,
        WEB_SERVICE,
        AGENT_SERVICE,
        WEB_SERVICE,
        WEB_SERVICE,
        WEB_SERVICE,
        AGENT_SERVICE,
    ]
    assert payloads[-2]["spec"]["traffic"][0]["revisionName"] == WEB_PREDECESSOR
    assert payloads[-1]["spec"]["traffic"][0]["revisionName"] == AGENT_PREDECESSOR
    assert gate.current_service(WEB_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == WEB_PREDECESSOR
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_PREDECESSOR
    assert "rollback_result=PASS" in result.stderr


def test_foreign_agent_lock_does_not_block_still_owned_web_rollback(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={
            "FAKE_CURL_FAIL_SUBSTRING": WEB_STABLE_URL + "/support",
            "FAKE_FOREIGN_AGENT_LOCK_ON_FAIL": "1",
        },
    )
    assert result.returncode != 0
    assert [
        payload["metadata"]["name"] for payload in gate.replacement_payloads()
    ] == [
        AGENT_SERVICE,
        WEB_SERVICE,
        AGENT_SERVICE,
        WEB_SERVICE,
        WEB_SERVICE,
        WEB_SERVICE,
    ]
    assert gate.current_service(WEB_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == WEB_PREDECESSOR
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_CANDIDATE
    evidence = json.loads(gate.output_path.read_text(encoding="utf-8"))
    assert evidence["rollback_results"] == {
        "agent": "REFUSED_FOREIGN_LOCK",
        "web": "PASS",
    }
    assert evidence["rollback_result"] == "PARTIAL"
    assert "rollback_result=PARTIAL" in result.stderr


def test_foreign_web_at_safe_predecessor_does_not_block_owned_agent_rollback(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={
            "FAKE_CURL_FAIL_SUBSTRING": WEB_STABLE_URL + "/support",
            "FAKE_FOREIGN_WEB_SAFE_ON_FAIL": "1",
        },
    )
    assert result.returncode != 0
    assert [
        payload["metadata"]["name"] for payload in gate.replacement_payloads()
    ] == [
        AGENT_SERVICE,
        WEB_SERVICE,
        AGENT_SERVICE,
        WEB_SERVICE,
        WEB_SERVICE,
        AGENT_SERVICE,
    ], result.stderr
    assert gate.current_service(WEB_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == WEB_PREDECESSOR
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_PREDECESSOR
    evidence = json.loads(gate.output_path.read_text(encoding="utf-8"))
    assert evidence["rollback_results"] == {
        "agent": "PASS",
        "web": "ALREADY_PREDECESSOR_FOREIGN_LOCK",
    }
    assert evidence["rollback_result"] == "PARTIAL"
    assert "rollback_result=PARTIAL" in result.stderr


def test_foreign_or_newer_lock_refuses_all_rollback_mutation(gate: Fixture) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={
            "FAKE_CURL_FAIL_SUBSTRING": "promoted-",
            "FAKE_FOREIGN_LOCK_ON_FAIL": "1",
        },
    )
    assert result.returncode != 0
    assert len(gate.replacement_payloads()) == 4
    assert "rollback_refused=DEPLOYMENT_LOCK_OR_IDENTITY_MISMATCH" in result.stderr


def test_new_agent_lock_after_web_rollback_refuses_agent_rollback(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={
            "FAKE_CURL_FAIL_SUBSTRING": WEB_STABLE_URL + "/support",
            "FAKE_FOREIGN_AGENT_LOCK_AFTER_WEB_ROLLBACK": "1",
        },
    )
    assert result.returncode != 0
    assert [
        payload["metadata"]["name"] for payload in gate.replacement_payloads()
    ] == [
        AGENT_SERVICE,
        WEB_SERVICE,
        AGENT_SERVICE,
        WEB_SERVICE,
        WEB_SERVICE,
        WEB_SERVICE,
    ]
    assert "rollback_refused=DEPLOYMENT_LOCK_OR_IDENTITY_MISMATCH" in result.stderr


def test_ambiguous_web_deploy_with_owned_lock_rolls_back_agent_traffic(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={"FAKE_DEPLOY_FAIL_AFTER_MUTATION": "1"},
    )
    assert result.returncode != 0
    assert [
        payload["metadata"]["name"] for payload in gate.replacement_payloads()
    ] == [AGENT_SERVICE, WEB_SERVICE, AGENT_SERVICE, WEB_SERVICE, AGENT_SERVICE]
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_PREDECESSOR
    assert gate.current_service(WEB_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == WEB_PREDECESSOR
    assert "rollback_result=PASS" in result.stderr


@pytest.mark.parametrize(
    "access_token",
    [
        "ya29.fake-promotion-token-never-log-this-value",
        "ya29.rfc6750+slash/token==still-private",
    ],
)
def test_apply_never_uses_mutating_gcloud_and_keeps_access_token_private(
    gate: Fixture, access_token: str,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={"FAKE_ACCESS_TOKEN": access_token},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(gate.api_put_calls()) == 5
    assert all("--retry" not in call for call in gate.api_put_calls())
    assert_no_mutating_gcloud(gate)
    token = access_token
    all_visible = result.stdout + result.stderr + "\n".join(gate.calls())
    assert token not in all_visible
    assert token not in gate.output_path.read_text(encoding="utf-8")
    assert token not in json.dumps(gate.replacement_payloads())
    assert sum(
        call.startswith("gcloud auth print-access-token ")
        for call in gate.calls()
    ) == 5


@pytest.mark.parametrize(
    ("operation", "delay_env", "failure_url", "service_name", "expected_revision"),
    [
        (
            "agent-cutover",
            "FAKE_ASYNC_AGENT_CUTOVER_READS",
            None,
            AGENT_SERVICE,
            AGENT_CANDIDATE,
        ),
        (
            "web-cutover",
            "FAKE_ASYNC_WEB_CUTOVER_READS",
            None,
            WEB_SERVICE,
            "FINAL",
        ),
        (
            "web-rollback",
            "FAKE_ASYNC_WEB_ROLLBACK_READS",
            WEB_STABLE_URL + "/support",
            WEB_SERVICE,
            WEB_PREDECESSOR,
        ),
        (
            "agent-rollback",
            "FAKE_ASYNC_AGENT_ROLLBACK_READS",
            WEB_STABLE_URL + "/support",
            AGENT_SERVICE,
            AGENT_PREDECESSOR,
        ),
    ],
)
def test_traffic_mutations_poll_read_only_until_spec_and_status_converge(
    gate: Fixture,
    operation: str,
    delay_env: str,
    failure_url: str | None,
    service_name: str,
    expected_revision: str,
) -> None:
    extra_env = {delay_env: "2"}
    if failure_url is not None:
        extra_env["FAKE_CURL_FAIL_SUBSTRING"] = failure_url
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env=extra_env,
    )
    if failure_url is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert "rollback_result=PASS" in result.stderr
    assert gate.async_read_count(operation) >= 3
    if expected_revision == "FINAL":
        expected_revision = (gate.state / "final-revision.txt").read_text(
            encoding="utf-8"
        )
    for location in ("spec", "status"):
        positive = [
            row["revisionName"]
            for row in gate.current_service(service_name)[location]["traffic"]
            if row.get("percent") == 100
        ]
        assert positive == [expected_revision]
    payload_fragment = operation.replace("-cutover", "-promotion").replace(
        "web-rollback", "rollback-web"
    ).replace("agent-rollback", "rollback-agent") + "-payload.json"
    assert sum(
        payload_fragment in call for call in gate.api_put_calls()
    ) == 1


def test_agent_cutover_convergence_timeout_never_reissues_put_and_rolls_back(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={"FAKE_ASYNC_AGENT_CUTOVER_READS": "999"},
    )
    assert result.returncode != 0
    assert "traffic_convergence=TIMEOUT" in result.stderr
    assert sum(
        "agent-promotion-payload.json" in call for call in gate.api_put_calls()
    ) == 1
    assert sum(
        "rollback-agent-payload.json" in call for call in gate.api_put_calls()
    ) == 1
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_PREDECESSOR
    assert "rollback_agent=PASS" in result.stderr


@pytest.mark.parametrize("conflict_status", ["409", "412"])
def test_final_web_creation_resource_version_race_conflicts_once_and_rolls_back_agent(
    gate: Fixture, conflict_status: str,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={
            "FAKE_RACE_FINAL_WEB_CREATE": "1",
            "FAKE_API_CONFLICT_STATUS": conflict_status,
        },
    )
    assert result.returncode != 0
    assert [
        payload["metadata"]["name"] for payload in gate.replacement_payloads()
    ] == [AGENT_SERVICE, WEB_SERVICE, AGENT_SERVICE, AGENT_SERVICE]
    assert sum("final-web-service-payload.json" in call for call in gate.api_put_calls()) == 1
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_PREDECESSOR
    assert gate.current_service(WEB_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == WEB_PREDECESSOR
    assert "cloud_run_api=CONFLICT" in result.stderr


def test_agent_rollback_resource_version_conflict_is_not_retried(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={
            "FAKE_CURL_FAIL_SUBSTRING": AGENT_STABLE_URL + "/ready",
            "FAKE_RACE_AGENT_ROLLBACK": "1",
        },
    )
    assert result.returncode != 0
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_CANDIDATE
    rollback_calls = [
        call for call in gate.api_put_calls() if "rollback-agent-payload.json" in call
    ]
    assert len(rollback_calls) == 1
    assert "rollback_agent=FAILED" in result.stderr


def test_tagged_production_predecessors_are_preserved_at_zero_after_cutover(
    gate: Fixture,
) -> None:
    for service_name, predecessor, prior_tag in (
        (AGENT_SERVICE, AGENT_PREDECESSOR, "prior-agent-stable"),
        (WEB_SERVICE, WEB_PREDECESSOR, "prior-web-stable"),
    ):
        service_value = gate.services[service_name]
        for location in ("spec", "status"):
            production = next(
                row
                for row in service_value[location]["traffic"]
                if row.get("revisionName") == predecessor
            )
            production["tag"] = prior_tag
            if location == "status":
                production["url"] = (
                    f"https://{prior_tag}---{service_name}.example.run.app"
                )
        gate.write_json(
            gate.state / "services" / f"{service_name}.json", service_value
        )
    result = gate.run(
        apply=True, confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert traffic_by_tag(gate.current_service(AGENT_SERVICE))[
        "prior-agent-stable"
    ]["percent"] == 0
    assert traffic_by_tag(gate.current_service(WEB_SERVICE))[
        "prior-web-stable"
    ]["percent"] == 0


def test_foreign_web_change_during_stable_agent_probe_blocks_agent_rollback(
    gate: Fixture,
) -> None:
    result = gate.run(
        apply=True,
        confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE",
        extra_env={
            "FAKE_CURL_FAIL_SUBSTRING": AGENT_STABLE_URL + "/ready",
            "FAKE_FOREIGN_WEB_UNSAFE_ON_FAIL": "1",
        },
    )
    assert result.returncode != 0
    assert gate.current_service(WEB_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == WEB_CANDIDATE
    assert gate.current_service(AGENT_SERVICE)["status"]["traffic"][0][
        "revisionName"
    ] == AGENT_CANDIDATE
    assert "rollback_agent=BLOCKED_WEB_NOT_SAFE" in result.stderr


def test_success_evidence_is_atomic_private_and_sanitized(gate: Fixture) -> None:
    result = gate.run(
        apply=True, confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(gate.output_path.read_text(encoding="utf-8"))
    assert stat.S_IMODE(gate.output_path.stat().st_mode) == 0o600
    assert evidence["source_commit"] == SOURCE_SHA
    assert evidence["build_id"] == BUILD_ID
    assert evidence["applied"] is True
    assert evidence["mode"] == "apply"
    assert evidence["prior_revisions"] == {
        "agent": AGENT_PREDECESSOR,
        "web": WEB_PREDECESSOR,
    }
    assert evidence["candidate_revisions"] == {
        "agent": AGENT_CANDIDATE,
        "web": WEB_CANDIDATE,
    }
    assert evidence["final_revisions"]["agent"] == AGENT_CANDIDATE
    assert evidence["final_revisions"]["web"].startswith("sumai-web-final-")
    serialized = json.dumps(evidence).casefold()
    for forbidden in (
        "token",
        "authorization",
        "request_body",
        "response_body",
        "base64",
        "image_content",
        "report_content",
        "action_content",
        "home_content",
        AGENT_ACCOUNT.casefold(),
        WEB_ACCOUNT.casefold(),
    ):
        assert forbidden not in serialized
    assert not list(gate.root.glob(f".{gate.output_path.name}.*"))


def test_apply_rejects_unsafe_output_symlink_before_any_mutation(gate: Fixture) -> None:
    target = gate.root / "actual.json"
    target.write_text("keep", encoding="utf-8")
    gate.output_path.symlink_to(target)
    result = gate.run(
        apply=True, confirm="PROMOTE_VERIFIED_SUMAI_CANDIDATE"
    )
    assert_failed_without_mutation(result, gate)
    assert target.read_text(encoding="utf-8") == "keep"
    assert "promotion_evidence_path=UNSAFE" in result.stderr
