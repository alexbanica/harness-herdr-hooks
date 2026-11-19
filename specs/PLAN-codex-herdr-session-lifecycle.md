# PLAN: Codex sessions and subagent pane lifecycle in Herdr

Status: Approved

- ID: HHH-002-PLAN
- Date: 2026-11-19
- Approved SPEC: [HHH-002](SPEC-codex-herdr-session-lifecycle.md), approved by
  the user's explicit "approve" on 2026-11-19.
- Approved SPEC SHA-256:
  `6c4934c18c6b9578972ec27b2308bff9ce738fc7607b575ca66c428aeb23a08c`.
- PLAN approval: Approved on 2026-11-19 by the user's explicit response
  "approve" to the complete HHH-002 implementation PLAN approval question.
- Reviewed Proposed PLAN SHA-256:
  `8313e0bcc61187d41037d673d7bb5bf15433f63525179713c8dd2e7d0707cd1c`.
- Planning origin: `/home/alexbanica/workspace/harness-herdr-hooks` on `main`.
- Observed research base: `e4ee497cb1c8d2273d2487c4e932b27ea398a580`.

## Outcome, authority, and preserved artifacts

Deliver HHH-002's normal-daemon Codex child display, verified completion cleanup,
and transparent routing of ordinary interactive agent-shell `codex` launches.
The SPEC defines behavior and exclusions. Preserve HHH-001 SPEC/PLAN bytes and
approval records. Their explicit-remote implementation boundary and retained
subagent panes change only as described by HHH-002; OpenCode semantics remain
unchanged. This PLAN does not approve itself or authorize implementation here.

Human-invoked planning stays planning-only. After both approvals, the human must
invoke `implement` in a fresh assistant conversation with both exact artifact
paths. That invocation owns implementation through assurance and authorized
commit/push without routine stage confirmations. It does not authorize main
merge, release, daemon restart, tool installation, or unrelated repair.

## Evidence and bounded source patterns

Implementation may inspect the approved artifacts, the files owned below and
their direct imports, existing public commands, and the version-matched source
patterns linked in HHH-002. Do not reopen product research or redesign behavior.
Regenerate installed Codex/Herdr schemas and use CLI help to verify exact
contracts; unsupported shapes trigger the implement amendment/blocker path.

Planning evidence distinguishes facts from unperformed checks:

- Codex CLI 0.170.0 help and tagged source establish shared default daemon
  selection, protected rendezvous socket aliases, child hook IDs, and literal
  shell environment overrides with per-command CODEX_THREAD_ID. A read-only
  live probe verified the selected profile's existing backend and loaded parent.
- Herdr protocol 22 permits omitted foreground argv. Current Herdr returns the
  foreground Codex PID/name/cwd without argv, so every ownership path must work
  without that field, not just bootstrap.
- `codex app-server generate-json-schema --experimental --out DIR` was run
  against 0.170.0 in planning. `v2/ThreadTurnsListParams.json` permits
  `itemsView: notLoaded`. Its response's TurnStatus enum is completed,
  interrupted, failed, inProgress; turn IDs and metadata are available without
  loading items. Use `thread/turns/list`, descending with bounded pagination,
  together with thread/read(includeTurns=false), stop-event correlation, and
  persisted turn generation to distinguish completion from temporary idle.
- No native pane attachment, automatic launcher, or completion cleanup has yet
  passed. CLI version is not evidence of running backend version or API support.

## Deterministic design and defaults

Use Python 3.11+ standard library, the existing POSIX entrypoint, and existing
native Codex/Herdr transports. No new executable dependency, daemon, service,
global shell alias, prompt instruction, or package registry installation.

### Backend and pane verification

Resolve an explicit native Unix endpoint when supplied. For normal shared-daemon
launches, select only the effective CODEX_HOME's documented alias. Validate the
alias and protected target using the native tagged socket rules, owner/mode,
private parent directory, and endpoint incarnation. Pin both advertised alias
resolution and physical socket identity; detect replacement on revalidation.
Verify the server's selected home, loaded parent thread, exact Herdr session
reference and same server/pane/tab before any presentation mutation.

Capture process evidence from Herdr PID/name/session binding and bounded native
OS inspection when needed; optional argv is additional evidence, never mandatory.
Pin process start identity to avoid PID reuse. Existing explicit endpoint
selection or `--no-daemon` must not be mistaken for default-daemon selection.
Do not scan other profiles or fallback to a server that merely has a similar ID.
If the process launch mode cannot be established safely, fail with a diagnostic.
Keep the OpenCode verifier's semantics unchanged.

New helper module `codex_backend.py` owns reusable endpoint/process proofs.
`herdr.py`, `attach.py`, and `coordinator.py` consume those proofs consistently
for bootstrap, display acknowledgement, reuse, title updates, and close checks.
A verified existing pane may be reused for display but is never close-owned.

### Hook and completion lifecycle

Handle SessionStart, SubagentStart, and SubagentStop independently. Validate
required fields/types without exact-object-key equality; discard nonmetadata
payload fields. Parse child IDs correctly and query native ancestor/source
metadata to find the exact eligible root binding. Validate ancestor chains and
Herdr context, rather than requiring a child ID to equal its parent's pane ID.

Persist child kind, root/parent, ownership provenance, current turn ID/generation,
accepted stop hints, attachment outcome, and manual-close suppression. Existing
records without positive creation ownership are never automatically close-owned.
Preserve baseline behavior: a verified newly created running child remains
eligible across delayed visibility/restart, while old unrelated children are not
backfilled. Bound pagination, payload sizes, retries and helper lifetime.

A stop event is a hint, not permission to close. Query metadata-only current/latest
turns and thread state after native hook handling. Close only after the matching
observed task turn is terminal, no newer/inProgress turn or continuation exists,
and the pane is still positively integration-owned and displays that child.
Recheck immediately before close. Errors, unknown ownership, transport loss or
unrelated foreground activity retain the pane. Persist pending cleanup so a
helper restart can reconcile an established terminal turn without replaying a
launch. A subsequent explicit subagent work generation is eligible again;
old stop/start deliveries cannot reopen its completed generation. Never send a
close-agent, interrupt-turn, or terminate-backend operation as pane cleanup.

### Ordinary interactive launch adapter

Install a profile-owned executable shim named `codex` in a dedicated private
adapter directory. Prepend only that directory to the selected Codex profile's
`shell_environment_policy.set.PATH`. Record the exact original field (including
absence), effective native executable, original PATH tail, and installed value
in ownership metadata. Values are concrete strings, never literal `$PATH`.
Reject ambiguous TOML/duplicate key layouts, symlinked or foreign-owned config,
changed ownership, and unresolvable native executables without overwriting them.

Use stdlib tomllib for parsing and a targeted byte-preserving TOML edit for this
one key. Preserve comments, formatting outside the owned edit, unrelated keys,
mode and owner. Atomic installation stages all files and validates native TOML
before publication; journal preimages privately and reconcile interrupted owned
transactions without clobbering concurrent edits. On reinstall, merge/preserve
the original PATH tail rather than repeatedly prefixing it. On uninstall remove
only unchanged owned values; restore an original field only when the current
field still matches the installation. Other changed fields remain untouched.

For an intercepted new interactive command, capture CODEX_THREAD_ID from that
native shell invocation, verify its parent backend and Herdr pane, then create
an idempotent private launch record with an opaque request ID. The destination
pane runs the originally resolved native CLI directly, once, under its own
terminal, profile and cwd. Preserve the intended argv/initial prompt once in
an owner-only short-lived launch payload; never place it in logs, Herdr titles,
source, or public evidence. Delete that argv payload after acknowledged launch;
retain only identity/outcome metadata. No shell evaluation of argv values.

Distinguish an integration display client from a newly launched independent
interactive session: displays bypass recursive automation, while independent
sessions may themselves spawn eligible descendants. Keep the new pane's own
Herdr markers, remove stale parent identity, and use the recorded native binary
to avoid recursive PATH interception. On client exit leave a usable shell.
Bound acknowledgement; after an uncertain launch outcome never retry the CLI.

Classify native CLI arguments before routing. `--help`/`--version`, tooling
subcommands, exec, existing-session resume, absolute-path/bypass cases, and
outside-Herdr invocations retain the SPEC's native/no-automation semantics.
Do not inspect or rewrite a user's prompt as a command or routing instruction.

### Diagnostics and installation lifecycle

Keep public install/status/uninstall entrypoints; add structured status facts
for registration, owned PATH adapter, observed native trust/load event, backend
binding, observer and attach/cleanup outcomes. Unknown/not-observed must remain
distinct from verified failure or success. Installation cannot prove hook trust.
Private records contain bounded metadata with appropriate expiry, not messages.
Expose one useful first-failure reason with a stable diagnostic category.

Upgrade isolated profiles first. Active Codex profile installation is authorized
by the existing local-install request and HHH-002 approval after valid implement
entry, but only after integrated source checks and isolated installer validation.
Announce exact hooks/config/PATH effects before applying. Never auto-trust changed
handlers or restart an active Codex/Herdr/backend. If the user must trust/reload,
record that native validation dependency and complete all independent work and
authorized DRAFT delivery; it is not a routine continuation gate.

## Workspace, delivery branch, and artifact transfer

- Source/destination repository: `alexbanica/harness-herdr-hooks`, remote origin.
- Delivery branch: `feat/codex-herdr-session-lifecycle`.
- Temporary retained checkout:
  `/tmp/agent-worktrees/harness-herdr-hooks/codex-session-lifecycle`.
- At implement entry, verify instructions, common Git directory, origin URL,
  dirty state, branch attachments and exact artifact bytes. Fetch the delivery
  branch if it exists; otherwise fetch/use origin/main, falling back to
  origin/master only if main is unavailable. Record resolved ref/SHA. The
  observed research SHA is not an instruction to reset a newer upstream.
- Existing delivery-branch continuation requires verified checkpoint ancestry;
  divergence, conflicting attachment or unrelated dirty paths stop as DRAFT.
  Use implement's guarded ordinary worktree lifecycle. Prepare the worktree
  detached; for a new branch, verify absence and create the exact named branch
  from accepted detached HEAD immediately before its first authorized commit.
- Transfer the approved SPEC/PLAN byte-for-byte, retaining invoking content,
  index and HEAD recovery states. Do not change invoking main's history or lose
  the approved artifacts. Restore transferred origin content only when it still
  matches its recorded preimage under the implement transfer rules.
- If this exact temporary path is registered but absent, deregister only that
  path with non-forced worktree remove and verify; never globally prune or
  remove a dirty/present unrelated worktree. Unsafe path state stops as DRAFT.
- Parent alone stages accepted paths, verifies diff/upstream and commits/pushes
  non-force to origin/feat/codex-herdr-session-lifecycle. Include both artifacts.
  Create one PR into main, DRAFT until all required acceptance evidence passes;
  verify head/base and published commit. No main merge or release is authorized.
- Preserve a clean retained checkout if an active installation links to it.
  Detach after verified push per implement lifecycle; do not remove its source
  or relink the user to an old main checkout. Report the active source location
  and later stable-source relink requirement. Never auto-pull into active work.

## Units, ownership, and sequencing

Parent retains requirements, integration, findings, Git, configuration mutation
authority and final acceptance. Every specialist assignment has exact file
ownership, effective artifact hashes, prerequisites, validation and a five-minute
interruption deadline; aim three minutes. No child creates a branch/worktree,
commits, pushes, deploys or edits active user configuration. Preserve others' work.
Each handoff is exactly one JSON object with stable unit_id, status and applicable
evidence. Before acceptance verify identity, artifact hashes and coverage.

Run units serially unless stated; shared schemas/files/native environments are
always serialized. Each developer unit includes meaningful tests with its
production changes; write regression tests first where practical. A unit that
cannot fit its bound returns verified partial progress and a disjoint remainder,
which parent resplits without overlapping an active assignment. Its handoff is
an intermediate checkpoint, never completion of the whole delivery.

| Unit | Role and exclusive paths | Prerequisites | Completion / validation |
| --- | --- | --- | --- |
| U00 | Parent: workspace, artifact transfer, version/schema snapshots; no source edits | Approved pair, fresh implement entry | Record upstream, working state, CLI/backend/Herdr versions and exact schemas; stop on unsupported required contract. |
| U10 | Developer: new `src/harness_herdr_hooks/codex_backend.py`, `tests/test_codex_backend.py` | U00 | Default/explicit endpoint, native alias/target validation and argv-optional process proof; foreign/stale/PID-reuse regression checks. |
| U20 | Developer: `adapters/codex.py`, `tests/test_codex_events.py` | U10 | Correct released hook IDs and metadata-only per-turn lifecycle APIs; continuation, extra fields, old/unknown shapes and ancestry tests. |
| U30 | Developer: `model.py`, `state.py`, `tests/test_lifecycle_state.py` | U20 | Versioned kind/ownership/turn/launch records and safe legacy adoption; idempotency, restart, baseline and changed-generation tests. |
| U40 | Developer: `herdr.py`, `attach.py`, `tests/test_pane_ownership.py` | U30 | Bootstrap/display/ownership verification without argv; created versus reused pane close rights, race and changed-foreground checks. |
| U50 | Developer: `coordinator.py`, `tests/test_subagent_completion.py` | U40 | One-pane attach and metadata-confirmed owned cleanup, continuation/idle/cancel/fail/restart/explicit-resume/manual-close cases. |
| U60 | Developer: new `launch.py`, `integrations/codex/codex`, `tests/test_interactive_launch.py` | U50 | Transparent bare-command classification, verified-parent direct-once launch, bounded acknowledgement, shell retention and recursion/isolation tests. |
| U70 | Developer: new `codex_config.py`, `tests/test_codex_config.py` | U60 | Byte-preserving owned PATH edit, TOML conflicts, static PATH construction, transactional recovery and restore semantics. |
| U80 | Developer: `install.py`, `integrations/codex/hooks.json`, `tests/test_codex_install.py` | U70 | Register three events and shim ownership; atomic upgrade/relink/uninstall, unrelated handler and second-profile preservation. |
| U90 | Developer: `cli.py`, `environment.py`, `tests/test_codex_integration.py` | U80 | Wire event/bootstrap/observer/launch/status paths; display versus independent recursion, bounded diagnostics and realistic combined fixtures. |
| U100 | Parent plus independent code-reviewer and contract-reviewer, read-only entire integrated change | U90 + development checks | Frozen complete diff, both artifacts, trace and evidence; all findings returned before one consolidated correction batch through bounded developers. |
| U110 | qa-agent: no source ownership, isolated and permitted live checks below | U100 corrections + affected checks | Independent final QA reports every acceptance group, effect and gap; classify any warranted correction cycle. |
| U120 | documentation-writer: README.md, docs/install-codex.md, docs/contracts.md, docs/isolation.md, docs/validation.md, docs/troubleshooting.md, docs/install-opencode.md only for obsolete clone instructions | Final QA and semantics stable | Synchronize approved behavior, install/trust/reload/limits, active source and actual evidence; no new behavior or approval claims. |
| U130 | Parent: accepted staging, commit, push, PR and terminal verification | All remaining lifecycle obligations reconciled | Verify source/artifacts/checks/config source and remote head; complete or evidenced blocked DRAFT with exact unmet criteria. |

Test ownership is exclusive per unit; initial reviewers/QA cover the full
integrated boundary, not only tests returned by individual developers. New test
modules use stdlib unittest and bounded fake transports/process metadata. Do not
add an unrelated repository-wide lint migration or hosted workflow in this change.

## Assurance profile and disposition

Full assurance: executable shell configuration, provenance, native hook event
contracts and cross-component pane lifecycle exclude routine assurance.

One independent integrated code-review wave is required. Contract review is
required for new SubagentStop consumption, corrected hook identity semantics,
private state/launch contracts and expanded status output. Security review is
not selected: no explicit security-review request was made; security concerns
remain part of development, code review and QA. Full independent final QA and
one documentation-writer synchronization are required.

Business domain assessment: one capability, presentation and lifecycle of
agent-created Codex sessions in Herdr. Native hooks, process/backend proofs,
configuration and Git delivery are technical components of that capability,
not interacting business domains. Additional architect PLAN assurance is not
triggered. Independent plan-readiness review remains mandatory.

Wait for the complete review wave. Main dispositions every supported finding;
apply one consolidated correction batch through bounded developer units and run
affected validation. Full QA follows. Repeat the cycle only for an evidenced
acceptance failure, regression, incompatible contract, high/critical security
defect, or blocked requested behavior with benefit exceeding impact. Record QA
concern evidence/benefit/impact/severity/recommendation and amendment class.
In-scope corrections and required implement amendments do not need routine
continue permission; missing external authority remains a genuine blocker.

## Validation and permitted effects

Run serially in the delivery checkout, retain exact inputs/results privately,
and never equate synthetic checks with native behavior:

1. `python3 -m unittest discover -s tests -v`; Python compilation with bytecode
   output redirected to a private temporary cache; `sh -n` for executable shell
   files; JSON parsing of hook/plugin metadata; Node syntax check of unchanged
   OpenCode plugin when Node is available. Parent performs git diff --check and
   inspects accepted staging. Do not install missing optional check tools.
2. Regenerate and validate the qualified Codex schemas and Herdr API schema.
   Query backend version read-only. Verify no unsupported schema is silently
   accepted and metadata requests use itemsView=notLoaded/includeTurns=false.
3. Isolated temporary profiles: native config/TOML validation without auth/model
   calls; unrelated hooks/config/comments/modes, managed/unmanaged conflicts,
   repeated install, interrupted transaction, moved source/relink, uninstall,
   no-PATH/existing-PATH values, quoting/metacharacters, native command bypass,
   snapshot restoration, second profile and OpenCode installation preservation.
4. Deterministic fake provider/Herdr/OS boundary checks for all named races and
   ownership failures. Include original explicit Unix endpoint and common
   OpenCode paths, no argv at every stage, stale marker/profile mismatch,
   backend/socket/PID replacement, old records, reuse/manual closure, unrelated
   foreground activity, duplicate launch and missing acknowledgement. These
   tests must assert observable behavior and prohibited effects, not mirror code.
5. After isolated checks and announced exact configuration effects, upgrade the
   selected active Codex integration using its owned installer. No native trust
   bypass, chmod of daemon sockets, active-session restart or backend start.
   If trust/reload is required, report precisely which native action is missing.
6. Authorized live Linux/WSL smoke work is narrowly scoped to this request:
   create a harmless read-only subagent long enough to observe, verify same
   thread/tab/unfocused pane and model-turn count, then completion cleanup.
   Exercise a controlled read-only interrupted/failed child and continuation
   where supported; do not interrupt existing user work. From a qualified parent
   run ordinary bare `codex` for a new independent interactive session in its
   pane, verify single launch, nested routing and pane retention after controlled
   client exit. No repository edits, credentials copying or trust bypass in the
   smoke sessions. Clean up only owned test helpers/panes; retained independent
   panes stay available as required. No native proof means a named DRAFT gap.

Live checks may require host-visible read-only queries and narrowly scoped owned
pane/config effects through the platform's permission mechanism. Permission
denial is not source-test failure. Complete safe independent work and DRAFT
delivery rather than bypass restrictions. This PLAN grants no external message,
deployment, credential change, or unrelated foreground-process termination.

## Requirement-to-delivery trace

R1–R11 refer to the SPEC's numbered Required behavior items. A1–A7 refer in
order to its seven Acceptance and validation bullets; other anchors are explicit.

| SPEC anchor | Units / paths | Required evidence |
| --- | --- | --- |
| Purpose; scope/current versions; R1, R2; A1, A5 | U00/U10/U40/U90; backend, Herdr, CLI | Default and explicit live backend identity; native alias and foreign/incarnation failures. |
| R3; A5 | U10/U40/U50/U90; backend/Herdr/attach/coordinator | Missing argv across bootstrap, attach, reuse, title, close; unrelated process retained. |
| R4; A1, A2, A3 | U20/U30/U80/U90; Codex adapter/state/hooks/install | Child hook source IDs, additional fields, exact native ancestry; trusted real events. |
| R5, R6; completion definition; A2, A3 | U20/U30/U40/U50/U110 | Existing-runtime no-added-turn attachment; terminal-generation close; idle/continuation/restart/failure/resume races. |
| R7, R8; separate-session definition; A4 | U60/U70/U80/U90/U110 | Bare-command PATH+snapshot routing, native argv exactly once, matching parent/tab/profile, retained shell. |
| R9; A2, A3, A4 | U30/U40/U50/U60/U90 | Duplicate/start-stop generation tests, manual-close suppression, display recursion and launch acknowledgement loss. |
| R10; preserved behavior/isolation; A5, A6 | U10/U30/U40/U60/U70/U80/U90 | No-op outside Herdr, one-way safe titles, existing/unowned pane preservation, explicit endpoints and OpenCode regression checks. |
| R11; installation effect; A1, A6, A7 | U70/U80/U90/U120 | Owned config transaction, restore/conflict checks, no false status/trust claims, user-owned reload evidence. |
| Scope exclusions; predecessor/platform boundaries; A4, A7 | U60/U90/U110/U120 | Bypass/native semantics, documented Linux qualification and predecessor gaps; no unauthorized daemon operations. |
| A7; evidence limits and DRAFT rule | U100/U110/U120/U130 | Complete reviews, actual static/native evidence, synchronized docs, verified published SHA or blocked DRAFT. |

## Definition of Done, checkpoints, and stop conditions

Complete means approved behavior implemented, all required tests/checks and
native acceptance obtained, required reviews/corrections/final QA/docs finished,
accepted artifacts/source committed and pushed to the verified branch, PR head
and base verified, and invoking/retained/active-source states reconciled. Assess
HHH-002 completion separately from historical macOS/OpenCode/native gaps; never
claim those predecessor criteria passed from this delivery.

At every reached checkpoint report `Checkpoint XX`, completed/remaining work,
and verified commit plus destination branch or explicit not committed/not pushed.
Unit handoffs, a checkpoint commit, and DRAFT push never finish the remaining
lifecycle or require a continue prompt. For incomplete safe checkpoint delivery,
label PR/report DRAFT and give exact missing native or assurance evidence.

Genuine stops: unverified approved artifacts, dirty/conflicting worktree or
upstream, unavailable supported attachment/API/launch provenance, missing native
trust/reload, denied necessary external effect, unsupported running backend,
unsafe config conflict, or unavailable required validation capability. First
finish unaffected work, preserve evidence and apply active implement amendments
where authorized. Temporary specialist capacity is scheduling state; queue/wait,
do not report it as a blocker. No fabricated acceptance or unrelated fallback.

## Planning assurance record

- Independent reviewer: native plan-readiness-reviewer,
  unit `HHH-002-readiness-01`, 2026-11-19; returned a valid complete JSON handoff.
- Reviewed approved SPEC SHA-256:
  `6c4934c18c6b9578972ec27b2308bff9ce738fc7607b575ca66c428aeb23a08c`.
- Reviewed PLAN body SHA-256 before this assurance-record-only update:
  `ef873d39d267b97c8b7306f106d53d74de47df6466e73aebc6080c4cade589ca`.
- Coverage: full supplied artifacts, requirement/acceptance trace, implementation
  handoff, units/ownership/dependencies, permitted effects, validation, assurance,
  delivery, stop conditions and predecessor/planning boundaries; bounded source
  inventory confirmed that the assigned test modules are new implementation work.
- Findings: none. No supported readiness finding remains unresolved. The parent
  verified matching artifact identities and complete assigned review coverage.
- Limitations: advisory artifact review, not runtime compatibility or native
  test evidence, approval, implementation authority or delivery acceptance.
- Architect trigger remains absent for the single-domain reason above. This
  record changes no reviewed behavior, sequencing, validation or delivery choice.
