# Product Decisions

## No Questionnaire

The POC does not ask age, walking state, fall history, care level, disease, medication, or insurance questions.

Reason: the core product test is whether one home photo can start a family safety conversation without adding friction or collecting sensitive profile data.

## No Full RAG or Vector DB

The POC uses `demo_rules.yaml` as a compact RAG-lite evidence base.

Reason: the current objective is deterministic action routing, not open-ended retrieval. A vector DB would add operational complexity before proving the basic workflow.

## No Report Download

PDF download is not implemented.

Reason: the current demo needs on-screen communication and re-check flow only. Persistent artifacts can be designed later when storage, privacy, and sharing rules are defined.

## No Final Renovation Design

The improvement image is a deterministic visual explanation with overlays such as safe zones, arrows, and labels.

Reason: the product is a preventive safety checker, not an interior design or construction drawing tool.

## Action Cards Are Required

The three action tiers are part of the core product.

Reason: preventive safety is useful only when the family can tell what they can do today, what needs care-manager or welfare-equipment consultation, and what requires professional on-site confirmation.

## Mock Mode Is Required

The app must work without Gemini credentials.

Reason: local demos, development, and tests should not depend on secrets or paid external calls.

## Local Ports

The requested defaults are backend `8080` and frontend `8081`.

Assumption: if another sibling project occupies a port, the user can change the local compose port mapping. This POC does not change the requested defaults.

## Cloud Run Deployment

Both services deploy to Cloud Run in `asia-northeast1` via source deploy (using the existing Dockerfiles).

Reasons:
- Cloud Run provides auto-scaling, HTTPS, and zero infrastructure management.
- Source deploy uses existing Dockerfiles — no separate container registry needed.
- `asia-northeast1` is closest to Japan users.
- The web service discovers the agent URL via environment variable at deploy time.

## Gemini API Integration

Gemini provides risk candidates via structured JSON output. The deterministic rule engine controls all action routing post-Gemini.

Reasons:
- Structured JSON output (`response_mime_type="application/json"`) ensures parseable responses.
- Pydantic validation catches malformed fields.
- Bbox 0–1000 normalization handles Gemini's coordinate inconsistency.
- Timeout and fallback ensure the demo never hangs.
- Gemini cannot override deterministic action-tier policy.

## Secrets Handling

For the hackathon POC, `GEMINI_API_KEY` is passed as a Cloud Run environment variable.

Reasons:
- Fastest setup for a hackathon.
- Secret Manager is documented as the recommended production approach.
- API key is never committed to git.
- API key is never logged.

## Structured Logging

JSON structured logs with correlation IDs.

Reasons:
- Cloud Run logs integrate with Cloud Logging.
- `analysis_id` enables tracing a single request across vision, rule engine, and rendering.
- `mode` (mock/gemini/gemini_fallback) immediately tells what happened.
- `latency_ms` helps identify slow Gemini calls.
- Image bytes and secrets are never logged.
