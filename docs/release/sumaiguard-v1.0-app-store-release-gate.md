# SumaiGuard v1.0 App Store Release Gate

## Current-truth snapshot

Observed on 2026-08-10 JST. This record separates local source readiness,
Cloud Run release state, Apple distribution, review, approval, manual release,
and Japan storefront visibility. A PASS at one gate does not imply any later
gate has passed.

The release source is the containing HEAD of the local branch
`codex/sumaiguard-app-store-release`, based on
`a95c4acea0304ce609f6471edc67ade1e79c3eff`. The two App Store implementation
commits end at `de37d0b821ea4be0d8df497b575bf9309b15d997`; this evidence-only
snapshot follows them. The branch is not yet pushed, so its externally visible
exact release SHA must be recorded after push rather than self-embedded in this
commit. The working tree was clean before this snapshot update.

App Store Connect record `6799968189` now exists with the approved public name
`実家あんしんチェック`, primary language Japanese, bundle ID
`com.zll.sumaiguard`, SKU `SUMAIGUARD-IOS-1`, and unrestricted user access.
Version 1.0 is in `提出準備中`. This proves record creation only; no build,
metadata submission, review decision, release, or storefront visibility exists.

Apple Developer shows App Attest enabled for `com.zll.sumaiguard` and a valid
Apple Distribution identity is installed locally. No SumaiGuard App Store
provisioning profile is currently present in the developer portal, so archive
signing must create or install one before archive acceptance.

## Gate status

| Gate | Status | Current evidence and next acceptance boundary |
|---|---|---|
| Local source and listing assets | PASS | Two focused commits contain the Japanese listing, privacy disclosures, review notes, public privacy/support pages, five validated 1320×2868 screenshots, and a DEBUG-only screenshot harness. |
| Local verification | PASS | Backend: 588 passed. Release/native/script checks: 65 passed. Xcode tests: 168 passed, 0 failed, 1 physical-device-only App Attest test skipped. Debug and Release simulator builds passed; the Release product contains no screenshot-harness marker. |
| App Store Connect record | PASS | App ID `6799968189`, version 1.0 `提出準備中`; record fields match the approved name, language, bundle ID, SKU, and access scope. |
| Apple capability and profile | IN PROGRESS | App Attest is enabled and the Apple Distribution identity exists. SumaiGuard has no App Store provisioning profile yet; create/install it during the archive-signing step. |
| Source push | NOT STARTED | Push the exact release branch and record the externally visible SHA. |
| Exact-head CI | NOT STARTED | Run the required workflow on the exact pushed release SHA. Historical CI for `a95c4ac` does not validate the two App Store commits. |
| Cloud Build candidate | NOT STARTED | Build immutable agent/web candidates from the exact release SHA and keep them at 0% production traffic. |
| Real-device App Attest | NOT STARTED | Obtain current real-iPhone evidence bound to the exact candidate revision. Xcode/TestFlight usability testing alone does not prove this release candidate gate. |
| Production promotion | AWAITING CHECKPOINT | Current production remains on the predecessor revisions. Apply only after an explicit promotion confirmation, successful dry-run, exact candidate/device bindings, and rollback evidence. |
| Archive and signing | NOT STARTED | No accepted release archive exists. Record source SHA, version/build, profile, signing result, and export validation. |
| IPA upload and processing | AWAITING CHECKPOINT | No build has been uploaded for App ID `6799968189`. Upload requires a separate explicit confirmation after archive acceptance. |
| Metadata and privacy answers | IN PROGRESS | Japanese copy, privacy-label draft, review notes, and screenshots exist locally; they are not yet saved in App Store Connect. |
| App Review submission | AWAITING CHECKPOINT | Submission requires an accepted processed build, completed metadata/privacy/export answers, manual-release selection, and separate explicit confirmation. |
| App Review approval | NOT STARTED | Approval is independent of submission and upload. |
| Manual release | AWAITING CHECKPOINT | App Store Connect currently defaults to automatic release; change it to manual before submission. The final release action requires explicit authorization after approval. |
| Japan storefront visibility | NOT STARTED | Record the public URL, observed version/build, Japan storefront, and observation time only after visibility is confirmed. |

## Known live-state evidence before mutation

- Production agent traffic was 100% on `sumai-agent-5a44215-738e`.
- Production web traffic was 100% on `sumai-web-5a44215-738e-fin`.
- Earlier 0%-traffic candidates were `sumai-agent-a95c4ac-774c` and
  `sumai-web-a95c4ac-774c-can`; they predate the two App Store commits and are
  not candidates for the exact release SHA.
- The earlier production agent returned 404 for `/health` and `/ready`; the
  earlier production web returned 404 for `/privacy` and `/support`.
- The earlier candidates returned 200 for `/health`, `/ready`, `/privacy`, and
  `/support` as applicable. These observations do not authorize promotion.

## Acceptance rules

- **Source** requires a reviewed, focused diff, clean working tree, exact pushed
  SHA, and successful exact-head CI.
- **Candidate** requires immutable digests, 0%-traffic revisions, unchanged
  predecessors, strict Gemini, App Check, web analysis disabled, safe probes,
  and sanitized evidence.
- **Device** requires current real-device `AppAttestProvider` evidence bound to
  the exact candidate agent revision. Simulator, browser, curl, historic phone
  testing, or skipped evidence does not pass.
- **Promotion** requires a passing dry-run followed by explicit authorization,
  ownership-preserving `resourceVersion` compare-and-swap, stable probes, and
  rollback readiness.
- **Archive/upload** requires a distribution-signed archive from the exact
  source, valid profile/export checks, separate upload authorization, and
  successful App Store Connect processing.
- **Review** requires complete metadata, privacy and export declarations,
  screenshots, review contact/notes, accepted build, manual-release selection,
  and separate submission authorization.
- **Public release** requires Apple approval followed by explicit manual-release
  authorization. Storefront visibility is verified separately after propagation.

## Current decision

The App Store record and local submission package are ready, but public release
is not yet complete. The next safe action is to push this exact branch, obtain
exact-head CI, create exact-SHA 0%-traffic candidates, and collect real-device
App Attest evidence. Production promotion remains stopped at its explicit
checkpoint. IPA upload, App Review submission, and manual release remain
separate later checkpoints.
