#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

: "${GOOGLE_CLOUD_PROJECT:?GOOGLE_CLOUD_PROJECT is required}"
: "${SUMAI_CANDIDATE_EVIDENCE:?SUMAI_CANDIDATE_EVIDENCE is required}"
: "${SUMAI_DEVICE_EVIDENCE:?SUMAI_DEVICE_EVIDENCE is required}"

region="${SUMAI_REGION:-asia-northeast1}"
apply_mode="${SUMAI_PROMOTE_APPLY:-false}"
confirmation="${SUMAI_PROMOTE_CONFIRM:-}"
promotion_evidence_path="${SUMAI_PROMOTION_EVIDENCE:-}"
agent_service="sumai-agent"
web_service="sumai-web"
readonly traffic_convergence_attempts=8
readonly traffic_convergence_delay_seconds=2

if ! python3 - "${GOOGLE_CLOUD_PROJECT}" "${region}" <<'PY'
import re
import sys

project, region = sys.argv[1:]
if re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project) is None:
    raise SystemExit(1)
if len(region) > 40 or re.fullmatch(
    r"[a-z][a-z0-9]{0,14}(?:-[a-z0-9]{1,15}){1,2}", region
) is None:
    raise SystemExit(1)
PY
then
  printf 'cloud_run_api_target=INVALID\n' >&2
  exit 1
fi

case "${apply_mode}" in
  true|false) ;;
  *)
    printf 'promotion_mode=INVALID\n' >&2
    exit 1
    ;;
esac

if [[ "${apply_mode}" == true ]]; then
  if [[ "${confirmation}" != "PROMOTE_VERIFIED_SUMAI_CANDIDATE" ]]; then
    printf 'promotion_confirmation=INVALID\n' >&2
    exit 1
  fi
  if [[ -z "${promotion_evidence_path}" ]]; then
    printf 'promotion_evidence_path=REQUIRED\n' >&2
    exit 1
  fi
fi

validate_input_path() {
  local input_path="$1"
  local label="$2"
  if ! python3 - "${input_path}" <<'PY'
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    info = path.lstat()
except OSError:
    raise SystemExit(1)
if not path.is_absolute() or stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
    raise SystemExit(1)
if info.st_size <= 0 or info.st_size > 131072:
    raise SystemExit(1)
if os.path.realpath(path) != str(path):
    raise SystemExit(1)
PY
  then
    printf '%s_evidence=INVALID\n' "${label}" >&2
    return 1
  fi
}

validate_output_path() {
  local output_path="$1"
  if ! python3 - "${output_path}" <<'PY'
import os
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_absolute() or not path.name:
    raise SystemExit(1)
parent = path.parent
try:
    parent_info = parent.lstat()
except OSError:
    raise SystemExit(1)
if not stat.S_ISDIR(parent_info.st_mode) or os.path.realpath(parent) != str(parent):
    raise SystemExit(1)
try:
    info = path.lstat()
except FileNotFoundError:
    info = None
except OSError:
    raise SystemExit(1)
if info is not None and (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)):
    raise SystemExit(1)
PY
  then
    printf 'promotion_evidence_path=UNSAFE\n' >&2
    return 1
  fi
}

validate_input_path "${SUMAI_CANDIDATE_EVIDENCE}" candidate
validate_input_path "${SUMAI_DEVICE_EVIDENCE}" device
if [[ "${apply_mode}" == true ]]; then
  validate_output_path "${promotion_evidence_path}"
fi

project_number=""
if ! project_number="$(gcloud projects describe "${GOOGLE_CLOUD_PROJECT}" \
  --format='value(projectNumber)')"; then
  printf 'project_identity=UNAVAILABLE\n' >&2
  exit 1
fi
if [[ ! "${project_number}" =~ ^[0-9]{6,20}$ ]]; then
  printf 'project_identity=INVALID\n' >&2
  exit 1
fi

tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/sumai-promotion.XXXXXX")"
promotion_lock="$(python3 - <<'PY'
import secrets

print("promote-" + secrets.token_hex(16))
PY
)"
if [[ ! "${promotion_lock}" =~ ^promote-[0-9a-f]{32}$ ]]; then
  printf 'promotion_lock=INVALID\n' >&2
  exit 1
fi
normalized_evidence="${tmp_dir}/normalized-evidence.json"
agent_service_json="${tmp_dir}/agent-service.json"
web_service_json="${tmp_dir}/web-service.json"
agent_candidate_json="${tmp_dir}/agent-candidate.json"
web_candidate_json="${tmp_dir}/web-candidate.json"
agent_predecessor_json="${tmp_dir}/agent-predecessor.json"
web_predecessor_json="${tmp_dir}/web-predecessor.json"
agent_artifact_json="${tmp_dir}/agent-artifact.json"
web_artifact_json="${tmp_dir}/web-artifact.json"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

source_sha=""
build_id=""
agent_digest=""
web_digest=""
agent_ref=""
web_ref=""
agent_candidate_revision=""
web_candidate_revision=""
agent_candidate_url=""
web_candidate_url=""
agent_service_account=""
web_service_account=""
agent_predecessor=""
web_predecessor=""
candidate_tag=""
agent_initial_resource_version=""
web_initial_resource_version=""
agent_claimed_resource_version=""
web_claimed_resource_version=""
agent_post_resource_version=""
web_final_resource_version=""
stable_agent_url=""
final_web_revision=""
final_web_url=""
final_web_tag=""
validation_status="PENDING"
candidate_probe_status="PENDING"
agent_promotion_status="NOT_STARTED"
stable_agent_probe_status="NOT_STARTED"
final_web_deploy_status="NOT_STARTED"
final_web_probe_status="NOT_STARTED"
web_promotion_status="NOT_STARTED"
production_probe_status="NOT_STARTED"
rollback_result="NOT_NEEDED"
agent_rollback_result="NOT_NEEDED"
web_rollback_result="NOT_NEEDED"
agent_claimed=0
web_claimed=0
agent_claim_attempted=0
web_claim_attempted=0
agent_mutation_started=0
web_revision_mutation_started=0
web_mutation_started=0
promotion_succeeded=0
handling_error=0

cleanup() {
  if [[ -n "${tmp_dir:-}" && -d "${tmp_dir}" ]]; then
    rm -rf -- "${tmp_dir}"
  fi
}

json_get() {
  local input_path="$1"
  local dotted_path="$2"
  python3 - "${input_path}" "${dotted_path}" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for part in sys.argv[2].split("."):
    value = value[part]
if not isinstance(value, (str, int)) or isinstance(value, bool):
    raise SystemExit("requested JSON value is not scalar")
print(value)
PY
}

write_promotion_evidence() {
  local output_path="$1"
  local mode_label="dry-run"
  local applied_value="false"
  if [[ "${apply_mode}" == true ]]; then
    mode_label="apply"
  fi
  if [[ "${promotion_succeeded}" -eq 1 ]]; then
    applied_value="true"
  fi
  python3 - \
    "${output_path}" \
    "${source_sha}" \
    "${build_id}" \
    "${agent_predecessor}" \
    "${web_predecessor}" \
    "${agent_candidate_revision}" \
    "${web_candidate_revision}" \
    "${final_web_revision}" \
    "${agent_digest}" \
    "${web_digest}" \
    "${validation_status}" \
    "${candidate_probe_status}" \
    "${agent_promotion_status}" \
    "${stable_agent_probe_status}" \
    "${final_web_deploy_status}" \
    "${final_web_probe_status}" \
    "${web_promotion_status}" \
    "${production_probe_status}" \
    "${started_at}" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "${mode_label}" \
    "${applied_value}" \
    "${rollback_result}" \
    "${agent_rollback_result}" \
    "${web_rollback_result}" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

(
    output_raw,
    source_commit,
    build_id,
    prior_agent,
    prior_web,
    candidate_agent,
    candidate_web,
    final_web,
    agent_digest,
    web_digest,
    validation,
    candidate_probe,
    agent_promotion,
    stable_agent_probe,
    final_web_deploy,
    final_web_probe,
    web_promotion,
    production_probe,
    started_at,
    finished_at,
    mode,
    applied_raw,
    rollback_result,
    agent_rollback_result,
    web_rollback_result,
) = sys.argv[1:]

payload = {
    "schema_version": 1,
    "source_commit": source_commit,
    "build_id": build_id,
    "mode": mode,
    "applied": applied_raw == "true",
    "prior_revisions": {"agent": prior_agent, "web": prior_web},
    "candidate_revisions": {
        "agent": candidate_agent,
        "web": candidate_web,
    },
    "final_revisions": {
        "agent": candidate_agent if applied_raw == "true" else "",
        "web": final_web,
    },
    "digests": {"agent": agent_digest, "web": web_digest},
    "checks": {
        "validation": validation,
        "candidate_probe": candidate_probe,
        "agent_promotion": agent_promotion,
        "stable_agent_probe": stable_agent_probe,
        "final_web_deploy": final_web_deploy,
        "final_web_probe": final_web_probe,
        "web_promotion": web_promotion,
        "production_probe": production_probe,
    },
    "timestamps": {"started_at": started_at, "finished_at": finished_at},
    "rollback_targets": {"agent": prior_agent, "web": prior_web},
    "rollback_result": rollback_result,
    "rollback_results": {
        "agent": agent_rollback_result,
        "web": web_rollback_result,
    },
}

output = Path(output_raw)
descriptor = None
temporary = None
try:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{output.name}.", dir=str(output.parent)
    )
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        descriptor = None
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)
    temporary = None
    os.chmod(output, 0o600)
finally:
    if descriptor is not None:
        os.close(descriptor)
    if temporary is not None:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
PY
}

describe_service() {
  local service_name="$1"
  local destination="$2"
  gcloud run services describe "${service_name}" \
    --project="${GOOGLE_CLOUD_PROJECT}" \
    --region="${region}" \
    --format=json > "${destination}"
}

describe_revision() {
  local revision_name="$1"
  local destination="$2"
  gcloud run revisions describe "${revision_name}" \
    --project="${GOOGLE_CLOUD_PROJECT}" \
    --region="${region}" \
    --format=json > "${destination}"
}

describe_artifact() {
  local immutable_ref="$1"
  local destination="$2"
  gcloud artifacts docker images describe "${immutable_ref}" \
    --project="${GOOGLE_CLOUD_PROJECT}" \
    --format=json > "${destination}"
}

assert_origin_main() {
  local remote_output=""
  local remote_sha=""
  if ! remote_output="$(git ls-remote --exit-code origin refs/heads/main)"; then
    printf 'origin_main=UNAVAILABLE\n' >&2
    return 1
  fi
  if ! remote_sha="$(python3 - "${remote_output}" <<'PY'
import re
import sys

lines = [line for line in sys.argv[1].splitlines() if line.strip()]
if len(lines) != 1:
    raise SystemExit(1)
parts = lines[0].split()
if len(parts) != 2 or parts[1] != "refs/heads/main":
    raise SystemExit(1)
if re.fullmatch(r"[0-9a-f]{40}", parts[0]) is None:
    raise SystemExit(1)
print(parts[0])
PY
  )"; then
    printf 'origin_main=INVALID\n' >&2
    return 1
  fi
  if [[ "${remote_sha}" != "${source_sha}" ]]; then
    printf 'origin_main=DRIFT\n' >&2
    return 1
  fi
}

parse_and_bind_evidence() {
  if ! python3 - \
    "${SUMAI_CANDIDATE_EVIDENCE}" \
    "${SUMAI_DEVICE_EVIDENCE}" \
    "${normalized_evidence}" \
    "${GOOGLE_CLOUD_PROJECT}" \
    "${region}" <<'PY'
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

candidate_path, device_path, output_path, project, region = sys.argv[1:]

def fail(code: str) -> None:
    print(code, file=sys.stderr)
    raise SystemExit(1)

def load(path: str, code: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail(code)
    if not isinstance(value, dict):
        fail(code)
    return value

candidate = load(candidate_path, "candidate_evidence=INVALID")
device = load(device_path, "device_evidence=INVALID")

forbidden_key_parts = {
    "token",
    "authorization",
    "cookie",
    "header",
    "requestbody",
    "responsebody",
    "image",
    "base64",
    "report",
    "action",
    "home",
    "content",
    "payload",
    "email",
}
forbidden_value_patterns = (
    r"(?i)bearer\s+",
    r"(?i)(?:access|refresh|identity)[_-]?token",
    r"(?i)authorization",
    r"(?i)data:image/",
    r"(?i)base64",
    r"(?i)request[_ -]?body",
    r"(?i)response[_ -]?body",
    r"(?i)(?:image|report|action|home)[_ -]?content",
)

def scan(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                fail("sensitive_evidence=REJECTED")
            normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
            if any(part in normalized for part in forbidden_key_parts):
                fail("sensitive_evidence=REJECTED")
            scan(child)
    elif isinstance(value, list):
        for child in value:
            scan(child)
    elif isinstance(value, str):
        if any(re.search(pattern, value) for pattern in forbidden_value_patterns):
            fail("sensitive_evidence=REJECTED")

scan(candidate)
scan(device)

candidate_keys = {
    "schema_version",
    "source_commit",
    "build_id",
    "project_id",
    "region",
    "agent_digest",
    "agent_revision",
    "agent_url",
    "agent_service_account",
    "agent_predecessor_service_account",
    "agent_resource_version_before",
    "agent_resource_version_after",
    "agent_production_before",
    "web_digest",
    "web_revision",
    "web_url",
    "web_service_account",
    "web_predecessor_service_account",
    "web_resource_version_before",
    "web_resource_version_after",
    "web_production_before",
    "production_traffic_changed",
}
device_keys = {
    "schema_version",
    "source_commit",
    "agent_revision",
    "agent_url",
    "app_attest_provider",
    "http_status",
    "observed_at",
    "synthetic_sample_sha256",
}
if set(candidate) != candidate_keys:
    fail("candidate_evidence=INVALID")
if set(device) != device_keys:
    fail("device_evidence=INVALID")
if type(candidate["schema_version"]) is not int or candidate["schema_version"] != 1:
    fail("candidate_evidence=INVALID")
if type(device["schema_version"]) is not int or device["schema_version"] != 1:
    fail("device_evidence=INVALID")
if type(candidate["production_traffic_changed"]) is not bool:
    fail("candidate_evidence=INVALID")
if candidate["production_traffic_changed"] is not False:
    fail("candidate_evidence=INVALID")

candidate_string_keys = candidate_keys - {
    "schema_version",
    "production_traffic_changed",
}
device_string_keys = device_keys - {"schema_version", "http_status"}
if any(type(candidate[key]) is not str for key in candidate_string_keys):
    fail("candidate_evidence=INVALID")
if any(type(device[key]) is not str for key in device_string_keys):
    fail("device_evidence=INVALID")

sha_pattern = re.compile(r"[0-9a-f]{40}")
digest_pattern = re.compile(r"sha256:[0-9a-f]{64}")
revision_pattern = re.compile(r"[a-z][a-z0-9-]{0,62}")
safe_id_pattern = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
account_pattern = re.compile(
    r"[a-z0-9][a-z0-9-]{0,62}@[a-z0-9][a-z0-9.-]{1,200}\.iam\.gserviceaccount\.com"
)
predecessor_account_pattern = re.compile(
    r"(?:[a-z0-9][a-z0-9-]{0,62}@[a-z0-9][a-z0-9.-]{1,200}\.iam\.gserviceaccount\.com|[0-9]+-compute@developer\.gserviceaccount\.com)"
)

if sha_pattern.fullmatch(candidate["source_commit"]) is None:
    fail("candidate_evidence=INVALID")
if safe_id_pattern.fullmatch(candidate["build_id"]) is None:
    fail("candidate_evidence=INVALID")
if candidate["project_id"] != project or candidate["region"] != region:
    fail("candidate_evidence=INVALID")
for key in ("agent_digest", "web_digest"):
    if digest_pattern.fullmatch(candidate[key]) is None:
        fail("candidate_evidence=INVALID")
for key in (
    "agent_revision",
    "web_revision",
    "agent_production_before",
    "web_production_before",
):
    if revision_pattern.fullmatch(candidate[key]) is None:
        fail("candidate_evidence=INVALID")
for key in (
    "agent_resource_version_before",
    "agent_resource_version_after",
    "web_resource_version_before",
    "web_resource_version_after",
):
    if not candidate[key]:
        fail("candidate_evidence=INVALID")
for component in ("agent", "web"):
    before = candidate[f"{component}_resource_version_before"]
    after = candidate[f"{component}_resource_version_after"]
    if after == before:
        fail("candidate_evidence=INVALID")
for key in ("agent_service_account", "web_service_account"):
    if account_pattern.fullmatch(candidate[key]) is None:
        fail("candidate_evidence=INVALID")
for key in (
    "agent_predecessor_service_account",
    "web_predecessor_service_account",
):
    if predecessor_account_pattern.fullmatch(candidate[key]) is None:
        fail("candidate_evidence=INVALID")
if candidate["agent_service_account"] != (
    f"sumai-agent-runtime@{candidate['project_id']}.iam.gserviceaccount.com"
):
    fail("candidate_evidence=INVALID")
if candidate["web_service_account"] != (
    f"sumai-web-runtime@{candidate['project_id']}.iam.gserviceaccount.com"
):
    fail("candidate_evidence=INVALID")

def validate_url(raw: str, code: str) -> None:
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        fail(code)

validate_url(candidate["agent_url"], "candidate_evidence=INVALID")
validate_url(candidate["web_url"], "candidate_evidence=INVALID")
if type(device["http_status"]) is not int or device["http_status"] != 200:
    fail("device_evidence=INVALID")
if device["app_attest_provider"] != "AppAttestProvider":
    fail("device_evidence=INVALID")
if re.fullmatch(r"[0-9a-f]{64}", device["synthetic_sample_sha256"]) is None:
    fail("device_evidence=INVALID")
if not device["observed_at"].endswith("Z"):
    fail("device_evidence=INVALID")
try:
    observed = dt.datetime.fromisoformat(device["observed_at"].replace("Z", "+00:00"))
except ValueError:
    fail("device_evidence=INVALID")
if observed.tzinfo != dt.timezone.utc:
    fail("device_evidence=INVALID")
validate_url(device["agent_url"], "device_evidence=INVALID")
for key in ("source_commit", "agent_revision", "agent_url"):
    if device[key] != candidate[key]:
        fail("evidence_binding=INVALID")

build_token = "".join(
    character
    for character in candidate["build_id"]
    if character in "abcdefghijklmnopqrstuvwxyz0123456789"
)[:4]
if not build_token:
    fail("candidate_evidence=INVALID")
candidate_tag = f"candidate-{candidate['source_commit'][:7]}-{build_token}"
agent_ref = (
    f"{region}-docker.pkg.dev/{project}/apps/sumai-agent@"
    f"{candidate['agent_digest']}"
)
web_ref = (
    f"{region}-docker.pkg.dev/{project}/apps/sumai-web@"
    f"{candidate['web_digest']}"
)
normalized = {
    "candidate": candidate,
    "candidate_tag": candidate_tag,
    "agent_ref": agent_ref,
    "web_ref": web_ref,
    "attestation": {
        "provider": device["app_attest_provider"],
        "status": device["http_status"],
        "observed_at": device["observed_at"],
        "sample_sha256": device["synthetic_sample_sha256"],
    },
}
Path(output_path).write_text(
    json.dumps(normalized, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
  then
    return 1
  fi

  source_sha="$(json_get "${normalized_evidence}" candidate.source_commit)"
  build_id="$(json_get "${normalized_evidence}" candidate.build_id)"
  agent_digest="$(json_get "${normalized_evidence}" candidate.agent_digest)"
  web_digest="$(json_get "${normalized_evidence}" candidate.web_digest)"
  agent_ref="$(json_get "${normalized_evidence}" agent_ref)"
  web_ref="$(json_get "${normalized_evidence}" web_ref)"
  agent_candidate_revision="$(json_get "${normalized_evidence}" candidate.agent_revision)"
  web_candidate_revision="$(json_get "${normalized_evidence}" candidate.web_revision)"
  agent_candidate_url="$(json_get "${normalized_evidence}" candidate.agent_url)"
  web_candidate_url="$(json_get "${normalized_evidence}" candidate.web_url)"
  agent_service_account="$(json_get "${normalized_evidence}" candidate.agent_service_account)"
  web_service_account="$(json_get "${normalized_evidence}" candidate.web_service_account)"
  agent_predecessor="$(json_get "${normalized_evidence}" candidate.agent_production_before)"
  web_predecessor="$(json_get "${normalized_evidence}" candidate.web_production_before)"
  agent_initial_resource_version="$(json_get "${normalized_evidence}" candidate.agent_resource_version_after)"
  web_initial_resource_version="$(json_get "${normalized_evidence}" candidate.web_resource_version_after)"
  candidate_tag="$(json_get "${normalized_evidence}" candidate_tag)"
}

read_initial_state() {
  describe_service "${agent_service}" "${agent_service_json}"
  describe_service "${web_service}" "${web_service_json}"
  describe_revision "${agent_candidate_revision}" "${agent_candidate_json}"
  describe_revision "${web_candidate_revision}" "${web_candidate_json}"
  describe_revision "${agent_predecessor}" "${agent_predecessor_json}"
  describe_revision "${web_predecessor}" "${web_predecessor_json}"
  describe_artifact "${agent_ref}" "${agent_artifact_json}"
  describe_artifact "${web_ref}" "${web_artifact_json}"
}

validate_initial_state() {
  python3 - \
    "${normalized_evidence}" \
    "${agent_service_json}" \
    "${web_service_json}" \
    "${agent_candidate_json}" \
    "${web_candidate_json}" \
    "${agent_predecessor_json}" \
    "${web_predecessor_json}" \
    "${agent_artifact_json}" \
    "${web_artifact_json}" \
    "${project_number}" <<'PY'
import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

(
    evidence_path,
    agent_service_path,
    web_service_path,
    agent_candidate_path,
    web_candidate_path,
    agent_predecessor_path,
    web_predecessor_path,
    agent_artifact_path,
    web_artifact_path,
    project_number,
) = sys.argv[1:]

def load(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        fail("candidate_state=INVALID")
    if not isinstance(value, dict):
        fail("candidate_state=INVALID")
    return value

def fail(code: str) -> None:
    print(code, file=sys.stderr)
    raise SystemExit(1)

evidence = load(evidence_path)
candidate = evidence["candidate"]
tag = evidence["candidate_tag"]
agent_service = load(agent_service_path)
web_service = load(web_service_path)
agent_candidate = load(agent_candidate_path)
web_candidate = load(web_candidate_path)
agent_predecessor = load(agent_predecessor_path)
web_predecessor = load(web_predecessor_path)
agent_artifact = load(agent_artifact_path)
web_artifact = load(web_artifact_path)

def ready(value: dict) -> bool:
    return any(
        row.get("type") == "Ready" and row.get("status") == "True"
        for row in value.get("status", {}).get("conditions", [])
    )

def clean_url(raw: object) -> bool:
    if not isinstance(raw, str):
        return False
    parsed = urlsplit(raw)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and parsed.path in ("", "/")
    )

def production_revision(rows: object) -> str | None:
    if not isinstance(rows, list):
        return None
    matches = [
        row.get("revisionName")
        for row in rows
        if isinstance(row, dict) and row.get("percent") == 100
    ]
    return matches[0] if len(matches) == 1 and isinstance(matches[0], str) else None

def validate_traffic_shape(service: dict) -> None:
    normalized = []
    for location in ("spec", "status"):
        rows = service.get(location, {}).get("traffic", [])
        if not isinstance(rows, list):
            fail("candidate_state=INVALID")
        seen_tags = set()
        identities = []
        positive = []
        for row in rows:
            if not isinstance(row, dict):
                fail("candidate_state=INVALID")
            revision_name = row.get("revisionName")
            percent = row.get("percent", 0)
            tag_value = row.get("tag")
            if not isinstance(revision_name, str) or type(percent) is not int:
                fail("candidate_state=INVALID")
            if percent not in (0, 100):
                fail("candidate_state=INVALID")
            if percent > 0:
                positive.append(revision_name)
            if percent == 0 and not isinstance(tag_value, str):
                fail("candidate_state=INVALID")
            if tag_value is not None:
                if not isinstance(tag_value, str) or not tag_value or tag_value in seen_tags:
                    fail("candidate_state=INVALID")
                seen_tags.add(tag_value)
            identities.append((revision_name, percent, tag_value))
        if len(positive) != 1:
            fail("candidate_state=INVALID")
        normalized.append(sorted(identities, key=repr))
    if normalized[0] != normalized[1]:
        fail("candidate_state=INVALID")

for component, service, expected_rv in (
    ("agent", agent_service, candidate["agent_resource_version_after"]),
    ("web", web_service, candidate["web_resource_version_after"]),
):
    if service.get("metadata", {}).get("resourceVersion") != expected_rv:
        fail("resource_version=DRIFT")

validate_traffic_shape(agent_service)
validate_traffic_shape(web_service)

for component, service, predecessor in (
    ("agent", agent_service, candidate["agent_production_before"]),
    ("web", web_service, candidate["web_production_before"]),
):
    if production_revision(service.get("spec", {}).get("traffic")) != predecessor:
        fail("predecessor=DRIFT")
    if production_revision(service.get("status", {}).get("traffic")) != predecessor:
        fail("predecessor=DRIFT")

def verify_service(
    service: dict,
    name: str,
    revision_name: str,
    revision_url: str,
    revision_value: dict,
) -> None:
    metadata = service.get("metadata", {})
    if (
        metadata.get("name") != name
        or metadata.get("namespace") != project_number
    ):
        fail("candidate_state=INVALID")
    labels = metadata.get("labels", {})
    if (
        labels.get("source-commit") != candidate["source_commit"]
        or labels.get("deployment-lock") != candidate["source_commit"]
    ):
        fail("candidate_state=INVALID")
    if not ready(service) or not clean_url(service.get("status", {}).get("url")):
        fail("candidate_state=INVALID")
    spec_matches = [
        row
        for row in service.get("spec", {}).get("traffic", [])
        if row.get("tag") == tag
    ]
    status_matches = [
        row
        for row in service.get("status", {}).get("traffic", [])
        if row.get("tag") == tag
    ]
    if (
        len(spec_matches) != 1
        or spec_matches[0].get("revisionName") != revision_name
        or spec_matches[0].get("percent", 0) != 0
        or len(status_matches) != 1
        or status_matches[0].get("revisionName") != revision_name
        or status_matches[0].get("percent", 0) != 0
        or status_matches[0].get("url") != revision_url
    ):
        fail("candidate_state=INVALID")
    template_spec = service.get("spec", {}).get("template", {}).get("spec")
    revision_spec = revision_value.get("spec")
    if not isinstance(template_spec, dict) or not isinstance(revision_spec, dict):
        fail("candidate_state=INVALID")
    comparable_revision_spec = copy.deepcopy(revision_spec)
    template_containers = template_spec.get("containers")
    revision_containers = comparable_revision_spec.get("containers")
    if (
        isinstance(template_containers, list)
        and len(template_containers) == 1
        and isinstance(template_containers[0], dict)
        and "name" not in template_containers[0]
        and isinstance(revision_containers, list)
        and len(revision_containers) == 1
        and isinstance(revision_containers[0], dict)
        and isinstance(revision_containers[0].get("name"), str)
        and revision_containers[0]["name"]
    ):
        revision_containers[0].pop("name")
    if template_spec != comparable_revision_spec:
        fail("candidate_state=INVALID")

verify_service(
    agent_service,
    "sumai-agent",
    candidate["agent_revision"],
    candidate["agent_url"],
    agent_candidate,
)
verify_service(
    web_service,
    "sumai-web",
    candidate["web_revision"],
    candidate["web_url"],
    web_candidate,
)

def env_map(revision_value: dict) -> dict[str, dict]:
    containers = revision_value.get("spec", {}).get("containers", [])
    if len(containers) != 1:
        fail("candidate_state=INVALID")
    rows = containers[0].get("env", [])
    if not isinstance(rows, list):
        fail("candidate_state=INVALID")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            fail("candidate_state=INVALID")
        if row["name"] in result:
            fail("candidate_state=INVALID")
        result[row["name"]] = row
    return result

def nonempty_string(value: object) -> bool:
    return type(value) is str and bool(value)

def exact_integer(value: object, minimum: int = 1, maximum: int | None = None) -> bool:
    if type(value) is not int or value < minimum:
        return False
    return maximum is None or value <= maximum

def exact_keys(value: object, allowed: set[str], required: set[str] = set()) -> bool:
    return (
        isinstance(value, dict)
        and set(value).issubset(allowed)
        and required.issubset(value)
        and all(type(key) is str for key in value)
    )

def verify_port(value: object) -> None:
    if not exact_keys(value, {"containerPort", "name", "protocol"}, {"containerPort"}):
        fail("candidate_state=INVALID")
    if not exact_integer(value["containerPort"], 1, 65535):
        fail("candidate_state=INVALID")
    for key in ("name", "protocol"):
        if key in value and not nonempty_string(value[key]):
            fail("candidate_state=INVALID")

def verify_resources(value: object) -> None:
    if not exact_keys(value, {"limits", "requests"}, {"limits"}):
        fail("candidate_state=INVALID")
    supported_resources = {"cpu", "memory", "nvidia.com/gpu"}
    for group in value:
        rows = value[group]
        if (
            not isinstance(rows, dict)
            or not rows
            or not set(rows).issubset(supported_resources)
            or any(not nonempty_string(item) for item in rows.values())
        ):
            fail("candidate_state=INVALID")

def verify_http_get(value: object) -> None:
    if not exact_keys(value, {"path", "port", "scheme", "httpHeaders"}, {"path", "port"}):
        fail("candidate_state=INVALID")
    if type(value["path"]) is not str or not exact_integer(value["port"], 1, 65535):
        fail("candidate_state=INVALID")
    if "scheme" in value and not nonempty_string(value["scheme"]):
        fail("candidate_state=INVALID")
    if "httpHeaders" in value:
        headers = value["httpHeaders"]
        if not isinstance(headers, list):
            fail("candidate_state=INVALID")
        for header in headers:
            if (
                not exact_keys(header, {"name", "value"}, {"name", "value"})
                or not nonempty_string(header["name"])
                or type(header["value"]) is not str
            ):
                fail("candidate_state=INVALID")

def verify_probe(value: object) -> None:
    handler_keys = {"httpGet", "tcpSocket", "grpc"}
    timing_keys = {
        "initialDelaySeconds",
        "timeoutSeconds",
        "periodSeconds",
        "successThreshold",
        "failureThreshold",
    }
    if not exact_keys(value, handler_keys | timing_keys):
        fail("candidate_state=INVALID")
    handlers = set(value) & handler_keys
    if len(handlers) != 1:
        fail("candidate_state=INVALID")
    for key in timing_keys:
        if key in value:
            minimum = 0 if key == "initialDelaySeconds" else 1
            if not exact_integer(value[key], minimum):
                fail("candidate_state=INVALID")
    handler = handlers.pop()
    if handler == "httpGet":
        verify_http_get(value[handler])
    elif handler == "tcpSocket":
        socket = value[handler]
        if (
            not exact_keys(socket, {"port"}, {"port"})
            or not exact_integer(socket["port"], 1, 65535)
        ):
            fail("candidate_state=INVALID")
    else:
        grpc = value[handler]
        if (
            not exact_keys(grpc, {"port", "service"}, {"port"})
            or not exact_integer(grpc["port"], 1, 65535)
            or ("service" in grpc and type(grpc["service"]) is not str)
        ):
            fail("candidate_state=INVALID")

def verify_volumes(value: object) -> set[str]:
    if not isinstance(value, list):
        fail("candidate_state=INVALID")
    source_keys = {"emptyDir", "secret", "cloudSqlInstance", "nfs"}
    names: set[str] = set()
    for volume in value:
        if not exact_keys(volume, {"name"} | source_keys, {"name"}):
            fail("candidate_state=INVALID")
        name = volume["name"]
        if not nonempty_string(name) or name in names:
            fail("candidate_state=INVALID")
        names.add(name)
        sources = set(volume) & source_keys
        if len(sources) != 1:
            fail("candidate_state=INVALID")
        source = sources.pop()
        source_value = volume[source]
        if source == "emptyDir":
            if not exact_keys(source_value, {"medium", "sizeLimit"}) or any(
                type(item) is not str for item in source_value.values()
            ):
                fail("candidate_state=INVALID")
        elif source == "secret":
            if not exact_keys(
                source_value,
                {"secretName", "items", "defaultMode"},
                {"secretName"},
            ) or not nonempty_string(source_value["secretName"]):
                fail("candidate_state=INVALID")
            if "defaultMode" in source_value and not exact_integer(
                source_value["defaultMode"], 0, 511
            ):
                fail("candidate_state=INVALID")
            if "items" in source_value:
                items = source_value["items"]
                if not isinstance(items, list):
                    fail("candidate_state=INVALID")
                for item in items:
                    if (
                        not exact_keys(item, {"key", "path", "mode"}, {"key", "path"})
                        or not nonempty_string(item["key"])
                        or not nonempty_string(item["path"])
                        or (
                            "mode" in item
                            and not exact_integer(item["mode"], 0, 511)
                        )
                    ):
                        fail("candidate_state=INVALID")
        elif source == "cloudSqlInstance":
            if not exact_keys(source_value, {"instances"}, {"instances"}):
                fail("candidate_state=INVALID")
            instances = source_value["instances"]
            if (
                not isinstance(instances, list)
                or not instances
                or any(not nonempty_string(item) for item in instances)
            ):
                fail("candidate_state=INVALID")
        else:
            if not exact_keys(
                source_value, {"server", "path", "readOnly"}, {"server", "path"}
            ):
                fail("candidate_state=INVALID")
            if not nonempty_string(source_value["server"]) or not nonempty_string(
                source_value["path"]
            ):
                fail("candidate_state=INVALID")
            if "readOnly" in source_value and type(source_value["readOnly"]) is not bool:
                fail("candidate_state=INVALID")
    return names

def verify_volume_mounts(value: object, volume_names: set[str]) -> None:
    if not isinstance(value, list):
        fail("candidate_state=INVALID")
    mount_paths: set[str] = set()
    for mount in value:
        if not exact_keys(
            mount,
            {"name", "mountPath", "readOnly", "subPath"},
            {"name", "mountPath"},
        ):
            fail("candidate_state=INVALID")
        if (
            not nonempty_string(mount["name"])
            or mount["name"] not in volume_names
            or not nonempty_string(mount["mountPath"])
            or mount["mountPath"] in mount_paths
            or ("readOnly" in mount and type(mount["readOnly"]) is not bool)
            or ("subPath" in mount and type(mount["subPath"]) is not str)
        ):
            fail("candidate_state=INVALID")
        mount_paths.add(mount["mountPath"])

def verify_runtime_spec(spec: object) -> dict:
    if not exact_keys(
        spec,
        {
            "serviceAccountName",
            "timeoutSeconds",
            "containerConcurrency",
            "containers",
            "volumes",
        },
        {
            "serviceAccountName",
            "timeoutSeconds",
            "containerConcurrency",
            "containers",
        },
    ):
        fail("candidate_state=INVALID")
    if (
        not nonempty_string(spec["serviceAccountName"])
        or not exact_integer(spec["timeoutSeconds"])
        or not exact_integer(spec["containerConcurrency"])
        or not isinstance(spec["containers"], list)
        or len(spec["containers"]) != 1
    ):
        fail("candidate_state=INVALID")
    volume_names = verify_volumes(spec.get("volumes", []))
    container = spec["containers"][0]
    if not exact_keys(
        container,
        {
            "name",
            "image",
            "command",
            "args",
            "ports",
            "resources",
            "env",
            "volumeMounts",
            "startupProbe",
            "livenessProbe",
        },
        {"image", "ports", "resources", "env"},
    ):
        fail("candidate_state=INVALID")
    if not nonempty_string(container["image"]):
        fail("candidate_state=INVALID")
    if "name" in container and (
        type(container["name"]) is not str
        or re.fullmatch(
            r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?",
            container["name"],
        )
        is None
    ):
        fail("candidate_state=INVALID")
    for key in ("command", "args"):
        if key in container and (
            not isinstance(container[key], list)
            or any(type(item) is not str for item in container[key])
        ):
            fail("candidate_state=INVALID")
    ports = container["ports"]
    if not isinstance(ports, list) or len(ports) != 1:
        fail("candidate_state=INVALID")
    verify_port(ports[0])
    verify_resources(container["resources"])
    if not isinstance(container["env"], list):
        fail("candidate_state=INVALID")
    for key in ("startupProbe", "livenessProbe"):
        if key in container:
            verify_probe(container[key])
    if "volumeMounts" in container:
        verify_volume_mounts(container["volumeMounts"], volume_names)
    return container

def verify_revision(
    value: dict,
    name: str,
    image_ref: str,
    account: str,
    component: str,
) -> None:
    if value.get("metadata", {}).get("name") != name or not ready(value):
        fail("candidate_state=INVALID")
    spec = value.get("spec", {})
    container = verify_runtime_spec(spec)
    if (
        spec.get("serviceAccountName") != account
        or container.get("image") != image_ref
        or value.get("status", {}).get("imageDigest") != image_ref
    ):
        fail("candidate_state=INVALID")
    annotations = value.get("metadata", {}).get("annotations", {})
    if (
        not isinstance(annotations, dict)
        or any(type(key) is not str or type(item) is not str for key, item in annotations.items())
    ):
        fail("candidate_state=INVALID")
    env = env_map(value)
    for env_name, row in env.items():
        if component == "agent" and env_name == "GEMINI_API_KEY":
            if set(row) != {"name", "valueFrom"}:
                fail("candidate_state=INVALID")
            value_from = row.get("valueFrom")
            if not isinstance(value_from, dict) or set(value_from) != {"secretKeyRef"}:
                fail("candidate_state=INVALID")
            secret_ref = value_from.get("secretKeyRef")
            if (
                not isinstance(secret_ref, dict)
                or set(secret_ref) != {"name", "key"}
                or any(type(secret_ref.get(key)) is not str for key in ("name", "key"))
            ):
                fail("candidate_state=INVALID")
        elif (
            set(row) != {"name", "value"}
            or type(row.get("name")) is not str
            or type(row.get("value")) is not str
        ):
            fail("candidate_state=INVALID")
    if component == "agent":
        expected = {
            "MOCK_MODE": "false",
            "REQUIRE_REAL_GEMINI": "true",
            "APP_CHECK_REQUIRED": "true",
            "GEMINI_MODEL": "gemini-2.5-flash",
            "LOG_LEVEL": "INFO",
        }
        if set(env) != set(expected) | {"FIREBASE_APP_ID", "GEMINI_API_KEY"}:
            fail("candidate_state=INVALID")
        if any(env.get(key, {}).get("value") != value for key, value in expected.items()):
            fail("candidate_state=INVALID")
        firebase_app_id = env.get("FIREBASE_APP_ID", {}).get("value")
        if not isinstance(firebase_app_id, str) or re.fullmatch(
            r"1:[0-9]+:ios:[0-9a-f]+", firebase_app_id
        ) is None:
            fail("candidate_state=INVALID")
        secret_ref = env["GEMINI_API_KEY"]["valueFrom"]["secretKeyRef"]
        if secret_ref != {"name": "sumai-gemini-api-key", "key": "2"}:
            fail("candidate_state=INVALID")
    else:
        expected = {
            "SUMAI_AGENT_URL": candidate["agent_url"],
            "SUMAI_WEB_PORT": "8080",
            "MOCK_MODE": "false",
            "REQUIRE_REAL_GEMINI": "true",
            "PUBLIC_WEB_ANALYSIS_ENABLED": "false",
            "LOG_LEVEL": "INFO",
        }
        if set(env) != set(expected):
            fail("candidate_state=INVALID")
        if any(env.get(key, {}).get("value") != value for key, value in expected.items()):
            fail("candidate_state=INVALID")

verify_revision(
    agent_candidate,
    candidate["agent_revision"],
    evidence["agent_ref"],
    candidate["agent_service_account"],
    "agent",
)
verify_revision(
    web_candidate,
    candidate["web_revision"],
    evidence["web_ref"],
    candidate["web_service_account"],
    "web",
)
if agent_predecessor.get("spec", {}).get("serviceAccountName") != candidate["agent_predecessor_service_account"]:
    fail("candidate_state=INVALID")
if web_predecessor.get("spec", {}).get("serviceAccountName") != candidate["web_predecessor_service_account"]:
    fail("candidate_state=INVALID")

def artifact_digest(value: dict) -> object:
    return value.get("image_summary", {}).get("digest", value.get("digest"))

if artifact_digest(agent_artifact) != candidate["agent_digest"]:
    fail("candidate_state=INVALID")
if artifact_digest(web_artifact) != candidate["web_digest"]:
    fail("candidate_state=INVALID")
PY
}

probe_json_endpoint() {
  local base_url="$1"
  local endpoint="$2"
  local label="$3"
  local output_file="${tmp_dir}/${label}.json"
  local status_code=""
  if ! status_code="$(curl --fail --silent --show-error \
    --retry 3 --retry-all-errors --retry-delay 1 \
    --output "${output_file}" \
    --write-out '%{http_code}' \
    "${base_url}${endpoint}")"; then
    printf 'probe=FAILED\n' >&2
    return 1
  fi
  if [[ "${status_code}" != 200 ]]; then
    printf 'probe=FAILED\n' >&2
    return 1
  fi
  if ! python3 - "${output_file}" <<'PY'
import json
import sys
from pathlib import Path

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit(1)
if not isinstance(payload, dict) or payload.get("status") not in {"ok", "ready"}:
    raise SystemExit(1)
PY
  then
    printf 'probe=FAILED\n' >&2
    return 1
  fi
}

probe_html_endpoint() {
  local base_url="$1"
  local endpoint="$2"
  local label="$3"
  local require_no_store="$4"
  local output_file="${tmp_dir}/${label}.html"
  local header_file="${tmp_dir}/${label}.headers"
  local status_code=""
  if ! status_code="$(curl --fail --silent --show-error \
    --retry 3 --retry-all-errors --retry-delay 1 \
    --dump-header "${header_file}" \
    --output "${output_file}" \
    --write-out '%{http_code}' \
    "${base_url}${endpoint}")"; then
    printf 'probe=FAILED\n' >&2
    return 1
  fi
  if [[ "${status_code}" != 200 || ! -s "${output_file}" ]]; then
    printf 'probe=FAILED\n' >&2
    return 1
  fi
  if [[ "${require_no_store}" == true ]]; then
    if ! python3 - "${header_file}" <<'PY'
import sys
from pathlib import Path

try:
    text = Path(sys.argv[1]).read_text(encoding="iso-8859-1")
except OSError:
    raise SystemExit(1)
values = [
    line.partition(":")[2].strip().casefold()
    for line in text.splitlines()
    if line.partition(":")[0].strip().casefold() == "cache-control"
]
if not values or "no-store" not in values[-1]:
    raise SystemExit(1)
PY
    then
      printf 'probe=FAILED\n' >&2
      return 1
    fi
  fi
}

probe_agent() {
  local base_url="$1"
  local prefix="$2"
  probe_json_endpoint "${base_url}" /health "${prefix}-health"
  probe_json_endpoint "${base_url}" /ready "${prefix}-ready"
}

probe_web() {
  local base_url="$1"
  local prefix="$2"
  probe_html_endpoint "${base_url}" / "${prefix}-home" false
  probe_json_endpoint "${base_url}" /ready "${prefix}-ready"
  probe_html_endpoint "${base_url}" /privacy "${prefix}-privacy" true
  probe_html_endpoint "${base_url}" /support "${prefix}-support" true
}

make_lock_payload() {
  local service_path="$1"
  local output_path="$2"
  local expected_lock="$3"
  local new_lock="$4"
  python3 - "${service_path}" "${output_path}" "${expected_lock}" "${new_lock}" <<'PY'
import copy
import json
import re
import sys
from pathlib import Path

service_path, output_path, expected_lock, new_lock = sys.argv[1:]
service = json.loads(Path(service_path).read_text(encoding="utf-8"))
metadata = service.get("metadata", {})
resource_version = metadata.get("resourceVersion")
labels = metadata.get("labels")
if not isinstance(resource_version, str) or not resource_version:
    raise SystemExit("conditional replacement resourceVersion is invalid")
if not isinstance(labels, dict) or labels.get("deployment-lock") != expected_lock:
    raise SystemExit("deployment lock changed before claim")
labels = copy.deepcopy(labels)
labels["deployment-lock"] = new_lock
payload = {
    "apiVersion": service.get("apiVersion"),
    "kind": service.get("kind"),
    "metadata": {
        "name": metadata.get("name"),
        "namespace": metadata.get("namespace"),
        "labels": labels,
        "annotations": copy.deepcopy(metadata.get("annotations", {})),
        "resourceVersion": resource_version,
    },
    "spec": copy.deepcopy(service.get("spec", {})),
}
Path(output_path).write_text(
    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
}

verify_lock_claim() {
  local before_path="$1"
  local after_path="$2"
  local expected_old_lock="$3"
  local expected_new_lock="$4"
  python3 - \
    "${before_path}" \
    "${after_path}" \
    "${expected_old_lock}" \
    "${expected_new_lock}" <<'PY'
import copy
import json
import re
import sys
from pathlib import Path

before_path, after_path, expected_old_lock, expected_new_lock = sys.argv[1:]
before = json.loads(Path(before_path).read_text(encoding="utf-8"))
after = json.loads(Path(after_path).read_text(encoding="utf-8"))
before_meta = before.get("metadata", {})
after_meta = after.get("metadata", {})
before_rv = before_meta.get("resourceVersion")
after_rv = after_meta.get("resourceVersion")
if (
    not isinstance(before_rv, str)
    or not isinstance(after_rv, str)
    or not before_rv
    or not after_rv
    or after_rv == before_rv
):
    raise SystemExit("claim resourceVersion did not advance")
before_labels = copy.deepcopy(before_meta.get("labels", {}))
after_labels = copy.deepcopy(after_meta.get("labels", {}))
if before_labels.get("deployment-lock") != expected_old_lock:
    raise SystemExit("claim started from an unexpected lock")
before_labels["deployment-lock"] = expected_new_lock
if after_labels != before_labels:
    raise SystemExit("claim changed labels other than deployment-lock")
for key in ("name", "namespace"):
    if after_meta.get(key) != before_meta.get(key):
        raise SystemExit("claim changed service metadata")
before_annotations = copy.deepcopy(before_meta.get("annotations", {}))
after_annotations = copy.deepcopy(after_meta.get("annotations", {}))
if not isinstance(before_annotations, dict) or not isinstance(after_annotations, dict):
    raise SystemExit("claim changed service metadata")
managed_annotations = {
    "run.googleapis.com/operation-id",
    "serving.knative.dev/lastModifier",
}
for key in managed_annotations:
    if (key in before_annotations) != (key in after_annotations):
        raise SystemExit("claim changed service metadata")
    if key in before_annotations and (
        not isinstance(before_annotations[key], str)
        or not before_annotations[key]
        or not isinstance(after_annotations[key], str)
        or not after_annotations[key]
    ):
        raise SystemExit("claim changed service metadata")
    before_annotations.pop(key, None)
    after_annotations.pop(key, None)
if before_annotations != after_annotations:
    raise SystemExit("claim changed service metadata")
if after.get("apiVersion") != before.get("apiVersion") or after.get("kind") != before.get("kind"):
    raise SystemExit("claim changed service identity")
if after.get("spec") != before.get("spec"):
    raise SystemExit("claim changed service spec")
PY
}

verify_service_snapshot() {
  local expected_path="$1"
  local current_path="$2"
  python3 - "${expected_path}" "${current_path}" <<'PY'
import json
import sys
from pathlib import Path

expected = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
current = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
for key in ("apiVersion", "kind", "spec"):
    if current.get(key) != expected.get(key):
        raise SystemExit("service changed before ownership claim")
for key in ("name", "namespace", "labels", "annotations", "resourceVersion"):
    if current.get("metadata", {}).get(key) != expected.get("metadata", {}).get(key):
        raise SystemExit("service metadata changed before ownership claim")
for key in ("url", "traffic"):
    if current.get("status", {}).get(key) != expected.get("status", {}).get(key):
        raise SystemExit("service status changed before ownership claim")
PY
}

validate_owned_services() {
  local agent_path="$1"
  local web_path="$2"
  local expected_agent_rv="$3"
  local expected_web_rv="$4"
  local expected_agent_production="$5"
  local expected_web_production="$6"
  local expected_agent_candidate_percent="$7"
  python3 - \
    "${agent_path}" "${web_path}" \
    "${source_sha}" "${promotion_lock}" \
    "${expected_agent_rv}" "${expected_web_rv}" \
    "${expected_agent_production}" "${expected_web_production}" \
    "${agent_candidate_revision}" "${web_candidate_revision}" \
    "${candidate_tag}" "${expected_agent_candidate_percent}" <<'PY'
import json
import sys
from pathlib import Path

(
    agent_path,
    web_path,
    source_sha,
    promotion_lock,
    expected_agent_rv,
    expected_web_rv,
    expected_agent_production,
    expected_web_production,
    agent_candidate,
    web_candidate,
    candidate_tag,
    expected_agent_candidate_percent,
) = sys.argv[1:]

def validate(path, expected_rv, expected_production, candidate, candidate_percent):
    service = json.loads(Path(path).read_text(encoding="utf-8"))
    metadata = service.get("metadata", {})
    labels = metadata.get("labels", {})
    if metadata.get("resourceVersion") != expected_rv:
        raise SystemExit("owned service resourceVersion changed")
    if labels.get("source-commit") != source_sha or labels.get("deployment-lock") != promotion_lock:
        raise SystemExit("owned service lock changed")
    identities = []
    for location in ("spec", "status"):
        rows = service.get(location, {}).get("traffic", [])
        seen_tags = set()
        values = []
        for row in rows:
            percent = row.get("percent", 0)
            tag = row.get("tag")
            if percent not in (0, 100) or (percent == 0 and not tag):
                raise SystemExit("owned service traffic is invalid")
            if tag:
                if not isinstance(tag, str) or tag in seen_tags:
                    raise SystemExit("owned service traffic tag is invalid")
                seen_tags.add(tag)
            values.append((tag or "", row.get("revisionName"), percent))
        production = [value[1] for value in values if value[2] == 100]
        if production != [expected_production]:
            raise SystemExit("owned service production changed")
        tagged = [value for value in values if value[0] == candidate_tag]
        if tagged != [(candidate_tag, candidate, int(candidate_percent))]:
            raise SystemExit("owned candidate tag changed")
        identities.append(sorted(values))
    if identities[0] != identities[1]:
        raise SystemExit("owned service traffic readback differs")

validate(agent_path, expected_agent_rv, expected_agent_production, agent_candidate, expected_agent_candidate_percent)
validate(web_path, expected_web_rv, expected_web_production, web_candidate, "0")
PY
}

claim_services() {
  local agent_before="${tmp_dir}/agent-before-claim.json"
  local web_before="${tmp_dir}/web-before-claim.json"
  local agent_payload="${tmp_dir}/agent-claim-payload.json"
  local web_payload="${tmp_dir}/web-claim-payload.json"
  local response="${tmp_dir}/claim-response.json"

  describe_service "${agent_service}" "${agent_before}"
  describe_service "${web_service}" "${web_before}"
  verify_service_snapshot "${agent_service_json}" "${agent_before}"
  verify_service_snapshot "${web_service_json}" "${web_before}"

  make_lock_payload "${agent_before}" "${agent_payload}" "${source_sha}" "${promotion_lock}"
  agent_claim_attempted=1
  conditional_put "${agent_payload}" "${response}"
  agent_claimed=1
  describe_service "${agent_service}" "${agent_service_json}"
  verify_lock_claim "${agent_before}" "${agent_service_json}" "${source_sha}" "${promotion_lock}"
  agent_claimed_resource_version="$(json_get "${agent_service_json}" metadata.resourceVersion)"

  make_lock_payload "${web_before}" "${web_payload}" "${source_sha}" "${promotion_lock}"
  web_claim_attempted=1
  conditional_put "${web_payload}" "${response}"
  web_claimed=1
  describe_service "${web_service}" "${web_service_json}"
  verify_lock_claim "${web_before}" "${web_service_json}" "${source_sha}" "${promotion_lock}"
  web_claimed_resource_version="$(json_get "${web_service_json}" metadata.resourceVersion)"
}

restore_claims() {
  local service_path=""
  local payload_path=""
  local response_path="${tmp_dir}/claim-restore-response.json"
  local current_lock=""
  local restore_failed=0
  local service_name=""
  local previous_resource_version=""
  local restore_changes_traffic=0

  for service_name in "${web_service}" "${agent_service}"; do
    if [[ "${service_name}" == "${web_service}" && "${web_claimed}" -ne 1 && "${web_claim_attempted}" -ne 1 ]]; then
      continue
    fi
    if [[ "${service_name}" == "${agent_service}" && "${agent_claimed}" -ne 1 && "${agent_claim_attempted}" -ne 1 ]]; then
      continue
    fi
    service_path="${tmp_dir}/${service_name}-claim-restore-current.json"
    payload_path="${tmp_dir}/${service_name}-claim-restore-payload.json"
    if ! describe_service "${service_name}" "${service_path}"; then
      restore_failed=1
      continue
    fi
    current_lock="$(python3 - "${service_path}" <<'PY'
import json
import sys
from pathlib import Path
print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).get("metadata", {}).get("labels", {}).get("deployment-lock", ""))
PY
)"
    if [[ "${current_lock}" != "${promotion_lock}" ]]; then
      if [[ "${service_name}" == "${web_service}" && "${web_claimed}" -eq 1 ]]; then
        restore_failed=1
      elif [[ "${service_name}" == "${agent_service}" && "${agent_claimed}" -eq 1 ]]; then
        restore_failed=1
      fi
      continue
    fi
    if ! make_lock_payload "${service_path}" "${payload_path}" "${promotion_lock}" "${source_sha}"; then
      restore_failed=1
      continue
    fi
    previous_resource_version="$(json_get "${service_path}" metadata.resourceVersion)"
    restore_changes_traffic=0
    if traffic_changed_between "${service_path}" "${payload_path}"; then
      restore_changes_traffic=1
    fi
    if ! conditional_put "${payload_path}" "${response_path}"; then
      restore_failed=1
      continue
    fi
    if [[ "${restore_changes_traffic}" -eq 1 ]] \
      && ! wait_for_traffic_convergence \
        "${service_name}" \
        "${service_path}" \
        "${payload_path}" \
        "${previous_resource_version}" \
        "${source_sha}" \
        "${promotion_lock}"; then
      restore_failed=1
    fi
  done
  if [[ "${restore_failed}" -ne 0 ]]; then
    rollback_result="REFUSED"
    printf 'claim_restore=REFUSED\n' >&2
    return 1
  fi
  rollback_result="PASS"
  printf 'claim_restore=PASS\n' >&2
}

make_promotion_payload() {
  local service_path="$1"
  local output_path="$2"
  local target_revision="$3"
  local target_tag="$4"
  local keep_zero_tag="$5"
  python3 - \
    "${service_path}" \
    "${output_path}" \
    "${target_revision}" \
    "${target_tag}" \
    "${keep_zero_tag}" \
    "${source_sha}" \
    "${promotion_lock}" <<'PY'
import copy
import json
import sys
from pathlib import Path

service_path, output_path, target_revision, target_tag, _keep_zero_tag, source_sha, promotion_lock = sys.argv[1:]
service = json.loads(Path(service_path).read_text(encoding="utf-8"))
metadata = service.get("metadata", {})
resource_version = metadata.get("resourceVersion")
if not isinstance(resource_version, str) or not resource_version:
    raise SystemExit("conditional replacement resourceVersion is missing")
labels = metadata.get("labels", {})
if labels.get("source-commit") != source_sha or labels.get("deployment-lock") != promotion_lock:
    raise SystemExit("conditional replacement ownership changed")
spec = copy.deepcopy(service.get("spec", {}))
source_traffic = spec.get("traffic", [])
if not isinstance(source_traffic, list):
    raise SystemExit("service traffic is invalid")
positive = [row for row in source_traffic if row.get("percent", 0) == 100]
if len(positive) != 1 or any(row.get("percent", 0) not in (0, 100) for row in source_traffic):
    raise SystemExit("service traffic has an unexpected positive target")
traffic = []
target_count = 0
seen_tags = set()
for source_row in source_traffic:
    tag = source_row.get("tag")
    if tag is None:
        if source_row.get("percent", 0) != 100:
            raise SystemExit("untagged zero traffic target is unsafe")
        continue
    if not isinstance(tag, str) or not tag or tag in seen_tags:
        raise SystemExit("service traffic tag is invalid")
    seen_tags.add(tag)
    row = copy.deepcopy(source_row)
    if tag == target_tag:
        if row.get("revisionName") != target_revision:
            raise SystemExit("promotion tag identity changed")
        row["percent"] = 100
        target_count += 1
    else:
        row["percent"] = 0
    traffic.append(row)
if target_count != 1:
    raise SystemExit("promotion tag did not resolve exactly once")
spec["traffic"] = traffic
payload = {
    "apiVersion": service.get("apiVersion"),
    "kind": service.get("kind"),
    "metadata": {
        "name": metadata.get("name"),
        "namespace": metadata.get("namespace"),
        "labels": copy.deepcopy(metadata.get("labels", {})),
        "annotations": copy.deepcopy(metadata.get("annotations", {})),
        "resourceVersion": resource_version,
    },
    "spec": spec,
}
Path(output_path).write_text(
    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
}

conditional_put() {
  local payload_path="$1"
  local response_path="$2"
  local service_name=""
  local access_token=""
  local auth_config=""
  local request_url=""
  local status_code=""

  if ! service_name="$(python3 - \
    "${payload_path}" \
    "${project_number}" \
    "${agent_service}" \
    "${web_service}" <<'PY'
import json
import re
import sys
from pathlib import Path

payload_path, project_number, agent_service, web_service = sys.argv[1:]
try:
    payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
metadata = payload.get("metadata", {})
name = metadata.get("name")
if (
    name not in {agent_service, web_service}
    or metadata.get("namespace") != project_number
    or not isinstance(metadata.get("resourceVersion"), str)
    or not metadata["resourceVersion"]
):
    raise SystemExit(1)
print(name)
PY
  )"; then
    printf 'cloud_run_api_payload=INVALID\n' >&2
    return 1
  fi

  if ! access_token="$(
    gcloud auth print-access-token \
      --project="${GOOGLE_CLOUD_PROJECT}" 2>/dev/null
  )" \
    || (( ${#access_token} < 20 || ${#access_token} > 4096 )) \
    || [[ ! "${access_token}" =~ ^[A-Za-z0-9._~+/=-]+$ ]]; then
    access_token=""
    printf 'cloud_run_api_auth=FAILED\n' >&2
    return 1
  fi
  auth_config="$(mktemp "${tmp_dir}/curl-auth.XXXXXX")"
  chmod 0600 "${auth_config}"
  printf 'header = "Authorization: Bearer %s"\n' "${access_token}" > "${auth_config}"
  access_token=""

  : > "${response_path}"
  chmod 0600 "${response_path}"
  request_url="https://${region}-run.googleapis.com/apis/serving.knative.dev/v1/namespaces/${GOOGLE_CLOUD_PROJECT}/services/${service_name}"
  if ! status_code="$(curl \
    --silent \
    --show-error \
    --connect-timeout 10 \
    --max-time 120 \
    --config "${auth_config}" \
    --request PUT \
    --header 'Content-Type: application/json' \
    --data-binary "@${payload_path}" \
    --output "${response_path}" \
    --write-out '%{http_code}' \
    "${request_url}")"; then
    rm -f -- "${auth_config}"
    printf 'cloud_run_api=UNAVAILABLE\n' >&2
    return 1
  fi
  rm -f -- "${auth_config}"
  case "${status_code}" in
    200) return 0 ;;
    409|412)
      printf 'cloud_run_api=CONFLICT\n' >&2
      return 1
      ;;
    *)
      printf 'cloud_run_api=FAILED\n' >&2
      return 1
      ;;
  esac
}

wait_for_traffic_convergence() {
  local service_name="$1"
  local service_path="$2"
  local expected_payload_path="$3"
  local previous_resource_version="$4"
  local expected_lock="$5"
  local previous_lock="$6"
  local attempt=0
  local convergence_state=""

  for (( attempt = 1; attempt <= traffic_convergence_attempts; attempt += 1 )); do
    if describe_service "${service_name}" "${service_path}" 2>/dev/null; then
      if ! convergence_state="$(python3 - \
        "${service_path}" \
        "${expected_payload_path}" \
        "${service_name}" \
        "${project_number}" \
        "${source_sha}" \
        "${previous_resource_version}" \
        "${expected_lock}" \
        "${previous_lock}" <<'PY'
import json
import sys
from pathlib import Path

(
    service_path,
    expected_path,
    service_name,
    project_number,
    source_sha,
    previous_rv,
    expected_lock,
    previous_lock,
) = sys.argv[1:]

try:
    service = json.loads(Path(service_path).read_text(encoding="utf-8"))
    expected = json.loads(Path(expected_path).read_text(encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)

def metadata_identity(value):
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        return None
    return (
        value.get("apiVersion"),
        value.get("kind"),
        metadata.get("name"),
        metadata.get("namespace"),
    )

expected_identity = metadata_identity(expected)
current_identity = metadata_identity(service)
required_identity = (
    "serving.knative.dev/v1",
    "Service",
    service_name,
    project_number,
)
if expected_identity != required_identity or current_identity != required_identity:
    print("INVALID")
    raise SystemExit(0)

expected_metadata = expected["metadata"]
current_metadata = service["metadata"]
expected_labels = expected_metadata.get("labels")
current_labels = current_metadata.get("labels")
if not isinstance(expected_labels, dict) or not isinstance(current_labels, dict):
    print("INVALID")
    raise SystemExit(0)
if (
    expected_labels.get("source-commit") != source_sha
    or expected_labels.get("deployment-lock") != expected_lock
):
    print("INVALID")
    raise SystemExit(0)
if current_labels.get("source-commit") != source_sha:
    print("OWNERSHIP_CHANGED")
    raise SystemExit(0)

current_rv = current_metadata.get("resourceVersion")
if (
    not isinstance(previous_rv, str)
    or not previous_rv
    or not isinstance(current_rv, str)
    or not current_rv
):
    print("INVALID")
    raise SystemExit(0)
current_lock = current_labels.get("deployment-lock")
if current_lock != expected_lock:
    if current_lock == previous_lock and current_rv == previous_rv:
        print("PENDING")
    else:
        print("OWNERSHIP_CHANGED")
    raise SystemExit(0)

def normalized_traffic(value, location):
    parent = value.get(location)
    if not isinstance(parent, dict):
        return None
    rows = parent.get("traffic")
    if not isinstance(rows, list) or not rows:
        return None
    result = []
    seen_tags = set()
    for row in rows:
        if not isinstance(row, dict):
            return None
        revision = row.get("revisionName")
        percent = row.get("percent", 0)
        tag = row.get("tag")
        if (
            not isinstance(revision, str)
            or not revision
            or type(percent) is not int
            or percent not in (0, 100)
            or (tag is not None and (not isinstance(tag, str) or not tag))
            or (tag is not None and tag in seen_tags)
            or (percent == 0 and tag is None)
        ):
            return None
        if tag is not None:
            seen_tags.add(tag)
        result.append((tag or "", revision, percent))
    if len([row for row in result if row[2] == 100]) != 1:
        return None
    return sorted(result)

expected_traffic = normalized_traffic(expected, "spec")
spec_traffic = normalized_traffic(service, "spec")
status_traffic = normalized_traffic(service, "status")
if expected_traffic is None:
    print("INVALID")
    raise SystemExit(0)

conditions = service.get("status", {}).get("conditions")
ready = isinstance(conditions, list) and any(
    isinstance(row, dict)
    and row.get("type") == "Ready"
    and row.get("status") == "True"
    for row in conditions
)
if (
    current_rv != previous_rv
    and spec_traffic == expected_traffic
    and status_traffic == expected_traffic
    and ready
):
    print("CONVERGED")
else:
    print("PENDING")
PY
      )"; then
        printf 'traffic_convergence=INVALID\n' >&2
        return 1
      fi
      case "${convergence_state}" in
        CONVERGED) return 0 ;;
        PENDING) ;;
        OWNERSHIP_CHANGED)
          printf 'traffic_convergence=OWNERSHIP_CHANGED\n' >&2
          return 1
          ;;
        *)
          printf 'traffic_convergence=INVALID\n' >&2
          return 1
          ;;
      esac
    fi
    if [[ "${attempt}" -lt "${traffic_convergence_attempts}" ]]; then
      sleep "${traffic_convergence_delay_seconds}"
    fi
  done
  printf 'traffic_convergence=TIMEOUT\n' >&2
  return 1
}

traffic_changed_between() {
  local before_path="$1"
  local after_path="$2"
  python3 - "${before_path}" "${after_path}" <<'PY'
import json
import sys
from pathlib import Path

before = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
after = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
raise SystemExit(
    0
    if before.get("spec", {}).get("traffic")
    != after.get("spec", {}).get("traffic")
    else 1
)
PY
}

validate_agent_promoted() {
  local service_path="$1"
  local previous_resource_version="$2"
  python3 - \
    "${service_path}" \
    "${agent_candidate_json}" \
    "${agent_artifact_json}" \
    "${source_sha}" \
    "${agent_candidate_revision}" \
    "${candidate_tag}" \
    "${agent_ref}" \
    "${agent_digest}" \
    "${agent_service_account}" \
    "${previous_resource_version}" \
    "${promotion_lock}" <<'PY'
import copy
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

(
    service_path,
    revision_path,
    artifact_path,
    source_sha,
    revision_name,
    tag,
    image_ref,
    expected_digest,
    account,
    old_rv,
    promotion_lock,
) = sys.argv[1:]
service = json.loads(Path(service_path).read_text(encoding="utf-8"))
revision = json.loads(Path(revision_path).read_text(encoding="utf-8"))
artifact = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
metadata = service.get("metadata", {})
labels = metadata.get("labels", {})
new_rv = metadata.get("resourceVersion")
if (
    not isinstance(new_rv, str)
    or not new_rv
    or not old_rv
    or new_rv == old_rv
):
    raise SystemExit("agent promotion resourceVersion did not advance")
if labels.get("source-commit") != source_sha or labels.get("deployment-lock") != promotion_lock:
    raise SystemExit("agent promotion ownership changed")
def traffic_identity(rows):
    result = []
    seen_tags = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("percent", 0) not in (0, 100):
            raise SystemExit("agent promotion traffic is invalid")
        tag_value = row.get("tag")
        if not isinstance(tag_value, str) or not tag_value or tag_value in seen_tags:
            raise SystemExit("agent promotion traffic tag is invalid")
        seen_tags.add(tag_value)
        result.append((tag_value, row.get("revisionName"), row.get("percent", 0)))
    production = [item for item in result if item[2] == 100]
    if production != [(tag, revision_name, 100)]:
        raise SystemExit("agent promotion traffic target is invalid")
    return sorted(result)

if traffic_identity(service.get("spec", {}).get("traffic", [])) != traffic_identity(
    service.get("status", {}).get("traffic", [])
):
    raise SystemExit("agent promotion status traffic is invalid")
template_spec = service.get("spec", {}).get("template", {}).get("spec")
revision_spec = revision.get("spec")
if not isinstance(template_spec, dict) or not isinstance(revision_spec, dict):
    raise SystemExit("agent promotion changed the candidate template")
comparable_revision_spec = copy.deepcopy(revision_spec)
template_containers = template_spec.get("containers")
revision_containers = comparable_revision_spec.get("containers")
if (
    isinstance(template_containers, list)
    and len(template_containers) == 1
    and isinstance(template_containers[0], dict)
    and "name" not in template_containers[0]
    and isinstance(revision_containers, list)
    and len(revision_containers) == 1
    and isinstance(revision_containers[0], dict)
    and isinstance(revision_containers[0].get("name"), str)
    and revision_containers[0]["name"]
):
    revision_containers[0].pop("name")
if template_spec != comparable_revision_spec:
    raise SystemExit("agent promotion changed the candidate template")
spec = revision.get("spec", {})
containers = spec.get("containers", [])
if (
    spec.get("serviceAccountName") != account
    or len(containers) != 1
    or containers[0].get("image") != image_ref
):
    raise SystemExit("agent promotion runtime identity changed")
artifact_digest = artifact.get("image_summary", {}).get(
    "digest", artifact.get("digest")
)
if artifact_digest != expected_digest:
    raise SystemExit("agent promotion artifact digest changed")
url = service.get("status", {}).get("url")
parsed = urlsplit(url if isinstance(url, str) else "")
if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
    raise SystemExit("stable agent URL is unsafe")
conditions = service.get("status", {}).get("conditions", [])
if not any(row.get("type") == "Ready" and row.get("status") == "True" for row in conditions):
    raise SystemExit("promoted agent is not ready")
PY
}

make_final_web_revision_payload() {
  local service_path="$1"
  local revision_path="$2"
  local output_path="$3"
  local stable_url="$4"
  local final_revision="$5"
  local final_tag="$6"
  python3 - \
    "${service_path}" \
    "${revision_path}" \
    "${output_path}" \
    "${stable_url}" \
    "${final_revision}" \
    "${final_tag}" \
    "${source_sha}" \
    "${promotion_lock}" \
    "${web_predecessor}" \
    "${web_candidate_revision}" \
    "${candidate_tag}" \
    "${project_number}" <<'PY'
import copy
import json
import re
import sys
from pathlib import Path

(
    service_path,
    revision_path,
    output_path,
    stable_agent_url,
    final_revision,
    final_tag,
    source_sha,
    promotion_lock,
    predecessor,
    candidate_revision,
    candidate_tag,
    project_number,
) = sys.argv[1:]
service = json.loads(Path(service_path).read_text(encoding="utf-8"))
candidate = json.loads(Path(revision_path).read_text(encoding="utf-8"))
metadata = service.get("metadata", {})
labels = metadata.get("labels", {})
resource_version = metadata.get("resourceVersion")
if (
    metadata.get("name") != "sumai-web"
    or metadata.get("namespace") != project_number
    or not isinstance(resource_version, str)
    or not resource_version
    or labels.get("source-commit") != source_sha
    or labels.get("deployment-lock") != promotion_lock
):
    raise SystemExit("final web service ownership changed")
if (
    candidate.get("metadata", {}).get("name") != candidate_revision
    or re.fullmatch(r"[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?", final_revision) is None
    or re.fullmatch(r"[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?", final_tag) is None
):
    raise SystemExit("final web revision identity is invalid")

candidate_spec = copy.deepcopy(candidate.get("spec", {}))
containers = candidate_spec.get("containers", [])
if len(containers) != 1 or not isinstance(stable_agent_url, str):
    raise SystemExit("web candidate runtime is invalid")
container = containers[0]
rows = container.get("env", [])
seen = set()
rebound = False
for row in rows:
    if (
        not isinstance(row, dict)
        or set(row) != {"name", "value"}
        or type(row.get("name")) is not str
        or type(row.get("value")) is not str
        or row["name"] in seen
    ):
        raise SystemExit("web candidate environment is unsafe")
    seen.add(row["name"])
    if re.search(r"(?i)(?:key|secret|token|credential|password)", row["name"]):
        raise SystemExit("web candidate contains a sensitive environment field")
    if row["name"] == "SUMAI_AGENT_URL":
        row["value"] = stable_agent_url
        rebound = True
if not rebound:
    raise SystemExit("web candidate agent URL is missing")

source_traffic = service.get("spec", {}).get("traffic", [])
if not isinstance(source_traffic, list):
    raise SystemExit("web service traffic is invalid")
production = [row for row in source_traffic if row.get("percent", 0) == 100]
if (
    len(production) != 1
    or production[0].get("revisionName") != predecessor
    or any(row.get("percent", 0) not in (0, 100) for row in source_traffic)
):
    raise SystemExit("web production changed before final revision creation")
traffic = copy.deepcopy(source_traffic)
seen_tags = set()
candidate_targets = 0
for row in traffic:
    tag = row.get("tag")
    if tag is None:
        if row.get("percent", 0) != 100:
            raise SystemExit("untagged zero traffic target is unsafe")
        continue
    if not isinstance(tag, str) or not tag or tag in seen_tags or tag == final_tag:
        raise SystemExit("web traffic tag is invalid")
    seen_tags.add(tag)
    if tag == candidate_tag and row.get("revisionName") == candidate_revision:
        candidate_targets += 1
if candidate_targets != 1:
    raise SystemExit("web candidate tag changed")
traffic.append({"revisionName": final_revision, "percent": 0, "tag": final_tag})

template_labels = copy.deepcopy(
    service.get("spec", {}).get("template", {}).get("metadata", {}).get("labels", {})
)
if not isinstance(template_labels, dict):
    raise SystemExit("web template labels are invalid")
template_labels["source-commit"] = source_sha
template_labels["deployment-lock"] = promotion_lock
template = {
    "metadata": {
        "name": final_revision,
        "labels": template_labels,
        "annotations": copy.deepcopy(candidate.get("metadata", {}).get("annotations", {})),
    },
    "spec": candidate_spec,
}
payload = {
    "apiVersion": service.get("apiVersion"),
    "kind": service.get("kind"),
    "metadata": {
        "name": metadata.get("name"),
        "namespace": metadata.get("namespace"),
        "labels": copy.deepcopy(labels),
        "annotations": copy.deepcopy(metadata.get("annotations", {})),
        "resourceVersion": resource_version,
    },
    "spec": copy.deepcopy(service.get("spec", {})),
}
payload["spec"]["template"] = template
payload["spec"]["traffic"] = traffic
Path(output_path).write_text(
    json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
}

resolve_final_web_revision() {
  local service_path="$1"
  local previous_resource_version="$2"
  local output_path="$3"
  python3 - \
    "${service_path}" \
    "${previous_resource_version}" \
    "${output_path}" \
    "${source_sha}" \
    "${web_predecessor}" \
    "${web_candidate_revision}" \
    "${candidate_tag}" \
    "${final_web_tag}" \
    "${promotion_lock}" <<'PY'
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

(
    service_path,
    previous_rv,
    output_path,
    source_sha,
    predecessor,
    candidate_revision,
    candidate_tag,
    final_tag,
    promotion_lock,
) = sys.argv[1:]
service = json.loads(Path(service_path).read_text(encoding="utf-8"))
metadata = service.get("metadata", {})
labels = metadata.get("labels", {})
resource_version = metadata.get("resourceVersion")
if (
    not isinstance(resource_version, str)
    or not resource_version
    or not previous_rv
    or resource_version == previous_rv
):
    raise SystemExit("final web deployment resourceVersion did not advance")
if labels.get("source-commit") != source_sha or labels.get("deployment-lock") != promotion_lock:
    raise SystemExit("final web deployment ownership changed")

def production(rows):
    matches = [row.get("revisionName") for row in rows if row.get("percent") == 100]
    return matches[0] if len(matches) == 1 else None

if production(service.get("spec", {}).get("traffic", [])) != predecessor:
    raise SystemExit("web production changed during final revision deployment")
if production(service.get("status", {}).get("traffic", [])) != predecessor:
    raise SystemExit("web status production changed during final revision deployment")
def traffic_identity(rows):
    identity = []
    seen_tags = set()
    for row in rows:
        percent = row.get("percent", 0)
        if percent not in (0, 100):
            raise SystemExit("web traffic contains an invalid percentage")
        tag_value = row.get("tag")
        if percent == 0 and (not isinstance(tag_value, str) or not tag_value):
            raise SystemExit("web zero traffic target is untagged")
        if tag_value:
            if tag_value in seen_tags:
                raise SystemExit("web traffic contains a duplicate tag")
            seen_tags.add(tag_value)
        identity.append((tag_value or "", row.get("revisionName"), percent))
    if len([row for row in identity if row[2] == 100]) != 1:
        raise SystemExit("web traffic has an unexpected positive target")
    return sorted(identity)

if traffic_identity(service.get("spec", {}).get("traffic", [])) != traffic_identity(
    service.get("status", {}).get("traffic", [])
):
    raise SystemExit("web spec and status traffic differ")
spec_candidate = [row for row in service.get("spec", {}).get("traffic", []) if row.get("tag") == candidate_tag]
status_candidate = [row for row in service.get("status", {}).get("traffic", []) if row.get("tag") == candidate_tag]
if (
    len(spec_candidate) != 1
    or spec_candidate[0].get("revisionName") != candidate_revision
    or spec_candidate[0].get("percent", 0) != 0
    or len(status_candidate) != 1
    or status_candidate[0].get("revisionName") != candidate_revision
    or status_candidate[0].get("percent", 0) != 0
):
    raise SystemExit("web candidate identity changed during final deployment")
spec_final = [row for row in service.get("spec", {}).get("traffic", []) if row.get("tag") == final_tag]
status_final = [row for row in service.get("status", {}).get("traffic", []) if row.get("tag") == final_tag]
if len(spec_final) != 1 or len(status_final) != 1:
    raise SystemExit("final web tag did not resolve exactly once")
revision_name = status_final[0].get("revisionName")
url = status_final[0].get("url")
if (
    not isinstance(revision_name, str)
    or spec_final[0].get("revisionName") != revision_name
    or spec_final[0].get("percent", 0) != 0
    or status_final[0].get("percent", 0) != 0
):
    raise SystemExit("final web revision is not at zero traffic")
parsed = urlsplit(url if isinstance(url, str) else "")
if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
    raise SystemExit("final web tag URL is unsafe")
result = {"revision": revision_name, "url": url, "resource_version": resource_version}
Path(output_path).write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
PY
}

validate_final_web_revision() {
  local final_revision_path="$1"
  python3 - \
    "${web_candidate_json}" \
    "${final_revision_path}" \
    "${source_sha}" \
    "${web_ref}" \
    "${web_service_account}" \
    "${stable_agent_url}" \
    "${final_web_revision}" \
    "${promotion_lock}" <<'PY'
import copy
import json
import sys
from pathlib import Path

candidate_path, final_path, source_sha, image_ref, account, agent_url, final_name, promotion_lock = sys.argv[1:]
candidate = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
final = json.loads(Path(final_path).read_text(encoding="utf-8"))
final_metadata = final.get("metadata", {})
final_labels = final_metadata.get("labels", {})
if final_metadata.get("name") != final_name:
    raise SystemExit("final web revision name changed")
if final_labels.get("source-commit") != source_sha or final_labels.get("deployment-lock") != promotion_lock:
    raise SystemExit("final web revision ownership labels changed")
if final_metadata.get("annotations", {}) != candidate.get("metadata", {}).get("annotations", {}):
    raise SystemExit("final web revision annotations drifted")
candidate_spec = copy.deepcopy(candidate.get("spec", {}))
final_spec = copy.deepcopy(final.get("spec", {}))
if candidate_spec.get("serviceAccountName") != account or final_spec.get("serviceAccountName") != account:
    raise SystemExit("final web service account drifted")
candidate_containers = candidate_spec.get("containers", [])
final_containers = final_spec.get("containers", [])
if len(candidate_containers) != 1 or len(final_containers) != 1:
    raise SystemExit("final web container shape changed")
candidate_container = candidate_containers[0]
final_container = final_containers[0]
if (
    candidate_container.get("image") != image_ref
    or final_container.get("image") != image_ref
    or final.get("status", {}).get("imageDigest") != image_ref
):
    raise SystemExit("final web immutable image drifted")

def normalized_env(container, *, rebind):
    result = {}
    for row in container.get("env", []):
        if (
            not isinstance(row, dict)
            or set(row) != {"name", "value"}
            or type(row.get("name")) is not str
            or type(row.get("value")) is not str
            or row["name"] in result
        ):
            raise SystemExit("final web environment is unsafe")
        result[row["name"]] = row["value"]
    if rebind:
        result["SUMAI_AGENT_URL"] = agent_url
        result["PUBLIC_WEB_ANALYSIS_ENABLED"] = "false"
    return [{"name": key, "value": result[key]} for key in sorted(result)]

candidate_container["env"] = normalized_env(candidate_container, rebind=True)
final_container["env"] = normalized_env(final_container, rebind=False)
if final_spec != candidate_spec:
    raise SystemExit("final web runtime configuration drifted")
conditions = final.get("status", {}).get("conditions", [])
if not any(row.get("type") == "Ready" and row.get("status") == "True" for row in conditions):
    raise SystemExit("final web revision is not ready")
PY
}

validate_pre_web_cutover() {
  local agent_path="$1"
  local web_path="$2"
  local final_revision_path="$3"
  python3 - \
    "${agent_path}" \
    "${web_path}" \
    "${agent_candidate_json}" \
    "${web_candidate_json}" \
    "${final_revision_path}" \
    "${agent_artifact_json}" \
    "${web_artifact_json}" \
    "${source_sha}" \
    "${agent_post_resource_version}" \
    "${web_final_resource_version}" \
    "${agent_candidate_revision}" \
    "${web_candidate_revision}" \
    "${final_web_revision}" \
    "${agent_predecessor}" \
    "${web_predecessor}" \
    "${candidate_tag}" \
    "${final_web_tag}" \
    "${agent_ref}" \
    "${web_ref}" \
    "${agent_digest}" \
    "${web_digest}" \
    "${agent_service_account}" \
    "${web_service_account}" \
    "${agent_candidate_url}" \
    "${web_candidate_url}" \
    "${stable_agent_url}" \
    "${promotion_lock}" <<'PY'
import json
import sys
from pathlib import Path

(
    agent_service_path,
    web_service_path,
    agent_candidate_path,
    web_candidate_path,
    final_path,
    agent_artifact_path,
    web_artifact_path,
    source_sha,
    agent_rv,
    web_rv,
    agent_candidate_name,
    web_candidate_name,
    final_name,
    agent_predecessor,
    web_predecessor,
    candidate_tag,
    final_tag,
    agent_ref,
    web_ref,
    agent_digest,
    web_digest,
    agent_account,
    web_account,
    agent_candidate_url,
    web_candidate_url,
    stable_agent_url,
    promotion_lock,
) = sys.argv[1:]

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

agent_service = load(agent_service_path)
web_service = load(web_service_path)
agent_candidate = load(agent_candidate_path)
web_candidate = load(web_candidate_path)
final = load(final_path)
agent_artifact = load(agent_artifact_path)
web_artifact = load(web_artifact_path)

for service, expected_rv in ((agent_service, agent_rv), (web_service, web_rv)):
    metadata = service.get("metadata", {})
    labels = metadata.get("labels", {})
    if metadata.get("resourceVersion") != expected_rv:
        raise SystemExit("resourceVersion changed before web cutover")
    if labels.get("source-commit") != source_sha or labels.get("deployment-lock") != promotion_lock:
        raise SystemExit("deployment ownership changed before web cutover")

def traffic_identity(service):
    identities = []
    for location in ("spec", "status"):
        rows = service.get(location, {}).get("traffic", [])
        values = []
        seen_tags = set()
        for row in rows:
            percent = row.get("percent", 0)
            if percent not in (0, 100):
                raise SystemExit("invalid traffic before web cutover")
            tag_value = row.get("tag")
            if percent == 0 and (not isinstance(tag_value, str) or not tag_value):
                raise SystemExit("untagged zero traffic before web cutover")
            if tag_value:
                if tag_value in seen_tags:
                    raise SystemExit("duplicate traffic tag before web cutover")
                seen_tags.add(tag_value)
            values.append((tag_value or "", row.get("revisionName"), percent))
        if len([value for value in values if value[2] == 100]) != 1:
            raise SystemExit("unexpected positive traffic before web cutover")
        identities.append(sorted(values))
    if identities[0] != identities[1]:
        raise SystemExit("traffic readback differs before web cutover")

traffic_identity(agent_service)
traffic_identity(web_service)

def production(service):
    for location in ("spec", "status"):
        matches = [
            row.get("revisionName")
            for row in service.get(location, {}).get("traffic", [])
            if row.get("percent") == 100
        ]
        if len(matches) != 1:
            raise SystemExit("production traffic is ambiguous before web cutover")
        yield matches[0]

if set(production(agent_service)) != {agent_candidate_name}:
    raise SystemExit("agent production changed before web cutover")
if set(production(web_service)) != {web_predecessor}:
    raise SystemExit("web production changed before web cutover")

def tagged(service, tag, revision, percent, url=None):
    for location in ("spec", "status"):
        matches = [row for row in service.get(location, {}).get("traffic", []) if row.get("tag") == tag]
        if len(matches) != 1 or matches[0].get("revisionName") != revision or matches[0].get("percent", 0) != percent:
            raise SystemExit("tag identity changed before web cutover")
        if location == "status" and url is not None and matches[0].get("url") != url:
            raise SystemExit("tag URL changed before web cutover")

tagged(agent_service, candidate_tag, agent_candidate_name, 100)
tagged(web_service, candidate_tag, web_candidate_name, 0, web_candidate_url)
tagged(web_service, final_tag, final_name, 0)

def verify_revision(value, name, image, account):
    spec = value.get("spec", {})
    containers = spec.get("containers", [])
    if (
        value.get("metadata", {}).get("name") != name
        or spec.get("serviceAccountName") != account
        or len(containers) != 1
        or containers[0].get("image") != image
        or value.get("status", {}).get("imageDigest") != image
    ):
        raise SystemExit("revision identity changed before web cutover")

verify_revision(agent_candidate, agent_candidate_name, agent_ref, agent_account)
verify_revision(web_candidate, web_candidate_name, web_ref, web_account)
verify_revision(final, final_name, web_ref, web_account)
if agent_artifact.get("image_summary", {}).get("digest") != agent_digest:
    raise SystemExit("agent artifact changed before web cutover")
if web_artifact.get("image_summary", {}).get("digest") != web_digest:
    raise SystemExit("web artifact changed before web cutover")
if agent_service.get("status", {}).get("url") != stable_agent_url:
    raise SystemExit("stable agent URL changed before web cutover")
PY
}

validate_final_production() {
  local agent_path="$1"
  local web_path="$2"
  python3 - \
    "${agent_path}" \
    "${web_path}" \
    "${source_sha}" \
    "${agent_candidate_revision}" \
    "${final_web_revision}" \
    "${candidate_tag}" \
    "${final_web_tag}" \
    "${promotion_lock}" <<'PY'
import json
import sys
from pathlib import Path

agent_path, web_path, source_sha, agent_revision, web_revision, candidate_tag, final_tag, promotion_lock = sys.argv[1:]
agent = json.loads(Path(agent_path).read_text(encoding="utf-8"))
web = json.loads(Path(web_path).read_text(encoding="utf-8"))

def verify(service, revision, tag):
    metadata = service.get("metadata", {})
    labels = metadata.get("labels", {})
    if labels.get("source-commit") != source_sha or labels.get("deployment-lock") != promotion_lock:
        raise SystemExit("production ownership changed")
    identities = []
    for location in ("spec", "status"):
        rows = service.get(location, {}).get("traffic", [])
        if any(row.get("percent", 0) not in (0, 100) for row in rows):
            raise SystemExit("production traffic percentage is invalid")
        production = [row for row in rows if row.get("percent") == 100]
        if len(production) != 1 or production[0].get("revisionName") != revision or production[0].get("tag") != tag:
            raise SystemExit("production traffic verification failed")
        seen_tags = set()
        values = []
        for row in rows:
            tag_value = row.get("tag")
            if not isinstance(tag_value, str) or not tag_value or tag_value in seen_tags:
                raise SystemExit("production traffic tag is invalid")
            seen_tags.add(tag_value)
            values.append((tag_value, row.get("revisionName"), row.get("percent", 0)))
        identities.append(sorted(values))
    if identities[0] != identities[1]:
        raise SystemExit("production traffic readback differs")
    conditions = service.get("status", {}).get("conditions", [])
    if not any(row.get("type") == "Ready" and row.get("status") == "True" for row in conditions):
        raise SystemExit("production service is not ready")

verify(agent, agent_revision, candidate_tag)
verify(web, web_revision, final_tag)
PY
}

classify_rollback_service() {
  local service_path="$1"
  local component="$2"
  python3 - \
    "${service_path}" "${component}" \
    "${source_sha}" "${promotion_lock}" \
    "${agent_predecessor}" "${web_predecessor}" \
    "${agent_candidate_revision}" "${web_candidate_revision}" \
    "${final_web_revision}" "${candidate_tag}" "${final_web_tag}" <<'PY'
import json
import sys
from pathlib import Path

(
    service_path,
    component,
    source_sha,
    promotion_lock,
    agent_predecessor,
    web_predecessor,
    agent_candidate,
    web_candidate,
    final_web,
    candidate_tag,
    final_tag,
) = sys.argv[1:]
service = json.loads(Path(service_path).read_text(encoding="utf-8"))
labels = service.get("metadata", {}).get("labels", {})
if labels.get("source-commit") != source_sha:
    raise SystemExit(1)

identities = []
for location in ("spec", "status"):
    rows = service.get(location, {}).get("traffic", [])
    values = []
    seen_tags = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SystemExit(1)
        percent = row.get("percent", 0)
        if percent not in (0, 100):
            raise SystemExit(1)
        revision = row.get("revisionName")
        tag = row.get("tag")
        if not isinstance(revision, str) or (percent == 0 and not tag):
            raise SystemExit(1)
        if tag:
            if not isinstance(tag, str) or tag in seen_tags:
                raise SystemExit(1)
            seen_tags.add(tag)
        values.append((tag or "", revision, percent))
    if len([value for value in values if value[2] == 100]) != 1:
        raise SystemExit(1)
    identities.append(sorted(values))
if identities[0] != identities[1]:
    raise SystemExit(1)
identity = identities[0]
production = [value[1] for value in identity if value[2] == 100][0]

def tagged(tag):
    return [value for value in identity if value[0] == tag]

if component == "agent":
    if production not in {agent_predecessor, agent_candidate}:
        raise SystemExit(1)
    targets = tagged(candidate_tag)
    if len(targets) != 1 or targets[0][1] != agent_candidate:
        raise SystemExit(1)
else:
    allowed = {web_predecessor}
    if final_web:
        allowed.add(final_web)
    if production not in allowed:
        raise SystemExit(1)
    targets = tagged(candidate_tag)
    if len(targets) != 1 or targets[0][1] != web_candidate:
        raise SystemExit(1)
    final_targets = tagged(final_tag) if final_tag else []
    if final_web:
        if final_targets and (
            len(final_targets) != 1 or final_targets[0][1] != final_web
        ):
            raise SystemExit(1)
        if not final_targets and production != web_predecessor:
            raise SystemExit(1)
    elif final_targets and (len(final_targets) != 1 or final_targets[0][2] != 0):
        raise SystemExit(1)

owned = labels.get("deployment-lock") == promotion_lock
if owned:
    if component == "web":
        print("OWNED_SAFE" if production == web_predecessor else "OWNED_UNSAFE")
    else:
        print("OWNED")
elif component == "web" and production == web_predecessor:
    print("FOREIGN_SAFE")
else:
    print("FOREIGN_UNSAFE")
PY
}

make_rollback_payload() {
  local service_path="$1"
  local output_path="$2"
  local predecessor="$3"
  local allowed_tag_one="$4"
  local allowed_tag_two="$5"
  python3 - \
    "${service_path}" \
    "${output_path}" \
    "${predecessor}" \
    "${allowed_tag_one}" \
    "${allowed_tag_two}" \
    "${promotion_lock}" <<'PY'
import copy
import json
import sys
from pathlib import Path

service_path, output_path, predecessor, _tag_one, _tag_two, promotion_lock = sys.argv[1:]
service = json.loads(Path(service_path).read_text(encoding="utf-8"))
metadata = service.get("metadata", {})
resource_version = metadata.get("resourceVersion")
labels = metadata.get("labels", {})
if not isinstance(resource_version, str) or not resource_version:
    raise SystemExit("rollback resourceVersion is missing")
if labels.get("deployment-lock") != promotion_lock:
    raise SystemExit("rollback ownership changed")
traffic = []
seen_tags = set()
tagged_predecessor = False
for row in service.get("spec", {}).get("traffic", []):
    tag = row.get("tag")
    if not tag:
        continue
    if tag in seen_tags:
        raise SystemExit("rollback traffic tag is duplicated")
    seen_tags.add(tag)
    preserved = copy.deepcopy(row)
    if preserved.get("revisionName") == predecessor:
        if tagged_predecessor:
            raise SystemExit("rollback predecessor tag is ambiguous")
        preserved["percent"] = 100
        tagged_predecessor = True
    else:
        preserved["percent"] = 0
    traffic.append(preserved)
if not tagged_predecessor:
    traffic.insert(0, {"revisionName": predecessor, "percent": 100})
spec = copy.deepcopy(service.get("spec", {}))
spec["traffic"] = traffic
payload = {
    "apiVersion": service.get("apiVersion"),
    "kind": service.get("kind"),
    "metadata": {
        "name": metadata.get("name"),
        "namespace": metadata.get("namespace"),
        "labels": copy.deepcopy(metadata.get("labels", {})),
        "annotations": copy.deepcopy(metadata.get("annotations", {})),
        "resourceVersion": resource_version,
    },
    "spec": spec,
}
Path(output_path).write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
PY
}

verify_rollback_target() {
  local service_path="$1"
  local predecessor="$2"
  python3 - "${service_path}" "${predecessor}" <<'PY'
import json
import sys
from pathlib import Path

service = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
predecessor = sys.argv[2]
for location in ("spec", "status"):
    matches = [row.get("revisionName") for row in service.get(location, {}).get("traffic", []) if row.get("percent") == 100]
    if matches != [predecessor]:
        raise SystemExit(1)
PY
}

rollback_release() {
  local rollback_agent_json="${tmp_dir}/rollback-agent-current.json"
  local rollback_web_json="${tmp_dir}/rollback-web-current.json"
  local rollback_agent_payload="${tmp_dir}/rollback-agent-payload.json"
  local rollback_web_payload="${tmp_dir}/rollback-web-payload.json"
  local rollback_response="${tmp_dir}/rollback-response.json"
  local web_class=""
  local agent_class=""
  local web_safe=1
  local any_pass=0
  local any_failed=0
  local any_refused=0
  local rollback_previous_resource_version=""

  agent_rollback_result="NOT_NEEDED"
  web_rollback_result="NOT_NEEDED"

  if [[ "${web_mutation_started}" -eq 1 ]]; then
    if ! describe_service "${web_service}" "${rollback_web_json}"; then
      web_rollback_result="FAILED_READBACK"
      web_safe=0
      any_failed=1
    elif ! web_class="$(classify_rollback_service "${rollback_web_json}" web)"; then
      web_rollback_result="REFUSED_IDENTITY_MISMATCH"
      web_safe=0
      any_refused=1
    elif [[ "${web_class}" == OWNED_SAFE || "${web_class}" == OWNED_UNSAFE ]]; then
      rollback_previous_resource_version="$(json_get "${rollback_web_json}" metadata.resourceVersion)"
      if ! make_rollback_payload \
        "${rollback_web_json}" \
        "${rollback_web_payload}" \
        "${web_predecessor}" \
        "${candidate_tag}" \
        "${final_web_tag}" \
        || ! conditional_put "${rollback_web_payload}" "${rollback_response}" \
        || ! wait_for_traffic_convergence \
          "${web_service}" \
          "${rollback_web_json}" \
          "${rollback_web_payload}" \
          "${rollback_previous_resource_version}" \
          "${promotion_lock}" \
          "${promotion_lock}" \
        || ! verify_rollback_target "${rollback_web_json}" "${web_predecessor}"; then
        web_rollback_result="FAILED"
        web_safe=0
        any_failed=1
      else
        web_rollback_result="PASS"
        any_pass=1
      fi
    elif [[ "${web_class}" == FOREIGN_SAFE ]]; then
      web_rollback_result="ALREADY_PREDECESSOR_FOREIGN_LOCK"
      any_refused=1
    else
      web_rollback_result="REFUSED_FOREIGN_LOCK"
      web_safe=0
      any_refused=1
    fi
  elif [[ "${web_revision_mutation_started}" -eq 1 ]]; then
    if ! describe_service "${web_service}" "${rollback_web_json}"; then
      web_rollback_result="FAILED_READBACK"
      web_safe=0
      any_failed=1
    elif ! web_class="$(classify_rollback_service "${rollback_web_json}" web)"; then
      web_rollback_result="REFUSED_IDENTITY_MISMATCH"
      web_safe=0
      any_refused=1
    elif [[ "${web_class}" == OWNED_SAFE ]]; then
      web_rollback_result="NOT_NEEDED"
    elif [[ "${web_class}" == FOREIGN_SAFE ]]; then
      web_rollback_result="ALREADY_PREDECESSOR_FOREIGN_LOCK"
      any_refused=1
    else
      web_rollback_result="REFUSED_FOREIGN_LOCK"
      web_safe=0
      any_refused=1
    fi
  fi

  if [[ "${agent_mutation_started}" -eq 1 ]]; then
    if ! describe_service "${web_service}" "${rollback_web_json}"; then
      web_safe=0
      web_rollback_result="FAILED_READBACK"
      any_failed=1
    elif ! web_class="$(classify_rollback_service "${rollback_web_json}" web)"; then
      web_safe=0
      web_rollback_result="REFUSED_IDENTITY_MISMATCH"
      any_refused=1
    elif [[ "${web_class}" != OWNED_SAFE && "${web_class}" != FOREIGN_SAFE ]]; then
      web_safe=0
      if [[ "${web_rollback_result}" == PASS || "${web_rollback_result}" == NOT_NEEDED ]]; then
        web_rollback_result="REFUSED_CHANGED_AFTER_CHECK"
      fi
      any_refused=1
    fi
    if [[ "${web_safe}" -ne 1 ]]; then
      agent_rollback_result="BLOCKED_WEB_NOT_SAFE"
      any_refused=1
    elif ! describe_service "${agent_service}" "${rollback_agent_json}"; then
      agent_rollback_result="FAILED_READBACK"
      any_failed=1
    elif ! agent_class="$(classify_rollback_service "${rollback_agent_json}" agent)"; then
      agent_rollback_result="REFUSED_IDENTITY_MISMATCH"
      any_refused=1
    elif [[ "${agent_class}" != OWNED ]]; then
      agent_rollback_result="REFUSED_FOREIGN_LOCK"
      any_refused=1
    else
      rollback_previous_resource_version="$(json_get "${rollback_agent_json}" metadata.resourceVersion)"
      if ! make_rollback_payload \
        "${rollback_agent_json}" \
        "${rollback_agent_payload}" \
        "${agent_predecessor}" \
        "${candidate_tag}" \
        "" \
        || ! conditional_put "${rollback_agent_payload}" "${rollback_response}" \
        || ! wait_for_traffic_convergence \
          "${agent_service}" \
          "${rollback_agent_json}" \
          "${rollback_agent_payload}" \
          "${rollback_previous_resource_version}" \
          "${promotion_lock}" \
          "${promotion_lock}" \
        || ! verify_rollback_target "${rollback_agent_json}" "${agent_predecessor}"; then
        agent_rollback_result="FAILED"
        any_failed=1
      else
        agent_rollback_result="PASS"
        any_pass=1
      fi
    fi
  fi

  if [[ "${any_pass}" -eq 1 && ( "${any_failed}" -eq 1 || "${any_refused}" -eq 1 ) ]]; then
    rollback_result="PARTIAL"
  elif [[ "${any_failed}" -eq 1 ]]; then
    rollback_result="FAILED"
  elif [[ "${any_refused}" -eq 1 ]]; then
    rollback_result="REFUSED"
  else
    rollback_result="PASS"
  fi
  printf 'rollback_agent=%s\n' "${agent_rollback_result}" >&2
  printf 'rollback_web=%s\n' "${web_rollback_result}" >&2
  if [[ "${any_refused}" -eq 1 ]]; then
    printf 'rollback_refused=DEPLOYMENT_LOCK_OR_IDENTITY_MISMATCH\n' >&2
  fi
  printf 'rollback_result=%s\n' "${rollback_result}" >&2
  if [[ "${rollback_result}" == PASS ]]; then
    return 0
  fi
  return 1
}

on_error() {
  local exit_code="$1"
  if [[ "${handling_error}" -eq 1 ]]; then
    exit "${exit_code}"
  fi
  handling_error=1
  trap - ERR
  set +e
  if [[ "${agent_mutation_started}" -eq 1 || "${web_revision_mutation_started}" -eq 1 || "${web_mutation_started}" -eq 1 ]]; then
    rollback_release
  elif [[ "${agent_claimed}" -eq 1 || "${web_claimed}" -eq 1 || "${agent_claim_attempted}" -eq 1 || "${web_claim_attempted}" -eq 1 ]]; then
    restore_claims
  fi
  if [[ "${apply_mode}" == true && -n "${promotion_evidence_path}" ]]; then
    write_promotion_evidence "${promotion_evidence_path}"
  fi
  printf 'promotion_result=FAILED\n' >&2
  exit "${exit_code}"
}

trap cleanup EXIT
trap 'on_error $?' ERR

parse_and_bind_evidence
assert_origin_main
read_initial_state
validate_initial_state
validation_status="PASS"

probe_agent "${agent_candidate_url}" candidate-agent
probe_web "${web_candidate_url}" candidate-web
candidate_probe_status="PASS"

if [[ "${apply_mode}" == false ]]; then
  rollback_result="NOT_NEEDED"
  write_promotion_evidence "${tmp_dir}/promotion-evidence.json"
  trap - ERR
  printf 'promotion_mode=DRY_RUN\n'
  printf 'source_commit=%s\n' "${source_sha}"
  printf 'build_id=%s\n' "${build_id}"
  printf 'proposed_agent_revision=%s\n' "${agent_candidate_revision}"
  printf 'proposed_agent_digest=%s\n' "${agent_digest}"
  printf 'proposed_web_digest=%s\n' "${web_digest}"
  printf 'validation=PASS\n'
  printf 'mutation=NONE\n'
  exit 0
fi

claim_services
assert_origin_main
describe_revision "${agent_candidate_revision}" "${tmp_dir}/agent-candidate-before-cutover.json"
describe_revision "${web_candidate_revision}" "${tmp_dir}/web-candidate-before-cutover.json"
describe_artifact "${agent_ref}" "${tmp_dir}/agent-artifact-before-cutover.json"
describe_artifact "${web_ref}" "${tmp_dir}/web-artifact-before-cutover.json"
python3 - \
  "${agent_candidate_json}" "${tmp_dir}/agent-candidate-before-cutover.json" \
  "${web_candidate_json}" "${tmp_dir}/web-candidate-before-cutover.json" \
  "${agent_artifact_json}" "${tmp_dir}/agent-artifact-before-cutover.json" \
  "${web_artifact_json}" "${tmp_dir}/web-artifact-before-cutover.json" <<'PY'
import json
import sys
from pathlib import Path

for old_path, new_path in zip(sys.argv[1::2], sys.argv[2::2]):
    if json.loads(Path(old_path).read_text(encoding="utf-8")) != json.loads(Path(new_path).read_text(encoding="utf-8")):
        raise SystemExit("candidate identity changed before traffic mutation")
PY
describe_service "${agent_service}" "${agent_service_json}"
describe_service "${web_service}" "${web_service_json}"
validate_owned_services \
  "${agent_service_json}" "${web_service_json}" \
  "${agent_claimed_resource_version}" "${web_claimed_resource_version}" \
  "${agent_predecessor}" "${web_predecessor}" 0

agent_payload="${tmp_dir}/agent-promotion-payload.json"
agent_response="${tmp_dir}/agent-promotion-response.json"
make_promotion_payload \
  "${agent_service_json}" \
  "${agent_payload}" \
  "${agent_candidate_revision}" \
  "${candidate_tag}" \
  ""
assert_origin_main
agent_mutation_started=1
conditional_put "${agent_payload}" "${agent_response}"
wait_for_traffic_convergence \
  "${agent_service}" \
  "${agent_service_json}" \
  "${agent_payload}" \
  "${agent_claimed_resource_version}" \
  "${promotion_lock}" \
  "${promotion_lock}"
describe_revision "${agent_candidate_revision}" "${agent_candidate_json}"
describe_artifact "${agent_ref}" "${agent_artifact_json}"
validate_agent_promoted "${agent_service_json}" "${agent_claimed_resource_version}"
agent_post_resource_version="$(json_get "${agent_service_json}" metadata.resourceVersion)"
stable_agent_url="$(json_get "${agent_service_json}" status.url)"
agent_promotion_status="PASS"

probe_agent "${stable_agent_url}" stable-agent
stable_agent_probe_status="PASS"

promotion_lock_suffix="${promotion_lock#promote-}"
promotion_lock_suffix="${promotion_lock_suffix:0:10}"
final_web_suffix="final-${source_sha:0:7}-${candidate_tag##*-}-${promotion_lock_suffix}"
final_web_revision="${web_service}-${final_web_suffix}"
final_web_tag="promoted-${source_sha:0:7}-${candidate_tag##*-}-${promotion_lock_suffix}"

assert_origin_main
describe_service "${agent_service}" "${agent_service_json}"
describe_service "${web_service}" "${web_service_json}"
validate_owned_services \
  "${agent_service_json}" "${web_service_json}" \
  "${agent_post_resource_version}" "${web_claimed_resource_version}" \
  "${agent_candidate_revision}" "${web_predecessor}" 100

final_web_payload="${tmp_dir}/final-web-service-payload.json"
final_web_response="${tmp_dir}/final-web-service-response.json"
make_final_web_revision_payload \
  "${web_service_json}" \
  "${web_candidate_json}" \
  "${final_web_payload}" \
  "${stable_agent_url}" \
  "${final_web_revision}" \
  "${final_web_tag}"
web_revision_mutation_started=1
conditional_put "${final_web_payload}" "${final_web_response}"
final_resolution="${tmp_dir}/final-web-resolution.json"
final_resolution_ready=0
for _attempt in {1..20}; do
  if describe_service "${web_service}" "${web_service_json}" \
    && resolve_final_web_revision \
      "${web_service_json}" \
      "${web_claimed_resource_version}" \
      "${final_resolution}" 2>/dev/null; then
    final_resolution_ready=1
    break
  fi
  sleep 2
done
if [[ "${final_resolution_ready}" -ne 1 ]]; then
  printf 'final_web_revision=UNAVAILABLE\n' >&2
  false
fi
resolved_final_web_revision="$(json_get "${final_resolution}" revision)"
if [[ "${resolved_final_web_revision}" != "${final_web_revision}" ]]; then
  printf 'final_web_revision=IDENTITY_MISMATCH\n' >&2
  false
fi
final_web_url="$(json_get "${final_resolution}" url)"
web_final_resource_version="$(json_get "${final_resolution}" resource_version)"
final_web_revision_json="${tmp_dir}/final-web-revision.json"
final_revision_ready=0
for _attempt in {1..20}; do
  if describe_revision "${final_web_revision}" "${final_web_revision_json}" 2>/dev/null \
    && python3 - "${final_web_revision_json}" <<'PY'
import json
import sys
from pathlib import Path

revision = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
conditions = revision.get("status", {}).get("conditions", [])
if not any(
    row.get("type") == "Ready" and row.get("status") == "True"
    for row in conditions
):
    raise SystemExit(1)
PY
  then
    final_revision_ready=1
    break
  fi
  sleep 2
done
if [[ "${final_revision_ready}" -ne 1 ]]; then
  printf 'final_web_revision=NOT_READY\n' >&2
  false
fi
validate_final_web_revision "${final_web_revision_json}"
final_web_deploy_status="PASS"

probe_web "${final_web_url}" final-web
final_web_probe_status="PASS"

assert_origin_main
describe_service "${agent_service}" "${agent_service_json}"
describe_service "${web_service}" "${web_service_json}"
describe_revision "${agent_candidate_revision}" "${agent_candidate_json}"
describe_revision "${web_candidate_revision}" "${web_candidate_json}"
describe_revision "${final_web_revision}" "${final_web_revision_json}"
describe_artifact "${agent_ref}" "${agent_artifact_json}"
describe_artifact "${web_ref}" "${web_artifact_json}"
validate_pre_web_cutover \
  "${agent_service_json}" \
  "${web_service_json}" \
  "${final_web_revision_json}"

web_payload="${tmp_dir}/web-promotion-payload.json"
web_response="${tmp_dir}/web-promotion-response.json"
make_promotion_payload \
  "${web_service_json}" \
  "${web_payload}" \
  "${final_web_revision}" \
  "${final_web_tag}" \
  "${candidate_tag}"
web_mutation_started=1
conditional_put "${web_payload}" "${web_response}"
wait_for_traffic_convergence \
  "${web_service}" \
  "${web_service_json}" \
  "${web_payload}" \
  "${web_final_resource_version}" \
  "${promotion_lock}" \
  "${promotion_lock}"
describe_service "${agent_service}" "${agent_service_json}"
validate_final_production "${agent_service_json}" "${web_service_json}"
web_promotion_status="PASS"

probe_agent "${stable_agent_url}" production-agent
stable_web_url="$(json_get "${web_service_json}" status.url)"
probe_web "${stable_web_url}" production-web
production_probe_status="PASS"

assert_origin_main
describe_service "${agent_service}" "${agent_service_json}"
describe_service "${web_service}" "${web_service_json}"
validate_final_production "${agent_service_json}" "${web_service_json}"

promotion_succeeded=1
rollback_result="NOT_NEEDED"
write_promotion_evidence "${promotion_evidence_path}"
trap - ERR
printf 'promotion_result=PASS\n'
printf 'source_commit=%s\n' "${source_sha}"
printf 'build_id=%s\n' "${build_id}"
printf 'agent_revision=%s\n' "${agent_candidate_revision}"
printf 'web_revision=%s\n' "${final_web_revision}"
