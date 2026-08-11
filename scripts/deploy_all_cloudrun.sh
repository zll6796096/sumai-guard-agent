#!/usr/bin/env bash
set -euo pipefail

# Sole deployment entrypoint: submit both services through cloudbuild.yaml as
# candidate-only revisions. This script never promotes or changes production traffic.

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 64
}

if (( $# != 0 )); then
    fail "This paired candidate-only entrypoint accepts no arguments"
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

PROJECT="${GOOGLE_CLOUD_PROJECT:-}"
FIREBASE_APP_ID="${SUMAI_FIREBASE_APP_ID:-}"
AGENT_SERVICE_ACCOUNT="${SUMAI_AGENT_SERVICE_ACCOUNT:-}"
WEB_SERVICE_ACCOUNT="${SUMAI_WEB_SERVICE_ACCOUNT:-}"
EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT="${SUMAI_EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT:-}"
EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT="${SUMAI_EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT:-}"
SERVICE_ACCOUNT_MIGRATION_CONFIRM="${SUMAI_SERVICE_ACCOUNT_MIGRATION_CONFIRM:-}"
REGION="${SUMAI_REGION:-asia-northeast1}"
AR_REPO="${SUMAI_AR_REPO:-apps}"
AGENT_SERVICE="${SUMAI_AGENT_SERVICE:-sumai-agent}"
WEB_SERVICE="${SUMAI_WEB_SERVICE:-sumai-web}"

[[ -n "$PROJECT" ]] || fail "GOOGLE_CLOUD_PROJECT is required"
[[ -n "$FIREBASE_APP_ID" ]] || fail "SUMAI_FIREBASE_APP_ID is required"
[[ -n "$AGENT_SERVICE_ACCOUNT" ]] || fail "SUMAI_AGENT_SERVICE_ACCOUNT is required"
[[ -n "$WEB_SERVICE_ACCOUNT" ]] || fail "SUMAI_WEB_SERVICE_ACCOUNT is required"
[[ -n "$EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT" ]] ||
    fail "SUMAI_EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT is required"
[[ -n "$EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT" ]] ||
    fail "SUMAI_EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT is required"

[[ "$PROJECT" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] ||
    fail "GOOGLE_CLOUD_PROJECT is invalid"
[[ "$FIREBASE_APP_ID" =~ ^1:[0-9]+:ios:[0-9a-f]+$ ]] ||
    fail "SUMAI_FIREBASE_APP_ID is invalid"
[[ "$REGION" =~ ^[a-z]+-[a-z]+[0-9]+$ ]] ||
    fail "SUMAI_REGION is invalid"

validate_resource_name() {
    local variable_name="$1"
    local value="$2"
    [[ "$value" =~ ^[a-z][a-z0-9-]{0,61}[a-z0-9]$ ]] ||
        fail "$variable_name is invalid"
}

validate_resource_name "SUMAI_AR_REPO" "$AR_REPO"
validate_resource_name "SUMAI_AGENT_SERVICE" "$AGENT_SERVICE"
validate_resource_name "SUMAI_WEB_SERVICE" "$WEB_SERVICE"

validate_predecessor_service_account() {
    local variable_name="$1"
    local account="$2"

    [[ "$account" =~ ^([a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com|[0-9]+-compute@developer\.gserviceaccount\.com)$ ]] ||
        fail "$variable_name is invalid"
}

[[ "$AGENT_SERVICE_ACCOUNT" == "sumai-agent-runtime@${PROJECT}.iam.gserviceaccount.com" ]] ||
    fail "SUMAI_AGENT_SERVICE_ACCOUNT must be the approved dedicated target-project identity"
[[ "$WEB_SERVICE_ACCOUNT" == "sumai-web-runtime@${PROJECT}.iam.gserviceaccount.com" ]] ||
    fail "SUMAI_WEB_SERVICE_ACCOUNT must be the approved dedicated target-project identity"
validate_predecessor_service_account \
    "SUMAI_EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT" \
    "$EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT"
validate_predecessor_service_account \
    "SUMAI_EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT" \
    "$EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT"

if [[ "$EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT" != "$AGENT_SERVICE_ACCOUNT" ||
      "$EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT" != "$WEB_SERVICE_ACCOUNT" ]]; then
    [[ "$SERVICE_ACCOUNT_MIGRATION_CONFIRM" == "MIGRATE_TO_DEDICATED_RUNTIME_SAS" ]] ||
        fail "SUMAI_SERVICE_ACCOUNT_MIGRATION_CONFIRM must explicitly approve the dedicated runtime SA migration"
fi

command -v git >/dev/null 2>&1 || fail "git is required"
command -v gcloud >/dev/null 2>&1 || fail "gcloud is required"

CURRENT_BRANCH="$(git -C "$ROOT_DIR" symbolic-ref --quiet --short HEAD)" ||
    fail "Detached HEAD is not deployable; branch main is required"
[[ "$CURRENT_BRANCH" == "main" ]] || fail "Branch main is required"

HEAD_SHA="$(git -C "$ROOT_DIR" rev-parse --verify 'HEAD^{commit}')" ||
    fail "Unable to resolve local HEAD"
[[ "$HEAD_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "Local HEAD is invalid"

git -C "$ROOT_DIR" diff --quiet --no-ext-diff --ignore-submodules -- ||
    fail "Tracked worktree must be clean"
git -C "$ROOT_DIR" diff --cached --quiet --no-ext-diff --ignore-submodules -- ||
    fail "Git index must be clean"

REMOTE_LINE="$(git -C "$ROOT_DIR" ls-remote --exit-code origin refs/heads/main)" ||
    fail "Unable to resolve remote origin main"
REMOTE_SHA="${REMOTE_LINE%%[[:space:]]*}"
[[ "$REMOTE_LINE" == "$REMOTE_SHA"$'\trefs/heads/main' ]] ||
    fail "Remote origin main response is invalid"
[[ "$REMOTE_SHA" == "$HEAD_SHA" ]] ||
    fail "Remote origin main must exactly match local HEAD"

TEMP_BASE="${TMPDIR:-/tmp}"
[[ "$TEMP_BASE" == /* && -d "$TEMP_BASE" && -w "$TEMP_BASE" ]] ||
    fail "TMPDIR must be an absolute writable directory"
TEMP_BASE="$(cd -- "$TEMP_BASE" && pwd -P)"
TEMP_DIR="$(mktemp -d "${TEMP_BASE%/}/sumai-cloudbuild.XXXXXX")"
[[ -d "$TEMP_DIR" && "$TEMP_DIR" == "$TEMP_BASE"/sumai-cloudbuild.* ]] ||
    fail "Unable to create a private temporary directory"
chmod 700 "$TEMP_DIR"

cleanup() {
    if [[ -n "${TEMP_DIR:-}" && -d "$TEMP_DIR" &&
          "$TEMP_DIR" == "$TEMP_BASE"/sumai-cloudbuild.* ]]; then
        rm -rf -- "$TEMP_DIR"
    fi
}
trap cleanup EXIT

umask 077
SOURCE_ARCHIVE="$TEMP_DIR/source.tar.gz"
BUILD_CONFIG="$TEMP_DIR/cloudbuild.yaml"
git -C "$ROOT_DIR" archive \
    --format=tar.gz \
    --output="$SOURCE_ARCHIVE" \
    "$HEAD_SHA"
git -C "$ROOT_DIR" show "${HEAD_SHA}:cloudbuild.yaml" > "$BUILD_CONFIG"
chmod 600 "$SOURCE_ARCHIVE" "$BUILD_CONFIG"
[[ -s "$SOURCE_ARCHIVE" ]] || fail "Immutable source archive is empty"
[[ -s "$BUILD_CONFIG" ]] || fail "Immutable cloudbuild.yaml is empty"

[[ "$(git -C "$ROOT_DIR" symbolic-ref --quiet --short HEAD)" == "main" ]] ||
    fail "Branch changed while preparing the archive"
[[ "$(git -C "$ROOT_DIR" rev-parse --verify 'HEAD^{commit}')" == "$HEAD_SHA" ]] ||
    fail "HEAD changed while preparing the archive"
git -C "$ROOT_DIR" diff --quiet --no-ext-diff --ignore-submodules -- ||
    fail "Tracked worktree changed while preparing the archive"
git -C "$ROOT_DIR" diff --cached --quiet --no-ext-diff --ignore-submodules -- ||
    fail "Git index changed while preparing the archive"

SHORT_SHA="${HEAD_SHA:0:7}"
SUBSTITUTIONS="COMMIT_SHA=${HEAD_SHA},SHORT_SHA=${SHORT_SHA},_REGION=${REGION},_AR_REPO=${AR_REPO},_AGENT_SERVICE=${AGENT_SERVICE},_WEB_SERVICE=${WEB_SERVICE},_FIREBASE_APP_ID=${FIREBASE_APP_ID},_AGENT_SERVICE_ACCOUNT=${AGENT_SERVICE_ACCOUNT},_WEB_SERVICE_ACCOUNT=${WEB_SERVICE_ACCOUNT},_EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT=${EXPECTED_AGENT_PREDECESSOR_SERVICE_ACCOUNT},_EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT=${EXPECTED_WEB_PREDECESSOR_SERVICE_ACCOUNT},_SERVICE_ACCOUNT_MIGRATION_CONFIRM=${SERVICE_ACCOUNT_MIGRATION_CONFIRM}"

safe_provider_error() {
    local stderr_path="$1"
    local permission
    for permission in \
        iam.serviceAccounts.actAs \
        storage.objects.create \
        storage.objects.get \
        storage.objects.list \
        storage.buckets.get \
        cloudbuild.builds.create \
        serviceusage.services.use; do
        if grep -Fq -- "$permission" "$stderr_path"; then
            printf '%s\n' "$permission"
            return
        fi
    done
    printf 'PROVIDER_ERROR_REDACTED\n'
}

GCLOUD_STDERR="$TEMP_DIR/gcloud-submit.stderr"
if ! BUILD_ID="$(gcloud builds submit "$SOURCE_ARCHIVE" \
    "--config=$BUILD_CONFIG" \
    "--project=$PROJECT" \
    "--region=$REGION" \
    "--substitutions=$SUBSTITUTIONS" \
    --async \
    --format=value\(id\) \
    2>"$GCLOUD_STDERR")"; then
    SAFE_PROVIDER_ERROR="$(safe_provider_error "$GCLOUD_STDERR")"
    fail "Cloud Build submission failed (${SAFE_PROVIDER_ERROR})"
fi
[[ "$BUILD_ID" =~ ^[A-Za-z0-9][A-Za-z0-9-]{2,127}$ ]] ||
    fail "Cloud Build did not return a valid build identifier"

printf 'Candidate-only paired build submitted; no production traffic is changed or promoted.\n'
printf 'Build identifier: %s\n' "$BUILD_ID"
printf 'Evidence hint: inspect this Cloud Build and its candidate evidence before any separate promotion gate.\n'
