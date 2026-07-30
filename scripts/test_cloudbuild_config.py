import re
from pathlib import Path


root = Path(__file__).resolve().parents[1]
config_path = root / "cloudbuild.yaml"
assert config_path.is_file(), "cloudbuild.yaml must exist"

text = config_path.read_text(encoding="utf-8")

test_block = text.split("  - id: test", 1)[1].split("\n  - id:", 1)[0]
assert "apt-get update" in test_block
assert re.search(r"apt-get install .*nodejs", test_block)
assert "node --version" in test_block
assert test_block.index("node --version") < test_block.index("python -m pytest")

for required in (
    "${COMMIT_SHA}",
    "--no-traffic",
    "candidate-${SHORT_SHA}",
    "sumai-gemini-api-key:2",
    "--remove-env-vars=GEMINI_API_KEY",
    "REQUIRE_REAL_GEMINI=true",
    "smoke_real_gemini.py",
    "update-traffic",
    "source-commit=${COMMIT_SHA}",
    "/workspace/sumai-agent.digest",
    "/workspace/sumai-web.digest",
    "assert_current_build",
    "rollback",
    "--remove-tags",
    "deployment-lock=${COMMIT_SHA}",
):
    assert required in text, required

assert "--update-secrets=GEMINI_API_KEY=sumai-gemini-api-key:2" in text
assert "sumai-gemini-api-key:latest" not in text
assert not re.search(r"--(?:set|update)-env-vars[^\n]*GEMINI_API_KEY", text)
assert text.count("/ready") == 3
assert "/healthz" not in text

probe_web_block = text.split("  - id: probe-web-candidate", 1)[1].split(
    "\n  - id:", 1
)[0]
assert "name: gcr.io/google.com/cloudsdktool/cloud-sdk:slim" in probe_web_block
assert "curlimages/curl" not in probe_web_block

image_lines = [
    line.split(":", 1)[-1].strip()
    for line in text.splitlines()
    if "docker.pkg.dev" in line
]
assert all(not line.endswith(":latest") for line in image_lines)
