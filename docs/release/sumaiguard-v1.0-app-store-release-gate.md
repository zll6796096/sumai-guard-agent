# SumaiGuard v1.0 App Store Release Gate

## Initial current-truth snapshot

This gate records only evidence that exists in the containing repository HEAD.
It is not a deployment report, release authorization, or claim about current
Cloud Run or App Store Connect state. Task 6 implementation is committed
locally on `main`, and the current release source is the containing repository
HEAD.

The earlier pushed and CI-tested source at `a84e85c` is superseded evidence: it
predates the candidate, promotion, retired-entrypoint, and Task 6 documentation
implementation. The historical reviewed precursor
`9d8716935299bbaa0bf87e647849fd1182d61d74` is also superseded by this
correction; it is not evidence that the containing repository HEAD has been
reviewed, pushed, or tested by CI. Neither historical source can clear any gate
below.

An exact release SHA cannot be written inside the commit it identifies because
embedding a commit's own SHA is self-referential. The exact release SHA will be
fixed and externally recorded only after push. Source push is not authorized by
this task, and no exact-head CI run exists for the containing repository HEAD.

Production mutation by this task: none; live state: unverified. “Unchanged” in
this document means this task performs no production mutation. It does not mean
the live control plane was inspected.

## Gate status

| Gate | Status | Current evidence and next acceptance boundary |
|---|---|---|
| Source implementation | IN PROGRESS | Task 6 is committed locally on `main`; the containing repository HEAD is the current source, while review of this correction and its external SHA record remain open. |
| Source push | NOT STARTED | The containing repository HEAD has not been pushed by this task. Record the externally visible exact release SHA only after a separately authorized push. |
| Exact-head CI | NOT STARTED | No exact-head CI run exists for the containing repository HEAD. Record the Exact CI run only after the pushed release SHA completes the required workflow. |
| Cloud Build candidate | NOT STARTED | No candidate build has run. Record the Exact Cloud Build record, immutable agent/web digests, source SHA, and sanitized build evidence only after candidate completion. |
| Real-device App Attest | NOT STARTED | No real-iPhone candidate call has run. Record the Exact device evidence hash, observation time, candidate revision binding, provider, response status, and approved synthetic-sample hash after acceptance. |
| Production promotion | NOT STARTED | No dry-run or authorized apply record exists. Record the Exact promotion evidence hash and the candidate/device evidence bindings after the separate checkpoint. |
| Production state | BLOCKED | Production mutation by this task: none; live state: unverified. Record exact predecessor and promoted revisions plus post-promotion probes only after an authorized apply run. |
| Archive and signing | NOT STARTED | No release archive exists. Record the Exact archive evidence hash, source SHA, marketing version, build number, signing result, and export validation after archive acceptance. |
| TestFlight upload | NOT STARTED | No upload or processing evidence exists for this release. Record the exact uploaded build and processing result after upload acceptance. |
| App Review submission | NOT STARTED | No review submission evidence exists. Record the Exact review evidence only after the accepted build and metadata are submitted. |
| App Review approval | NOT STARTED | No approval evidence exists. Approval is independent of submission and upload. |
| Manual release | NOT STARTED | No release action or propagation evidence exists. Record the Exact release evidence only after approval and explicit release authorization. |
| Storefront visibility | NOT STARTED | No Japan storefront observation exists. Record the Exact storefront evidence, observed version/build, country storefront, and observation time only after public visibility. |

## Evidence fields

Absence is stated explicitly instead of using placeholder identifiers.

| Evidence field | Status | Current record |
|---|---|---|
| Exact source SHA | IN PROGRESS | The containing repository HEAD is the current local release source. Its exact release SHA will be fixed and externally recorded only after push; it cannot be embedded in its own commit. |
| Exact CI run | NOT STARTED | No exact-head CI record exists. |
| Exact Cloud Build | NOT STARTED | No candidate build record exists. |
| Exact candidate evidence | NOT STARTED | No sanitized candidate evidence artifact exists. |
| Exact agent revision | NOT STARTED | No Task 6 candidate revision is recorded. |
| Exact web revision | NOT STARTED | No Task 6 candidate revision is recorded. |
| Exact device evidence | NOT STARTED | No real-device evidence artifact exists. |
| Exact promotion evidence | NOT STARTED | No promotion evidence artifact exists. |
| Exact archive evidence | NOT STARTED | No archive artifact or validation record exists. |
| Exact review evidence | NOT STARTED | No review submission or decision record exists. |
| Exact release evidence | NOT STARTED | No manual-release or propagation record exists. |
| Exact storefront evidence | NOT STARTED | No storefront observation record exists. |

## Gate acceptance rules

- **Source** requires the exact final SHA and a reviewed diff limited to the
  authorized scope.
- **CI** requires a successful run for that exact pushed SHA; the earlier
  `a84e85c` result remains superseded evidence.
- **Candidate** requires immutable digests, tagged agent and web revisions at
  0% production traffic, unchanged predecessors, strict Gemini, App Check, web
  analysis disabled, safe probes, and sanitized evidence.
- **Device** requires current real-device `AppAttestProvider` evidence bound to
  that exact agent revision. Simulator, browser, curl, older build, or skipped
  evidence does not pass.
- **Promotion** is separate from candidate and device. Default dry-run must
  pass first; apply requires dual confirmation and explicit authorization.
- **Production** requires ownership-preserving Cloud Run Admin API
  `resourceVersion` compare-and-swap, successful stable probes, sanitized
  evidence, and a safe rollback result if a mutation fails.
- **Apple distribution** keeps archive/signing, TestFlight upload/processing,
  App Review submission, approval, manual release, propagation, and storefront
  visibility separate. No earlier PASS implies a later PASS.

## Current decision

Release remains BLOCKED. No external action is authorized by this task. After a
separately authorized push, record the exact release SHA externally and wait
for exact-head CI before starting the candidate gate. Nothing in this snapshot
authorizes Cloud Build, a real-device call, production promotion,
archive/upload, review submission, manual release, or storefront publication.
