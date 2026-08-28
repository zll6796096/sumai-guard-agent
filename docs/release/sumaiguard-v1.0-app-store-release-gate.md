# SumaiGuard v1.0 App Store Release Gate

## 2026-08-28 corrective update

Builds 1 and 2 were automatically rejected with `ITMS-90111: Unsupported SDK
or Xcode version`; this was binary validation, not substantive App Review.
Both uploads were produced after this Mac moved to macOS 27 beta. Apple lists
Xcode 26.6 as supported on production macOS 26.2–26.x, while Xcode 27 beta is
currently accepted only for TestFlight. Local release archive and upload are
therefore prohibited on the current boot volume.

Build 3 changes only the build identity and the fail-closed signing contract.
The app and test targets now require team `YMUG864233` with automatic signing.
The release archive, Apple-managed signing, and App Store Connect distribution
must run through the same stable Xcode Cloud pattern that cleared the equivalent
LifeSnap toolchain failure. Xcode Cloud setup, archive, processing, association,
and App Review submission remain pending at this snapshot.

## Current-truth snapshot

This record separates source readiness, Cloud Run state, Apple binary
processing, review submission, approval, manual release, propagation, and Japan
storefront visibility. A PASS at one gate does not imply a later gate passed.

The original release application source remains merged through PR #7 at
`7bcdbb18321c4c31aa749170f57584024057e924`, with its historical candidate,
real-device, and production-promotion evidence retained below. The active
Build 3 correction is scoped to build identity, automatic signing, validation,
and Xcode Cloud release orchestration; it does not change product behavior.

App Store Connect record `6799968189` uses the approved public name
`実家あんしんチェック`, Japanese primary language, bundle ID
`com.zll.sumaiguard`, SKU `SUMAIGUARD-IOS-1`, and Japan-only free availability. Review contact details,
listing metadata, privacy answers, export compliance, and manual-release mode
were sufficient to submit Build 2. Build 2 is now rejected by automatic binary
validation, so Build 3 processing and association are the next Apple gates.

## Gate status

| Gate | Status | Current evidence and next acceptance boundary |
|---|---|---|
| Local source and listing assets | PASS | Two focused commits contain the Japanese listing, privacy disclosures, review notes, public privacy/support pages, five validated 1320×2868 screenshots, and a DEBUG-only screenshot harness. |
| Local verification | PASS | Fresh Build 3 run: backend 588 passed, candidate-promotion 116 passed, deployment-entrypoint 35 passed, native release controls 60 passed, frontend import passed, and Compose validation passed. A local Xcode 26.6 simulator launch is not accepted as release evidence because the host is macOS 27 beta; Xcode Cloud must run the native build/test/archive gate. |
| App Store Connect record | BLOCKED | App ID `6799968189`, version 1.0. Build 2 is rejected by automatic ITMS-90111 validation; Build 3 is not yet present. |
| Apple capability and profile | PASS | App Attest is enabled; the distribution identity and App Store profile produced a validated distribution-signed Build 1 IPA. |
| Source push | PASS | PR #7 merged the release branch to remote `main`; exact release application source is `7bcdbb18321c4c31aa749170f57584024057e924`. |
| Exact-head CI | PASS | GitHub Actions run `31396624070` passed backend and iOS jobs for exact merged `main` SHA `7bcdbb18321c4c31aa749170f57584024057e924`. |
| Cloud Build candidate | PASS | Regional Cloud Build `b6596ba5-d920-461a-8361-14baddddfa5b` succeeded. Agent `sumai-agent-7bcdbb1-b659` and web `sumai-web-7bcdbb1-b659-can` used the dedicated runtime accounts, passed safe probes, and were both at 0% when sanitized evidence was written with `production_traffic_changed: false`. The tracked evidence URI is redacted as `gs://<project-id>-sumai-release-evidence/candidates/7bcdbb18321c4c31aa749170f57584024057e924/b6596ba5-d920-461a-8361-14baddddfa5b.json`. |
| Real-device App Attest | PASS | The paired physical iPhone completed the selected `AppAttestProvider` round trip against `sumai-agent-7bcdbb1-b659`: 1 test, 0 failures, HTTP 200. The sanitized device evidence SHA-256 is `f75037731da65d007687132fef7246bfd6f4245c852c5c2c31d0b083c8c69555`; it contains no token, photo, response body, or device identifier. |
| Production promotion | PASS | The exact candidate/device dry-run passed with `validation=PASS` and `mutation=NONE`; the separately authorized apply produced promotion evidence SHA-256 `05b5de9c01b89cc6b5c645bce693ac62913f5d4340ff79761b0d160365c3899b`. Fresh inspection shows agent `sumai-agent-7bcdbb1-b659` and web `sumai-web-final-7bcdbb1-b659-58e1e1b75e` at 100%, with all required public probes passing. |
| Archive and signing | IN PROGRESS | Earlier local archives are not reusable after ITMS-90111. Build 3 must be archived and signed by the stable Xcode Cloud workflow. |
| IPA upload and processing | BLOCKED | Build 2 reached App Store Connect but was invalidated by ITMS-90111. Build 3 cloud archive, distribution, and processing have not started. |
| Metadata and privacy answers | PASS | The Build 2 submission proved the listing, international-format review contact, privacy answers, export compliance, screenshots, Japan-only availability, and manual-release selection were saved. Reverify unchanged values before submitting Build 3. |
| App Review submission | AWAITING CHECKPOINT | The Build 2 submission was rejected by binary validation. Build 3 requires successful cloud processing and association, followed by separate action-time confirmation. |
| App Review approval | NOT STARTED | Approval is independent of submission and upload. |
| Manual release | AWAITING CHECKPOINT | Manual release is selected on the unsaved version page; save it after the required review phone is supplied. The final release action still requires explicit authorization after approval. |
| Japan storefront visibility | NOT STARTED | Record the public URL, observed version/build, Japan storefront, and observation time only after visibility is confirmed. |

## Known live-state evidence

- Candidate build evidence proves that production stayed on
  `sumai-agent-5a44215-738e` and `sumai-web-5a44215-738e-fin` while the exact
  `7bcdbb1` candidates were created at 0%.
- The later promotion moved agent production to `sumai-agent-7bcdbb1-b659` and
  web production to `sumai-web-final-7bcdbb1-b659-58e1e1b75e`.
- On 2026-08-11, each service had exactly one 100% revision, the dedicated
  service-account hashes remained distinct, and agent `/health` and `/ready`
  plus web `/`, `/ready`, `/privacy`, and `/support` returned 200.
- The failed GitHub Actions run `31394541871` stopped before checkout or Cloud
  Build because keyless repository configuration was absent. It is not success
  evidence and is separate from the later successful regional Cloud Build.

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

Product/backend readiness and the earlier production-promotion evidence remain
separate from Apple binary acceptance. Build 3 source controls are green, but
no valid Build 3 archive or upload exists yet. The next authorized action is to
push the scoped Build 3 source branch and configure one stable Xcode Cloud
archive/distribution run. Apple processing, build association, App Review
submission, approval, manual release, propagation, and Japan storefront
visibility remain distinct later gates.
