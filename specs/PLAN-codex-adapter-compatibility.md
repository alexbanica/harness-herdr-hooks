# PLAN — Codex adapter compatibility

Status: Approved

Approved by the user's explicit response `approve` on 2026-11-22.
Reviewed proposed revision SHA-256 `2be0b9b9f10ab8120284cd8e46d925c7a770bbda5368b440d3efe117b7993a6a`.

## Authority and delivery

Implement the [approved SPEC](SPEC-codex-adapter-compatibility.md), SHA-256
`fda49560889d45d7a160ca9647521c0ab3c9d34d607a60a050cc2c7b731651e0`.
The delta replaces Codex release gating with required protocol and identity
checks. The [lifecycle SPEC](SPEC-codex-herdr-session-lifecycle.md) and
[PLAN](PLAN-codex-herdr-session-lifecycle.md), the
[creation-events SPEC](SPEC-codex-standalone-creation-events.md) and
[PLAN](PLAN-codex-standalone-creation-events.md), and the session-subagent-tabs
SPEC and PLAN on the base retain their original approval and content. Preserve
their existing attachment, ownership, pane placement and cleanup rules.

Use new branch `feat/codex-adapter-compatibility` on remote `origin` in
`/tmp/agent-worktrees/harness-herdr-hooks/codex-adapter-compatibility`. Pin
`origin/feat/session-subagent-tabs` at
`09a31ca68d4cbba1ecb7e927fa3343a53871871c`, the diagnosed installed revision
which also contains the main baseline. This stacked delivery keeps the tab
feature available for verification without changing its existing branch or the
installed worktree. Refresh the named reference and verify the exact SHA
before editing. A mismatch requires an amendment. Verify the new branch is
absent locally and remotely before creation and verify the approved artifacts
byte-for-byte when transferring them from the invoking checkout. Keep the
invoking checkout and its unrelated untracked work intact.

Parent owns worktree, isolated validation, acceptance, staging, commit and push.
Start detached at the verified base in the named isolated worktree. Create the
named branch immediately before the first authorized commit after checking
that it is absent locally and unattached. Commit the accepted source, tests,
docs and transferred artifacts and push without force to
`origin/feat/codex-adapter-compatibility`. Verify its exact remote SHA, upstream
and committed artifact contents, then release the branch attachment under the
implement lifecycle. No merge, live install, daemon restart, hook trust change
or current-pane mutation is authorized. Availability on main depends on later
integration of the stacked change.

## Units and dependencies

| Unit | Owner and paths | Behavior and verification |
| --- | --- | --- |
| U1 | Developer owns `src/harness_herdr_hooks/adapters/codex.py` and `tests/test_codex_events.py`, `tests/test_tab_hooks.py` | Update the version-pin tests first. Accept arbitrary, missing and unfamiliar version metadata after successful initialization. Preserve the local transport and identity checks and existing call/response validation. At the adapter boundary, give bounded failure reasons and the daemon version where available. Test an intact handshake for `0.170.0`, `0.171.0`, future and unknown versions, and invalid transport, profile, method and required response cases. |
| U2 | Parent and read-only QA after U1, no owned source files | Verify the integrated diff and run the commands below. Exercise the updated adapter against the local `0.171.0` daemon using a separately connected, read-only client. |
| U3 | Documentation writer after U2 owns `docs/install-codex.md`, `docs/troubleshooting.md`, `docs/isolation.md`, `docs/contracts.md` and `docs/validation.md` | Explain required interface, observed releases and bounded errors. Distinguish handshake and metadata evidence from the known shared-daemon pane identity failure. Retain historical release evidence. |
| U4 | Parent after U3 owns delivery, no additional source | Reconcile approved paths and evidence, stage reviewed files only, then commit and verify push as specified above. |

U1 diagnostics fixtures assert acceptance of extra fields in valid replies.
For incompatible replies, assert the diagnostic names the failing stage or
method and the available daemon version. Inject sentinel credentials,
transcript text and an oversized server message into fixture responses, then
assert the diagnostic is bounded and excludes each sentinel and raw message.
Use existing adapter errors where they already meet these requirements.

In `tests/test_tab_hooks.py`, exercise the Codex hook gateway with fake
transport and Herdr effects. For incompatible transport, profile mismatch,
missing method, and malformed required response, drive each failure through
the installed adapter path and assert observer startup, tab creation, pane
attachment and cleanup are not called. With a valid newer version and with
unknown version metadata, separately deny endpoint/incarnation mismatch,
wrong thread, unverified ancestry, and missing or foreign ownership at the
relevant gateway or existing ownership boundary. Assert zero effects for
each denied case. Keep the older-version success path as a positive control.
U2 records these assertions and their fixture outcomes alongside the native
read-only probe.

Use the existing WebSocket exchange and read-only methods. Treat initialization
and operation-specific response validation as compatibility checks. Do not send
new probing operations that create turns or change a session. Keep existing
checks for profile, socket incarnation, exact thread and ancestry, pane ownership
and existing effect ordering. Inspect only these direct implementation paths and
existing validation patterns. Serialize developer integration, review, QA, docs
and delivery. Apply five-minute native assignment limits.

## Assurance and commands

Full assurance applies because the eligibility change affects an external native
dependency used during verified pane routing. The change has one technical
integration scope, with no interacting business domains. Independent PLAN
readiness review is required. Architect plan assurance is inapplicable.
Implementation requires independent integrated code review, one consolidated
correction batch, affected validation, read-only QA, then documentation
synchronization. No API operation or event contract is added, changed or
removed. Contract review is inapplicable. No separate security review was
requested. Preserve boundary checks during integrated review.

From the isolated worktree:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /usr/bin/python3 -m unittest -q test_codex_events test_tab_hooks
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -q
git diff --check
```

For the live check, use the installed profile metadata to identify the genuine
Codex executable and the owned target of
`~/.codex/app-server-control/app-server-control.sock`. Use the isolated
worktree's unmodified-at-runtime adapter, including its real initialization
and identity checks. Confirm the peer reports `0.171.0`, then perform
`thread/loaded/list` and a metadata-only `thread/read` of the first returned
loaded ID. Confirm the response matches that ID without emitting thread
contents. Use host access if the sandbox cannot read the local socket. No
synthetic hook is sent to the live daemon. Record unavailable prerequisites,
intermittent failures and the results of focused reruns. Do not treat a rerun
as evidence that a confirmed regression was corrected.

## Requirement-to-delivery trace

| Approved SPEC anchor | Unit and evidence |
| --- | --- |
| Scope bullets 1–2 and acceptance 1 | U1 adapter/version fixtures. U2 verified local initialization and metadata on 0.171.0. |
| Scope bullets 3–4 and acceptance 2 | U1 response-extension, diagnostic bounds and redaction, and effect-spy and ownership fixtures. U2 integrated review and explicit per-case QA evidence. |
| Scope bullet 5 and preserved predecessor behavior | U1 bounded diff. U2 review of unchanged pane authority and existing regression suite. Shared-daemon identity repair, Herdr/OpenCode changes and live attachment are outside this plan. |
| Acceptance 3 | U2 focused, full suite and read-only real daemon probe with exact build and results. |
| Acceptance 4 | U3 specified operator docs, checked against final source and U2 evidence. |
| Artifact and delivery integrity | U4 exact reviewed staging and verified non-force push. |

## Completion and recovery

Complete when the approved behavior, independent review, focused/full tests,
required live read-only probe, documentation and verified push are all evidenced.
Stop with specific unmet criteria for a base mismatch, unsafe checkout, failed
required check, unavailable live prerequisite or non-fast-forward delivery.
Complete independent in-scope work first. Where safe, deliver verified partial
work to the authorized branch as DRAFT under the implement lifecycle. A
checkpoint or qualified rerun does not end the remaining approved lifecycle.

## Plan assurance evidence

Independent readiness review inspected the initial draft at SHA-256
`83335bd99cca2f62a01880da881c37af30c20e8a8dda0bbb2f3c9359b0820276`,
the approved SPEC, and base `09a31ca`. The reviewer identified two coverage
gaps. This revision adds end-to-end negative fixtures with effect assertions
and names their owner and commands. It also adds tests and trace entries for
response-extension acceptance and bounded diagnostics with redaction.
