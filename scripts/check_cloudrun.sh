#!/usr/bin/env bash
set -Eeuo pipefail

# Read-only Cloud Run evidence inspection. This script never sends an image or
# request body and never changes service configuration or traffic.

umask 077

project="${GOOGLE_CLOUD_PROJECT:-}"
region="${SUMAI_REGION:-}"
agent_service="${SUMAI_AGENT_SERVICE:-}"
web_service="${SUMAI_WEB_SERVICE:-}"

if [[ -z "${project}" ]]; then
  printf 'GOOGLE_CLOUD_PROJECT is required\n' >&2
  exit 2
fi
if [[ -z "${region}" ]]; then
  printf 'SUMAI_REGION is required\n' >&2
  exit 2
fi
if [[ -z "${agent_service}" ]]; then
  printf 'SUMAI_AGENT_SERVICE is required\n' >&2
  exit 2
fi
if [[ -z "${web_service}" ]]; then
  printf 'SUMAI_WEB_SERVICE is required\n' >&2
  exit 2
fi

if ! python3 - "${project}" "${region}" "${agent_service}" "${web_service}" <<'PY'
import re
import sys

project, region, agent_service, web_service = sys.argv[1:]
if re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project) is None:
    raise SystemExit(1)
if len(region) > 40 or re.fullmatch(
    r"[a-z][a-z0-9]{0,14}(?:-[a-z0-9]{1,15}){1,2}", region
) is None:
    raise SystemExit(1)
service_pattern = re.compile(r"[a-z][a-z0-9-]{0,61}[a-z0-9]|[a-z]")
if any(
    service_pattern.fullmatch(service) is None
    for service in (agent_service, web_service)
):
    raise SystemExit(1)
if agent_service == web_service:
    raise SystemExit(1)
PY
then
  printf 'cloud_run_target=INVALID\n' >&2
  exit 2
fi

tmp_parent="${TMPDIR:-/tmp}"
tmp_dir=""
created_tmp_dir=false

cleanup() {
  if [[ "${created_tmp_dir}" == true && -n "${tmp_dir}" && -d "${tmp_dir}" ]]; then
    rm -rf -- "${tmp_dir}"
  fi
}
trap cleanup EXIT

tmp_dir="$(mktemp -d "${tmp_parent%/}/sumaiguard-cloudrun-check.XXXXXX")"
chmod 700 "${tmp_dir}"
created_tmp_dir=true

agent_json="${tmp_dir}/agent-service.json"
web_json="${tmp_dir}/web-service.json"
agent_summary="${tmp_dir}/agent-summary.json"
web_summary="${tmp_dir}/web-summary.json"
for private_file in "${agent_json}" "${web_json}" "${agent_summary}" "${web_summary}"; do
  : > "${private_file}"
  chmod 600 "${private_file}"
done

fail_safe() {
  local service_name="$1"
  local endpoint="$2"
  local reason="$3"
  printf 'inspection_result=FAILED_SAFE\n' >&2
  printf 'service=%s endpoint=%s reason=%s\n' \
    "${service_name}" "${endpoint}" "${reason}" >&2
  exit 1
}

describe_service() {
  local service_name="$1"
  local output_path="$2"
  if ! gcloud run services describe "${service_name}" --project="${project}" --region="${region}" --format=json > "${output_path}" 2>/dev/null; then
    fail_safe "${service_name}" control-plane DESCRIBE_UNAVAILABLE
  fi
}

summarize_service() {
  local source_path="$1"
  local output_path="$2"
  local expected_name="$3"
  if ! python3 - "${source_path}" "${output_path}" "${expected_name}" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

source_path, output_path, expected_name = sys.argv[1:]

def fail() -> None:
    raise SystemExit(1)

try:
    service = json.loads(Path(source_path).read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    fail()
if not isinstance(service, dict):
    fail()
metadata = service.get("metadata", {})
spec = service.get("spec", {})
status = service.get("status", {})
if metadata.get("name") != expected_name:
    fail()

url = status.get("url")
if not isinstance(url, str):
    fail()
parsed = urlsplit(url)
if (
    parsed.scheme != "https"
    or not parsed.hostname
    or not parsed.hostname.endswith(".run.app")
    or parsed.port is not None
    or parsed.username is not None
    or parsed.password is not None
    or parsed.path not in {"", "/"}
    or parsed.query
    or parsed.fragment
):
    fail()

revision_pattern = re.compile(r"[a-z][a-z0-9-]{0,62}")
tag_pattern = re.compile(r"[a-z][a-z0-9-]{0,62}")
latest_created = status.get("latestCreatedRevisionName")
latest_ready = status.get("latestReadyRevisionName")
if any(
    not isinstance(value, str) or revision_pattern.fullmatch(value) is None
    for value in (latest_created, latest_ready)
):
    fail()

traffic = status.get("traffic")
if not isinstance(traffic, list) or not traffic:
    fail()
traffic_parts = []
positive_total = 0
seen_tags = set()
for row in traffic:
    if not isinstance(row, dict):
        fail()
    revision = row.get("revisionName")
    percent = row.get("percent", 0)
    tag = row.get("tag")
    if (
        not isinstance(revision, str)
        or revision_pattern.fullmatch(revision) is None
        or type(percent) is not int
        or not 0 <= percent <= 100
    ):
        fail()
    if tag is not None:
        if (
            not isinstance(tag, str)
            or tag_pattern.fullmatch(tag) is None
            or tag in seen_tags
        ):
            fail()
        seen_tags.add(tag)
        traffic_parts.append(f"{tag}@{revision}:{percent}")
    else:
        traffic_parts.append(f"{revision}:{percent}")
    positive_total += percent
if positive_total != 100:
    fail()

template_spec = spec.get("template", {}).get("spec", {})
account = template_spec.get("serviceAccountName")
containers = template_spec.get("containers")
timeout = template_spec.get("timeoutSeconds")
concurrency = template_spec.get("containerConcurrency")
if not isinstance(account, str) or not account or not isinstance(containers, list):
    fail()
if type(timeout) is not int or timeout <= 0:
    fail()
if type(concurrency) is not int or concurrency <= 0:
    fail()

summary = {
    "url": url.rstrip("/"),
    "latest_created_revision": latest_created,
    "latest_ready_revision": latest_ready,
    "traffic": ",".join(traffic_parts),
    "service_account_sha256": hashlib.sha256(account.encode("utf-8")).hexdigest()[:16],
    "container_count": len(containers),
    "timeout_seconds": timeout,
    "container_concurrency": concurrency,
}
Path(output_path).write_text(
    json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
  then
    fail_safe "${expected_name}" control-plane INVALID_SERVICE_RESPONSE
  fi
  chmod 600 "${output_path}"
}

summary_value() {
  python3 - "$1" "$2" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))[sys.argv[2]]
if not isinstance(value, (str, int)) or isinstance(value, bool):
    raise SystemExit(1)
print(value)
PY
}

print_summary() {
  local service_name="$1"
  local summary_path="$2"
  local url latest_created latest_ready traffic account_hash containers timeout concurrency
  url="$(summary_value "${summary_path}" url)"
  latest_created="$(summary_value "${summary_path}" latest_created_revision)"
  latest_ready="$(summary_value "${summary_path}" latest_ready_revision)"
  traffic="$(summary_value "${summary_path}" traffic)"
  account_hash="$(summary_value "${summary_path}" service_account_sha256)"
  containers="$(summary_value "${summary_path}" container_count)"
  timeout="$(summary_value "${summary_path}" timeout_seconds)"
  concurrency="$(summary_value "${summary_path}" container_concurrency)"
  printf 'service=%s\n' "${service_name}"
  printf 'url=%s\n' "${url}"
  printf 'latest_created_revision=%s\n' "${latest_created}"
  printf 'latest_ready_revision=%s\n' "${latest_ready}"
  printf 'traffic=%s\n' "${traffic}"
  printf 'service_account_sha256=%s\n' "${account_hash}"
  printf 'config_summary=containers:%s,timeout_seconds:%s,container_concurrency:%s\n' \
    "${containers}" "${timeout}" "${concurrency}"
}

probe_endpoint() {
  local service_name="$1"
  local base_url="$2"
  local endpoint="$3"
  local response_kind="$4"
  local expected_status="$5"
  local require_no_store="$6"
  local safe_label
  safe_label="$(printf '%s' "${service_name}-${endpoint}" | tr -cd 'a-zA-Z0-9-')"
  local body_path="${tmp_dir}/${safe_label}.body"
  local header_path="${tmp_dir}/${safe_label}.headers"
  local status_code=""
  : > "${body_path}"
  : > "${header_path}"
  chmod 600 "${body_path}" "${header_path}"

  if ! status_code="$(curl \
    --disable \
    --proto '=https' \
    --max-redirs 0 \
    --silent \
    --show-error \
    --connect-timeout 5 \
    --max-time 15 \
    --max-filesize 1048576 \
    --request GET \
    --dump-header "${header_path}" \
    --output "${body_path}" \
    --write-out '%{http_code}' \
    "${base_url}${endpoint}" 2>/dev/null)"; then
    fail_safe "${service_name}" "${endpoint}" UNREACHABLE_OR_NON_200
  fi
  if [[ "${status_code}" != 200 ]]; then
    fail_safe "${service_name}" "${endpoint}" UNREACHABLE_OR_NON_200
  fi

  if [[ "${response_kind}" == json ]]; then
    if ! python3 - "${body_path}" "${expected_status}" <<'PY'
import json
import sys
from pathlib import Path

try:
    value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError):
    raise SystemExit(1)
if not isinstance(value, dict) or value.get("status") != sys.argv[2]:
    raise SystemExit(1)
PY
    then
      fail_safe "${service_name}" "${endpoint}" INVALID_JSON_RESPONSE
    fi
  elif [[ ! -s "${body_path}" ]]; then
    fail_safe "${service_name}" "${endpoint}" EMPTY_RESPONSE
  fi

  if [[ "${require_no_store}" == true ]]; then
    if ! python3 - "${header_path}" <<'PY'
import sys
from pathlib import Path

try:
    headers = Path(sys.argv[1]).read_text(encoding="iso-8859-1")
except OSError:
    raise SystemExit(1)
values = [
    line.partition(":")[2].strip().casefold()
    for line in headers.splitlines()
    if line.partition(":")[0].strip().casefold() == "cache-control"
]
if not values or "no-store" not in {
    directive.strip() for directive in values[-1].split(",")
}:
    raise SystemExit(1)
PY
    then
      fail_safe "${service_name}" "${endpoint}" NO_STORE_REQUIRED
    fi
  fi
  printf 'probe=PASS service=%s endpoint=%s\n' "${service_name}" "${endpoint}"
}

describe_service "${agent_service}" "${agent_json}"
describe_service "${web_service}" "${web_json}"
summarize_service "${agent_json}" "${agent_summary}" "${agent_service}"
summarize_service "${web_json}" "${web_summary}" "${web_service}"

printf 'inspection_mode=READ_ONLY\n'
printf 'project=%s region=%s\n' "${project}" "${region}"
print_summary "${agent_service}" "${agent_summary}"
print_summary "${web_service}" "${web_summary}"

agent_account_hash="$(summary_value "${agent_summary}" service_account_sha256)"
web_account_hash="$(summary_value "${web_summary}" service_account_sha256)"
if [[ "${agent_account_hash}" == "${web_account_hash}" ]]; then
  printf 'service_accounts_equal=true\n'
else
  printf 'service_accounts_equal=false\n'
fi

agent_url="$(summary_value "${agent_summary}" url)"
web_url="$(summary_value "${web_summary}" url)"
probe_endpoint "${agent_service}" "${agent_url}" /health json ok false
probe_endpoint "${agent_service}" "${agent_url}" /ready json ready false
probe_endpoint "${web_service}" "${web_url}" / html unused false
probe_endpoint "${web_service}" "${web_url}" /ready json ok false
probe_endpoint "${web_service}" "${web_url}" /privacy html unused true
probe_endpoint "${web_service}" "${web_url}" /support html unused true

printf 'inspection_result=PASS\n'
