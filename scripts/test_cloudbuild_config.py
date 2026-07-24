import re
from pathlib import Path


root = Path(__file__).resolve().parents[1]
config_path = root / "cloudbuild.yaml"
assert config_path.is_file(), "cloudbuild.yaml must exist"

text = config_path.read_text(encoding="utf-8")

for required in (
    "${COMMIT_SHA}",
    "--no-traffic",
    "candidate-${SHORT_SHA}",
    "sumai-gemini-api-key:2",
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

image_lines = [
    line.split(":", 1)[-1].strip()
    for line in text.splitlines()
    if "docker.pkg.dev" in line
]
assert all(not line.endswith(":latest") for line in image_lines)
