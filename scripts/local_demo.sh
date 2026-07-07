#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Web: http://localhost:8081"
echo "Agent health: http://localhost:8080/healthz"
docker compose up --build
