#!/usr/bin/env bash
set -euo pipefail

# Compatibility wrapper for the cloudbuild.yaml candidate-only paired release.
# A partial web release is forbidden; no production traffic is changed here.

if (( $# != 0 )); then
    printf 'ERROR: Partial release arguments are not supported\n' >&2
    exit 64
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
exec "$ROOT_DIR/scripts/deploy_all_cloudrun.sh"
