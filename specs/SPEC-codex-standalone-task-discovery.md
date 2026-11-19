# SPEC: Discover agent-created standalone Codex tasks

Status: Approved

- ID: HHH-003
- Date: 2026-11-19
- Authority: User invoked `spec-plan` to make the hook also launch for a
  standalone Codex task, then requested an explorer investigate the task that
  another agent had attached manually. This is planning authority only.
- Research checkout: `main`, `e4ee497cb1c8d2273d2487c4e932b27ea398a580`.
- Predecessors: [HHH-001 SPEC](SPEC-harness-herdr-hooks.md),
  [HHH-001 PLAN](PLAN-harness-herdr-hooks.md),
  [HHH-002 SPEC](SPEC-codex-herdr-session-lifecycle.md), and
  [HHH-002 PLAN](PLAN-codex-herdr-session-lifecycle.md).
  Preserve these artifacts and their approval records. HHH-002 PLAN A1 is
  pending; this proposal neither approves it nor authorizes concurrent repair.

## Purpose and evidence

An agent-created standalone task should appear automatically in an unfocused
pane of the originating session's existing Herdr tab. Attach the task that
already exists; do not launch another task or repeat its prompt.

The missed task was created by `mcp__codex_tui__create_thread`, rather than a
native subagent spawn. The observed parent was
`01a1f353-39a2-7bc1-84b8-5d36081e51e2`; the returned task was
`01a1f406-a89a-7ac3-ae66-1db305e17eb8`. Its own metadata had no native parent
link. The creation response recorded `codexDelegation.sourceThreadId` equal
to the originating parent. Subsequent manual native remote resume attached
that exact task in Herdr pane `w5:p8`, tab `w5:t1`, while preserving the parent.
These IDs are historical evidence, never configured discovery targets.

Current discovery filters `thread/list` to `subAgentThreadSpawn` and attachment
rechecks native spawn ancestry (`adapters/codex.py`, `list_threads`,
`_is_native_child`, `sessions`, and `can_attach_now`). Relaxing the listing
filter alone cannot establish a standalone task's intended parent.

Independent read-only exploration found the successful creation result in the
parent's local rollout JSONL, at records around 2026-11-19 13:37:12–13:37:24 UTC.
It is nested in a correlated `exec` call/output, not a top-level native subagent
event. The inner result contains a returned `thread.id` and a
`functionCallOutput` item with `name: create_thread`, `namespace: codex_tui`,
and `codexDelegation.sourceThreadId`. The outer result has `isError: false`.
Manual attachment evidence is at 13:39:41–13:40:32 UTC in the same parent rollout.

## Scope, definitions, and decisions

- **Standalone task:** a new task returned by a successful
  `mcp__codex_tui__create_thread` invocation from a verified Herdr-bound parent.
  It remains a separate session, not a native subagent.
- **Creation association:** the matched creation call/result plus its returned
  parent and child IDs. It nominates a task for independent backend verification;
  it is not native ancestry and cannot bypass identity checks.
- **Supported capture:** a version-qualified adapter for the observed local
  parent rollout format, driven by the integration's automatic observer.
  Bootstrap remains automatic; no manually started watcher or agent follow-up
  command is required. This proposal deliberately permits reading the minimum
  creation-related transcript records needed for association.
- Qualification target: the observed Codex CLI 0.170.0, local Codex app/TUI
  rollout envelope, and Herdr 0.9.5/protocol 22 on Linux/WSL. CLI version alone
  does not qualify the app format; actual envelope and parent-file binding must
  pass validation. Unsupported formats fail closed with a bounded diagnostic.
- Codex 0.170.0 has a native `PostToolUse` schema, but delivery for this
  app-owned tool is unverified. The required solution must work through the
  qualified parent-record adapter without depending on such delivery. This
  change does not introduce a second speculative discovery path.
- Standalone panes are retained through idle, completion, and client exit,
  consistently with HHH-002 separate-session behavior. They are not subject to
  native subagent automatic closure.

Exclude arbitrary API-created roots, tasks created outside an observed verified
parent, `codex exec`, forks/resumes of old tasks, shell-launch routing changes,
remote hosted backends, broad historical session backfill, OpenCode changes,
new platforms, and client/server product changes outside this repository.
Do not modify the Codex app, monkey-patch its tools, or execute transcript input.

## Required behavior and invariants

### R1 — Bind observation to the exact parent

Automatically observe only the current verified parent's local rollout, bound
to its selected profile, session ID, existing backend incarnation, and current
Herdr server/pane/tab. Validate file ownership, canonical path, regular-file
identity, and session metadata before consuming records; reject unsafe links
and mismatches. Inherited pane markers, cwd, timestamps, titles, and a shared
backend alone never establish the association. If the correct parent file
cannot be established, skip automation with a useful bounded reason.

### R2 — Recognize a successful creation result

Correlate newly observed creation-related call and completed result records by
call ID. Support the observed nested `exec` result envelope and require its
successful result state, returned child thread ID, exact structured
`functionCallOutput` create_thread/codex_tui identity, and matching
`codexDelegation.sourceThreadId`. Interpret these fields as a candidate
association, then apply R3. Never search arbitrary messages for session IDs,
execute or evaluate the recorded JavaScript, or accept a title/status/cwd
coincidence as creation evidence. Reject ambiguous, conflicting, failed,
incomplete, or unsupported envelopes. A textual lookalike alone cannot pass
the complete call/result and backend validation chain.

### R3 — Verify both sessions independently before attachment

Revalidate the exact parent binding and fetch the exact candidate task from
that parent's verified selected-profile backend. Require consistent task
identity, same backend incarnation, and positive running/attachable evidence.
The returned cwd must agree with verified task metadata before use. Do not
fabricate native ancestry or weaken native subagent checks. Missing metadata
permits bounded deferred verification, never speculative attachment. A task
already finished before attachment opens no pane. Foreign/mismatched tasks
are rejected and no other backend is searched to make the candidate fit.

### R4 — Attach the existing task exactly once

Create one unfocused pane in the verified parent's current tab and attach the
existing task on its owning backend, using native existing-session attachment.
Do not send its initial prompt again, create a replacement task/backend, start
another inference turn, or change model or permissions. Reuse an independently
verified existing display of that exact task instead of duplicating it; such
reuse grants no pane ownership or close authority. Respect manual pane closure.
Preserve one-way title sanitation/synchronization. Revalidate destination and
ownership across creation and attachment races.

### R5 — Preserve standalone lifecycle

Keep attached standalone panes through task completion, idle, failure,
cancellation, and client exit, leaving a usable shell on exit. Never apply
native subagent completion cleanup to this association type. Display clients
must not recursively trigger discovery or create additional panes.

### R6 — Bound reading, restart recovery, and duplicate suppression

Track incremental parent-record position and minimum creation association state
in private integration-owned storage. Initial observation establishes a boundary
without backfilling pre-existing tasks. Retain incomplete newly observed call
correlations across restart; replay after a crash must not duplicate attachment.
Handle split writes, duplicate results, concurrent observers, delayed backend
metadata, and parent-record replacement/truncation with bounded work and explicit
safe recovery. Uncertain gaps are not permission to scan all historical sessions
or open old tasks. Persist only required IDs, file/cursor identity, backend/pane
bindings, and outcome/retry state; never persist prompt, preview, conversation
text, `codexDelegation.input`, or bulk tool output. Logs must not contain them.

### R7 — Preserve unrelated behavior and expose qualification

Preserve HHH-002 default-daemon verification, explicit endpoint precedence,
ordinary interactive launch routing, native subagent lifecycle, profile/harness
isolation, and owned-only installation/uninstallation. Outside Herdr, perform
no pane automation. Status/troubleshooting must distinguish observer health,
supported creation-record recognition, successful backend verification, and
actual attachment. Unknown formats, inaccessible parent files, and rejected
associations need bounded actionable diagnostics without secrets or transcript
contents. No native daemon restart, unrelated configuration change, deployment,
release, merge, or commit/push is authorized by this Proposed specification.

## Delta and preserved predecessors

HHH-003 narrowly replaces HHH-002's exclusion of arbitrary API-created root
sessions for the specifically observed app-owned create_thread mechanism and
validated creation association. Other root-session origins remain excluded.
It supplements native discovery with a separate association type; it does not
turn every root into a subagent or replace native ancestry. It permits minimum
creation-result transcript processing, while preserving the ban on using
conversation content to infer relationships and on retaining such content.

HHH-001/002 approved content remains unchanged. Integration must preserve
concurrent predecessor work; the eventual PLAN must pin a compatible delivered
HHH-002 baseline and resolve ownership before source changes. This proposal
does not grant approval to HHH-002's pending PLAN amendment or certify any
predecessor runtime acceptance.

## Acceptance, regression, and validation

- **A1 (R1–R3):** A sanitized fixture derived from the observed nested result
  yields the exact parent/child pair. Partial writes, multiple calls/results,
  mismatched call IDs, wrong sourceThreadId, error results, lookalike message
  text, unsupported formats, unsafe files, and foreign backend/profile IDs
  cannot cause attachment. No prompt/body retention or diagnostic leakage.
- **A2 (R3–R4):** Positive native metadata is required. Unknown/delayed status,
  completion before attachment, changed parent/tab/backend, and existing display
  races produce bounded safe outcomes without duplicate sessions or panes.
- **A3 (R4–R6):** Duplicate events, restarts between association and attachment,
  concurrent observation, truncation/replacement, and manual closure preserve
  at-most-one display and do not backfill unrelated historical tasks.
- **A4 (R5–R7):** Standalone completion retains its pane; native subagent cleanup
  keeps its existing behavior. Verify unaffected interactive launch routing,
  title sanitation, display recursion suppression, outside-Herdr behavior, and
  profile/OpenCode isolation with checks proportionate to changed shared paths.
- **A5 (R1–R7):** In a separately authorized live qualification, create one
  harmless sufficiently long-running task through the actual app create_thread
  tool from a verified parent. Prove the parent-file binding and actual result
  envelope, automatic unfocused same-tab attachment of the exact existing task,
  no added prompt/turn, duplicate suppression, and pane retention. A manual
  attachment alone does not satisfy this automatic-capture criterion. Planning
  performs no task creation, hook installation, or pane mutation.
- **A6 (R7):** Update README, Codex installation, contracts, isolation,
  troubleshooting, and validation documentation as applicable. Explain the
  version-qualified local-record dependency, separate-task retention, exclusions,
  failure diagnostics, and distinction between static and live evidence.

Meaningful deterministic checks and existing quality checks are required during
implementation; they do not prove native capture or attachment. Unavailable
required qualification remains a disclosed DRAFT delivery gap, unless explicitly
excluded by the user. No runtime compatibility is claimed by this proposal.

## Evidence limitations

The observed rollout is an internal client artifact, not a promised stable public
API. Its precise hook transcript_path relationship and format must be qualified;
failure to establish the bound file or parse the observed records stops automatic
attachment. The creation correlation is serialized tool output, not cryptographic
ancestry proof. Parent/file binding and independent native backend checks remain
mandatory; no guarantee against an actor able to forge owner-controlled native
state is claimed. Native PostToolUse delivery for this app tool remains untested
and is not represented as an implemented solution.

## Approval

Approved on 2026-11-19 by the user's explicit response "approve" to the complete
HHH-003 specification approval question. Reviewed Proposed file SHA-256:
`60f322015c7d24fe99586b5297b4a517d40a62f63fef0954c75f5dc828d3a6a0`.
SPEC approval permits separate PLAN authoring only. No source implementation is
authorized in this human-invoked spec-plan session.
