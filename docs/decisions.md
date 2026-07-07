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
