# SumaiGuard UI-only Waiting Experience Design

## Objective

Improve the perceived waiting time after a photo is selected while keeping the
restored analysis backend and response semantics unchanged. The release must
remain a one-photo, real-Gemini safety check that renders the existing annotated
image, improvement image, and three action tiers.

## First-principles boundary

- The real goal is reducing uncertainty during a necessary wait, not pretending
  that analysis is faster than it is.
- The browser may present local waiting guidance, but it must not invent a
  precise completion percentage or claim that an unobserved backend stage has
  completed.
- The browser must make exactly the existing `POST /analyze` request. It must not
  poll, open a stream, use WebSocket/EventSource, or send telemetry.
- No file below `apps/sumai_agent/app/`, no knowledge base, rule, model, API,
  dependency, environment variable, or Cloud Run setting may change.

## User experience

After the user chooses a photo, the existing analysis screen remains visible
with the selected image. Beneath it, the UI shows:

1. An indeterminate progress rail with a calm moving indicator and no numeric
   percentage.
2. A short status sentence that advances according to local elapsed time:
   photo preparation, safety review in progress, and result preparation.
   These are waiting messages, not backend completion claims.
3. A non-interactive safety-tip card that rotates locally every six seconds.
   Tips cover lighting, clear walking routes, dry floors, and keeping frequently
   used items within easy reach.
4. A longer-wait note after 24 seconds explaining that some photos take longer
   and asking the user to keep the page open.

When the existing request resolves, all waiting timers stop before the current
result renderer runs. When it fails or the user returns home, timers also stop
and the existing error behavior remains authoritative.

## Accessibility and resource use

- Status changes use `role="status"` and `aria-live="polite"`.
- The tip card is readable but not a live region, avoiding repeated screen-reader
  interruptions.
- `prefers-reduced-motion: reduce` disables the moving animation and transitions.
- Font sizes, contrast, and touch targets retain the current elderly-first UI.
- Only CSS animations and browser timers are used; no additional backend or
  network resources are consumed.

## Files and scope

- Runtime modification: `apps/sumai_web/app.py` only.
- Contract tests: `apps/sumai_agent/tests/test_frontend_contract.py` only.
- Documentation: this design and its implementation plan.

The test file is not backend runtime code. It only imports `INDEX_HTML` and
locks the frontend contract.

## Acceptance criteria

- The waiting UI contains an indeterminate progress rail, rotating safety tips,
  and a delayed long-wait message.
- No percentage is displayed and no progress value is exposed as if measured.
- The page still contains exactly one analysis request path and no streaming or
  polling transport.
- Waiting timers are cleared on success, failure, and home reset.
- The existing result renderer still exposes annotated and improvement images
  and all three action tiers.
- Git path audit shows no backend runtime changes.
- Full tests, frontend import, and Compose validation pass.
- A real production photo returns non-empty annotation, improvement, and action
  outputs after deployment.
- Cloud Build succeeds and both Cloud Run services route 100 percent traffic to
  the new revision.
- The accepted release is tagged `sumai-ui-fixed-2026-07-31`.

## Explicitly out of scope

- Backend streaming or progress events.
- Analysis speed, Gemini prompts, ontology, risk rules, bounding boxes, and
  improvement-image logic.
- New persistence, analytics, authentication, or uploaded-image storage.
- Any redesign of the completed result or action-plan semantics.
