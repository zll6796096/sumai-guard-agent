# Cloud Run Candidate And Release Evidence

This is an operator contract for evidence collection. It does not claim that a
candidate exists, that production matches this repository, or that any Cloud
Run or Apple gate has passed.

## Release topology

The release flow is deliberately split:

1. **Source:** create one exact implementation SHA and push it.
2. **CI:** obtain passing CI evidence bound to that exact SHA.
3. **Candidate:** run Cloud Build for that SHA. Cloud Build tests first, builds
   both containers, resolves each immutable digest, and creates uniquely tagged
   agent and web candidate revisions at 0% production traffic. It must prove
   that both production predecessors are unchanged and emit sanitized,
   identity-bound candidate evidence.
4. **Device:** use a real iPhone with `AppAttestProvider` and the approved
   synthetic sample. Bind the result to the exact agent candidate revision and
   retain only the sanitized device evidence contract.
5. **Promotion:** run the separate promotion checkpoint. Its default dry-run
   revalidates the source, candidate, immutable artifacts, service state,
   candidate probes, and real-device App Attest evidence without mutation.
6. **Production:** only an explicitly authorized apply run may change traffic.
   Re-probe both stable services and retain sanitized promotion evidence.
7. **Apple:** archive/signing, TestFlight processing, App Review submission,
   approval, manual release, propagation, and storefront visibility remain
   independent gates.

Candidate PASS is not promotion authorization. Production PASS is not archive,
review, release, or storefront PASS.

## Candidate configuration contract

The candidate is fail-closed and cannot use fallback analysis:

- the agent image and web image are deployed by immutable digest;
- each candidate tag remains at 0% production traffic;
- agent `APP_CHECK_REQUIRED=true`;
- agent `REQUIRE_REAL_GEMINI=true` and `MOCK_MODE=false`;
- web `PUBLIC_WEB_ANALYSIS_ENABLED=false`;
- the agent validates App Check before reading the multipart body;
- Gemini credentials use the pinned secret-backed source contract and are
  never copied into evidence; and
- candidate evidence contains only allowlisted identity, digest, revision,
  resource-version, predecessor, service-account, build, and status fields.

Local mock mode remains available through `.env.example` and Docker Compose.
It needs no Google or Firebase credentials and is not candidate or production
evidence.

## Candidate evidence acceptance

Before recording the candidate gate as PASS, the sanitized evidence must bind:

- exact source SHA and Cloud Build record;
- exact agent and web immutable digests;
- exact agent and web candidate revisions and candidate URLs;
- candidate tag and 0% traffic for both candidates;
- agent and web production predecessors before the build;
- unchanged production predecessors after candidate creation and probes;
- service resource versions before and after candidate creation;
- service-account identities matching the expected predecessor identities;
- agent `/health` and `/ready` returning the expected 200 JSON contracts;
- web `/`, `/ready`, `/privacy`, and `/support` returning 200, with
  `Cache-Control: no-store` on `/privacy` and `/support`;
- an unauthenticated native analysis attempt rejected by App Check before any
  request body is processed; and
- strict Gemini and disabled public web analysis read back from the candidate
  configuration without copying values or credential references into release
  documentation.

Cloud Build candidate success changes no production traffic and does not
perform a real-device call.

## Real-device gate

Device evidence must come from the native app on a real iPhone, use
`AppAttestProvider`, target the exact candidate agent URL and revision, return
the expected successful native response for the approved synthetic image, and
record an observation time plus the synthetic sample SHA-256. Simulator,
browser, curl, historic device, different revision, or user-skipped evidence is
not PASS.

The device evidence file must conform exactly to the promotion script's
allowlist. It must not contain tokens, headers, request/response bodies, image
content, report/action content, personal material, account identities, or
credentials.

## Separate promotion checkpoint

`scripts/promote-verified-candidate.sh` is the only promotion entrypoint. It
requires both candidate and device evidence even in default dry-run mode. The
dry run verifies exact `origin/main` binding, immutable artifact identity,
candidate and predecessor state, 0% candidate traffic, configuration shape,
candidate probes, and device freshness, then prints `mutation=NONE`.

Apply mode requires dual confirmation:

- `SUMAI_PROMOTE_APPLY=true`; and
- `SUMAI_PROMOTE_CONFIRM=PROMOTE_VERIFIED_SUMAI_CANDIDATE`.

It also requires an explicit safe output path for sanitized promotion evidence.
The apply path claims both services using the Cloud Run Admin API with the
current `resourceVersion`, making concurrent changes fail as a compare-and-swap
conflict. It rechecks ownership and source identity before each traffic change,
promotes the agent, probes its stable URL, creates a final web revision bound to
that stable agent URL, probes it at 0%, then promotes the web revision. On an
owned failure it attempts ownership-aware rollback; it refuses rollback when a
foreign lock, revision, or service identity makes mutation unsafe.

Promotion execution is outside this documentation task. Never infer an apply
run from source tests, dry-run output, candidate evidence, or an old production
revision.

## Strict read-only inspection

`scripts/check_cloudrun.sh` is not a deployment or promotion tool. All four
inspection targets are mandatory and must be supplied explicitly:
`GOOGLE_CLOUD_PROJECT`, `SUMAI_REGION`, `SUMAI_AGENT_SERVICE`, and
`SUMAI_WEB_SERVICE`. There are no region or service-name defaults. Every target
is validated before any `gcloud` or curl call. The script:

- calls only `gcloud run services describe` for the two validated services;
- summarizes sanitized service URLs, revision traffic percentages, latest
  created/ready revision names, bounded runtime shape, hashed service-account
  identities, and whether those identities are equal;
- sends GET only to agent `/health` and `/ready`, and web `/`, `/ready`,
  `/privacy`, and `/support`; each curl invocation starts by disabling user
  configuration, permits HTTPS only, follows no redirects, and sends no
  authorization header;
- requires HTTP 200, agent `/health` status `ok`, agent `/ready` status `ready`,
  and web `/ready` status `ok`;
- requires `Cache-Control: no-store` on `/privacy` and `/support`;
- never calls analysis, status aliases, logs, revision/secret/config listing,
  deployment, update, replacement, or traffic commands; and
- fails with a fixed safe error when a service is private, unreachable,
  malformed, or returns an unexpected contract.

Example read-only invocation (do not paste real target values into tracked
files):

```bash
GOOGLE_CLOUD_PROJECT=owner-approved-project SUMAI_REGION=owner-approved-region SUMAI_AGENT_SERVICE=owner-approved-agent-service SUMAI_WEB_SERVICE=owner-approved-web-service ./scripts/check_cloudrun.sh
```

Its output is inspection evidence only. It does not establish that App Check,
strict Gemini, or public web analysis settings match the candidate contract,
because the checker deliberately does not print environment values or secret
references. Those checks belong to sanitized Cloud Build candidate evidence.

## Retired direct mechanics and operational compatibility wrappers

Direct legacy deployment paths are retired: ad-hoc `gcloud run deploy`, service
update/replace, traffic update, mutable image tags, plaintext keys, and the
retired source-deployment workflow fail closed and are not release paths.

The compatibility wrappers remain operational.
`scripts/deploy_sumai_agent.sh` and `scripts/deploy_sumai_web.sh` reject partial
arguments and delegate to `scripts/deploy_all_cloudrun.sh`; they do not perform
an agent-only or web-only deployment. The paired entrypoint validates every
required input and a clean exact `main` and `origin/main`, then uses approved
WIF or otherwise valid `gcloud` authentication to submit a paired candidate-only
Cloud Build from the immutable source archive and exact `cloudbuild.yaml`. This is an
external candidate deployment: it can create both tagged 0% candidate
revisions and sanitized evidence. It does not change production traffic or
replace the separate device and promotion gates, but it still requires explicit
authorization before execution.

## Evidence hygiene

Release documentation may record sanitized hashes, immutable digests,
revisions, percentages, status, and evidence artifact hashes. Do not record
credentials, access or App Check tokens, service-account addresses, personal
email addresses, project numbers, Firebase app IDs, request/response bodies,
image or report content, private log material, signed URLs, or invented service
URLs. Cloud Logging retention and the owner-approved support contact must be
observed separately before privacy publication.
