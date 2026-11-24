# PLAN — Bind Codex conversations to their Herdr client panes

Status: Approved

Approved by the user on 2026-11-24 with the response `approve`.
Reviewed proposed revision SHA-256 `87cd4ee164b1e0ebf1eeba463d244cd808f7a0021ab088b7b39973cb6a75754b`.

## Authority and delivery

Implement [the approved SPEC](SPEC-codex-client-pane-binding.md) at
SHA-256 `6dce64b3ca3a910340c00791cce2ef678b10118e6934fffe4a997259cd264a6c`.
The user approved including the pinned Codex TUI change. Preserve the earlier
[SPEC](SPEC-standalone-session-panes-only.md) and
[PLAN](PLAN-standalone-session-panes-only.md). This delivery adds client
evidence for the Herdr binding that those artifacts treated as an input.

Deliver to `alexbanica/harness-herdr-hooks` on a new
`feat/codex-client-pane-binding` branch, using a detached worktree at
`/tmp/agent-worktrees/harness-herdr-hooks/codex-client-pane-binding`.
Refresh origin and verify the branch is absent and
`origin/main` is `5b40ce8c0f1ed214e9faf78536ed4356457a5245`.
A changed branch or pinned base requires reconciliation before edits.
Transfer this SPEC and PLAN byte-for-byte. Leave invoking changes alone.
Commit reviewed files and artifacts, push without force, and open a PR to
`main`. Verify exact commit, upstream, PR head and base. Leave a DRAFT PR
with exact missing evidence if live qualification is blocked. No production
install, daemon restart, main merge, or upstream publication is authorized.

The installed standalone release includes two local corrections required for
a valid attachment test. Import only the three following tracked files from
the invoking checkout, verifying each digest and that their combined diff
against pinned main is exactly
`0cc532cd304a67185eec886d0b40a1539b765b2ad7683457c9e29474af22d59a`.
A missing or changed dependency blocks this delivery before source edits.

| Path | SHA-256 |
| --- | --- |
| `src/harness_herdr_hooks/attach.py` | `d65e784bafef01aa380989c50c9e5efcbb89ea9f0b1d65754d916b096a2fa40b` |
| `src/harness_herdr_hooks/herdr.py` | `c98ed27b5af4c6bf9adc429716186166386568f18cd290056ee3117e42681ac6` |
| `tests/test_tab_transport.py` | `1af73121d6c889d6ce1cdd0cf70340688bec842358225e201add42fcea435292` |

## Codex input and delivery boundary

Use OpenAI Codex tag `rust-v0.172.0` at
`3d86e43b075adeba2193ec5c22ac92f55afd82e6`.
Prepare a parent-owned scratch checkout under the isolated worktree's
temporary sibling directory. Verify both the tag commit and source tree.
Apply and build a distributable patch locally against that immutable input.
Deliver the patch and build instructions in this repository. Keep upstream
source, compiled binaries, build cache and live profiles out of the PR.
Use the upstream locked dependency graph and Rust toolchain `1.99.1`.
The invoking environment did not have Cargo on PATH or in the standard
local toolchain directories. Prepare the pinned toolchain in scratch
using the official Rust distribution if available. Failure to acquire it
is a build blocker. Do not change the system toolchain.

The producer belongs in the TUI, which controls view adoption in
`codex-rs/tui/src/app/session_lifecycle.rs` and the app lifecycle in
`codex-rs/tui/src/app.rs`. A server hook can see the thread ID and start
source but has no display identity. A request response can arrive before the
client adopts the view. Publishing from a successful client view transition
keeps the binding tied to the displayed session. The ordinary unconfigured
TUI must behave exactly as before.

## Execution units

| Unit | Owner | Boundaries and prerequisites |
| --- | --- | --- |
| U0 | Parent | Refresh and pin both sources, capture artifact and dependency bytes, and import the three verified attachment corrections. |
| U1 | Developer | Own the standalone Codex patch under `integrations/codex/client-pane-binding.patch`. Its upstream edit boundary is `codex-rs/tui/src/app.rs`, `codex-rs/tui/src/app/session_lifecycle.rs`, `codex-rs/tui/src/dynamic_tools_mcp.rs`, `codex-rs/tui/src/app/user_turn_submission.rs`, and a new `codex-rs/tui/src/app/herdr_display_binding.rs` with inline Rust tests. Implement the producer contract below and build/test the patched locked client. |
| U2 | Developer | Own `src/harness_herdr_hooks/{attach,client_binding,cli,coordinator,herdr,launch,install}.py` and `tests/test_{client_binding,interactive_launch,codex_install,standalone_task_discovery,tab_transport}.py`. Implement admission, leased client reports, observer authority, and qualification-mode setup below. U1 contract is fixed here. Integrate U0 without replacing its retry or transport safeguards. |
| U3 | Parent, code reviewer, contract reviewer, QA agent | Review complete integrated diff and producer/consumer contract, consolidate supported fixes, rerun affected checks, then run final fixtures and the authorized disposable live qualification. |
| U4 | Documentation writer | Own `README.md` and `docs/{contracts,install-codex,isolation,troubleshooting,validation}.md`. Record setup, patch provenance, migration boundaries, actual evidence, and the explicit-pane fresh-start operator procedure below. |
| U5 | Parent | Stage, reconcile, commit, push, verify PR, and perform guarded worktree cleanup per the implement skill. |

Serialize overlapping mutations and validation. Use the bundled specialist
assignment limits and structured handoffs. Full assurance applies because a
new executable opt-in changes a cross-component lifecycle contract,
session reporting, and the authority for pane effects. This is one business
domain, pane presentation. Contract review is required for the new event
contract. Security review was not requested. Independent PLAN readiness
review is required before approval.

## Client reporting and creation contract

The profile-owned adapter exposes an absolute reporting-helper command only
in the opt-in local interactive client launch. Use the
actual terminal descriptor already held by the TUI before redirecting helper
stdin. Duplicate that terminal as inherited descriptor 3 to
one helper. Its stdin and stdout are private pipes. Close other inherited
descriptors in the helper. Reject nonterminal or missing descriptors.
The helper obtains the terminal identity from descriptor 3 and compares
device and inode with the tty reported for the candidate pane. Accept only
a private authenticated Herdr socket, current protocol, exact workspace,
tab and pane, and a unique matching terminal. For admission only, examine
the tty and pane ID from protocol-22 pane process info in a bounded snapshot
of at most 128 panes. Missing or mismatched tty data fails closed. Do not
use a PID, foreground argv or process tree. Reads in the standalone effect
path use verified leases and Herdr snapshots, with no process query.

The helper inherits the managed launch's canonical selected profile and
the client-local Herdr address and coordinates. It validates those against
the active manifest, own terminal, and current server before publishing.
Use the existing endpoint pinning path to select the owned profile alias.
Qualify local shared connections on that endpoint. An explicit endpoint
qualifies only when it resolves to the same pinned selected-profile endpoint.
No server-inherited pane variables can supply the client coordinates.

Use newline-delimited JSON, bounded to 4096 bytes per line, over the
private pipes. A request contains version 1, a strictly increasing positive
sequence, event, and thread ID. `clear` has null thread ID, `active` has
the canonical displayed UUID and source `startup`, `resume`, or `fork`,
and `created` has the canonical parent UUID plus `child_id`, `turn_id`, and
`view_sequence`. Require the server-returned turn ID, with a byte length
cap of 128. Reject unknown fields, invalid sequences, reused view
generations, and malformed UUIDs. Replies contain only version 1, exact
request sequence, and status `ok` or `rejected`. Do not log authentication
data, client commands, transcripts or tool arguments.

Before leaving or replacing a view, the TUI sends `clear` and waits for
confirmed revocation before adopting the next view. Once it adopts a
supported primary view, send `active` and bind its acknowledged sequence
to that view. Cover initial startup, in-place resume, fresh replacement,
fork, switching away from supported views and detach. On normal close,
revoke before helper teardown. Use a six-second acknowledgement cap. If
revocation cannot be confirmed, close the channel and allow the transition
only after the old effect gate can be acquired, the live lease is absent,
and there is no unresolved split or start on the old view. Otherwise keep the current view available and report the failed handoff.
An unavailable helper on startup allows normal Codex operation with
reporting disabled and no managed placement authority.

The TUI records a turn as its own only when its foreground
`app/user_turn_submission.rs` submits a new user turn for its exact
acknowledged primary view and receives `UserMessageAdmission::StartResponse`
with the server's turn ID. Track it in memory for that acknowledged view
only. Do not infer ownership from a turn notification, shared turn state,
steering, queued submissions or inherited/restored turns.
`dynamic_tools_mcp.rs::call_tool` may issue a creation receipt only when the
request contains the native, unsynthesized thread and turn IDs and both
match that TUI's acknowledged view and own admitted user turn. Capture
that correlation before dispatch. On successful `create_thread`, take the
exact child UUID from the typed result of `dynamic_tools.rs::execute` and
emit `created` only if the captured view and turn still match. If a tool
arrives before the start response, metadata is absent, or another client
owns the turn, the tool may proceed but grants no placement authority.
Serialize client messages through a single writer and request sequence.

The helper records a bounded single-use receipt. Match it against the
existing verified rollout association for the exact parent, turn and
child before reserving a split. Match at most one current receipt and
consume it with the durable split intent, retaining the lease generation
and acknowledged view sequence on that claim for start and title effects.
Use existing rollout retention and cap receipts at 128 per client with
expiry at 60 seconds. A receipt from a prior client, stale endpoint
configuration, a native subagent, a failed result or a view switch during
the call never authorizes placement. Add same-thread registered and
unregistered caller controls with the same TUI MCP endpoint.

## Lease and effect ordering

Use private owner-only records under the existing state root in a
`client-bindings` namespace. Use a random per-helper UUID for generation,
one lifetime lock and one effect lock per generation. Reject symlinks,
foreign modes or owner, replaced lock inodes, and malformed records.
Publish lease bytes atomically with canonical profile and backend incarnation,
Herdr server identity, workspace/tab/pane/terminal identity, generation,
active UUID, last sequence, and bounded creation receipts. Permit one live
lease per server and terminal. Keep the lifetime lock held for the helper
connection. Verify it remains held and generation and inodes still match.
EOF, malformed input or non-monotonic sequence invalidates the lease.
Stale records cannot regain authority if a helper restarts.

Take the effect lock for publication, invalidation and effect admission.
Before sending a split or start RPC, check the live generation, current
view, backend, Herdr snapshot and exact destination under the lock. Hold
it until a validated terminal RPC reply or its existing request cap. A
timeout, lost reply or malformed acknowledgement leaves a durable unresolved
effect flag for that view before the lock is released. An outstanding flag
prevents acknowledging clear and adopting another managed view. Resolve
only through exact existing split/start reconciliation or a definitive
typed no-effect reply. Never infer absence from a snapshot, start again
after uncertainty, or close an unknown pane. Codex input in the current
view and client exit remain available. Disconnect invalidates the lease
regardless of effect resolution. A sent request may still finish, but
cannot authorize a subsequent effect. Test delayed server completion
after local timeout for both split and start. Before
each definitive busy retry obtain the same guard again. Use the existing
durable intent for uncertain external effects and reconcile by exact pane
and session only. An acknowledged clear must revoke the active generation
and all pending receipts under that lock, so no new effect from the old
view starts after the transition. Disconnect during an already issued
request leaves the existing durable intent and cannot authorize a later
request. Reuse the same guard before title effects. Add tests for switch
racing both split and start, EOF and lock replacement, failed acknowledgement,
duplicate terminal admission, and competing or unregistered callers.

## Hook migration and routing

Enable the managed client route per profile with
`install codex --client-binding-codex /absolute/path/to/codex`. Require the
pinned version and a capability marker in the patched client's version
output. Check regular executable ownership, canonical path and SHA-256,
record them in the existing installer manifest, and export the reporting
helper only when the managed adapter starts that executable in a verified
local interactive pane. Retain the native executable's direct launch for
excluded commands and the existing non-opt-in install semantics.
Use the existing selected-profile launcher and hook ownership transactions.

For claimed child displays, preserve the existing managed `agent.start`
request. Add the manifest-verified adapter directory as the first entry
in the split pane's PATH, followed by the profile's recorded native PATH.
Extend the split allowlist only for manager-constructed PATH. Herdr's
canonical `codex` command then reaches the selected profile shim, which
passes display resumes directly to the pinned executable with the exact
child claim and avoids recursive routing. Verify this real command path in
disposable QA, including a shell that changes PATH. In managed mode accept
an attached display only if the pinned client publishes the exact child
lease with the matching durable pane claim and Herdr reference. A client
that bypasses the patched shim cannot qualify.

For managed mode, require the legacy Herdr Codex session reporter to be
absent from that profile before enablement. Stop and report the conflict
if it remains. For disposable QA only, remove it via Herdr's
ownership-checked uninstall or start with a fresh profile that never
installed it. Preserve unrelated hooks. Publish Herdr's native session
reference from the verified client, using its transition source and current
Herdr sequence. The managed lease remains independent placement authority.
If a stale informational reference cannot be updated through approved
Herdr reporting, fail closed. Do not release or rewrite an unrelated
agent or pane. A daemon-reported reference cannot authorize a managed
split. Unconfigured profiles retain existing routing and installer behavior.

In managed mode start the existing discovery loop only from a verified
lease. Feed it the exact parent and current destination through the existing
association contract. Require an exact live creation receipt for the initiating client before any split. If competing receipts or a changed view leave the origin ambiguous, skip the split. Keep the one-shot split and start intent,
exact child session acknowledgement, bounded definitive shell-busy retry,
manual-close behavior, no prompt injection, and no automatic tab handling.

## Explicit-pane fresh launch evidence

A separate confirmed operator launch selected workspace `w2`
(RpiInfrastructure) from `herdr workspace list`, then selected its focused
working Codex pane `w2:pR` in `w2:t1` from `herdr pane list`. The caller
shell still inherited the unrelated `wE:p4` marker. The agent used the
explicit target, captured `w2:pZ` from the split acknowledgement, and
started a fresh Codex process in that pane:

```sh
herdr pane split --pane w2:pR --direction right --cwd /tmp/rpi-vpn-merge.aOklGJ --no-focus
herdr agent start swarm-vpn-implement --kind codex --pane w2:pZ --timeout 25000
```

The acknowledgements showed `w2:pZ` in `w2:t1` and an idle Codex client.
They did not contain an exact Codex session reference. Incorporate the
explicit inspected anchor, acknowledged new pane, and independent start
verification as the operator control in docs and live QA. In the automated
path source the anchor from the admitted client receipt, never from
global focus. Preserve the prior managed-start timeout and exact remote
resume arguments. A fresh launch with no arguments is a control and
cannot satisfy attachment to the already created child. No additional
automatic fallback or script entry point is part of this plan.

## Validation and Definition of Done

Run the Codex build and focused new Rust tests from the pinned upstream
`codex-rs` directory with `cargo build --locked -p codex-cli` and
`cargo test --locked -p codex-tui herdr_display_binding`. Check patch
application against a clean pinned tree. Run, in the delivery worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /usr/bin/python3 -m unittest -q test_client_binding test_interactive_launch test_codex_install test_standalone_task_discovery test_tab_transport
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -q
git diff --check
```

Live use is restricted to a disposable Herdr server and an authenticated
disposable Codex profile with two verified TUI clients in different spaces
sharing the same app-server. Use native hook trust if prompted. Capture
exact workspace, tab, pane and client IDs before each action. Trigger one
standalone creation from each client, then repeat after in-place resume in
one client. Confirm exactly one unfocused pane on the originating tab, the
exact child ID, original display retention, no additional turn, and a usable
shell after the attached client exits. Test one transition gap and one
ambiguous or stale binding with no pane effect. Clean up only owned test
resources. A missing credential, trust approval, compatible client build,
or usable create-thread tool is a recorded blocker. Synthetic cases cannot
substitute for live evidence.

Required terminal evidence is completed code and contract review, final QA,
docs, passing focused/full and Rust checks, live acceptance and verified
delivery. A blocked item stays DRAFT. The one-off manual binding confirmed
the target selection only. Its tool connection failure means it supplies
no live attachment acceptance.

## Requirement-to-delivery trace

| Approved SPEC anchor | Unit and evidence |
| --- | --- |
| Behavior 1 and acceptance 2 | U1/U2 view transition and lease tests. U3 in-place resume and transition-gap checks. |
| Behavior 2 and acceptance 3 | U2 stale, duplicate, moved, disconnected and malformed proof fixtures. U3 no-effect controls. |
| Behavior 3 and acceptance 3 | U1/U2 background and display-claim tests, legacy reporter conflict fixture. U3 verifies parent retention. |
| Behavior 4 and acceptance 1 | U0/U2 same-tab attachment and typed start regression. U3 live two-space exact child verification. |
| Prior scope, exclusions and acceptance 4 | U1/U2 compatibility and unchanged ordinary route. U3 full tests and contract review. U4 docs and live limitations. U5 exact artifacts and PR. |

## PLAN readiness evidence

The initial independent readiness pass reviewed draft SHA-256
`1a4a220f9481ac5974991ae628c15f6f589f2712c1188ce1dd1681db3dd9085f`.
It found missing effect ordering, exact creation attribution, terminal
descriptor delivery, patched child executable selection, and lease lifetime
semantics. The revision specifies acknowledged revocation with effect
locking, a client-owned successful-creation receipt, an inherited tty
descriptor, a verified profile shim path for display starts, and explicit
lease identity and invalidation rules. Upstream source inspection at the
pinned commit verified the relevant TUI MCP call and successful child
result plus both Cargo package names and the pinned Rust toolchain.

The second readiness pass reviewed draft SHA-256
`c4addf8ddda8559c40fe3698e151e94187529e78f845b34a603dc4bbd9e226eb`.
It identified delayed server execution after RPC timeout and a stale MCP
endpoint receiving another client's turn. The revision keeps uncertain
effects unresolved across view revocation, requires the exact TUI's own
user-turn start response, and adds an explicit-pane fresh-launch control.
Pinned `user_turn_submission.rs` was checked for the existing
`UserMessageAdmission::StartResponse` boundary.

The final independent recheck reviewed SHA-256
`649e07fac9e3d2c73f197aa48aa2d8a146fe01ee69f060ee1bd75505cb0b05a5`.
It found no remaining supported planning gap. It rechecked unresolved-effect
revocation, client-owned turn provenance, tty and patched executable
selection, and the explicit-pane fresh-start control. This is planning
assurance. Runtime and build qualification remain implementation work.

## Amendment A1 — 2026-11-24

Preceding effective PLAN SHA-256
`2cf89aac0b00acb973de6149651bf492c154dbddab6967f95cb3fd2cb740b536`.
The approved SPEC remains at the digest above.

- Add `codex-rs/tui/src/app/startup.rs` to U1. Before this amendment only
  `app.rs` and `app/session_lifecycle.rs` were available for view adoption.
  The pinned startup resume and fork path directly enqueues its first
  adopted session in `app/startup.rs`; use that site after successful
  adoption and retain the selection's exact transition source.
- Add `codex-rs/tui/src/dynamic_tools.rs` to U1. Existing `execute` erases the
  internal creation result into MCP text. Preserve the existing external
  response and existing callers, and expose a typed child ID to the TUI MCP
  call site before serialization. Capture the active view generation and
  acknowledged own turn before dispatch and verify them at completion.
- Add `src/harness_herdr_hooks/state.py` to U2. Its existing standalone
  effect schema rejects client generation fields. Extend the existing
  split/start intent to persist both the exact issuing generation and view
  sequence, accepting legacy intent records without those fields. Reuse
  exact child reconciliation and keep sent effects unresolved until proven.
- Protocol 22's snapshot has no global report sequence. Follow the installed
  native reporter's `time.time_ns()` sequence convention for Herdr session
  report requests and verify the resulting exact typed reference from a
  fresh snapshot.

The originating `$implement SPEC-codex-client-pane-binding.md` request
authorizes this implementation-required PLAN amendment automatically under
the implement skill after independent readiness assurance. Behavior, profile
and pane authority, pinned sources, delivery, validation and live acceptance
stay as approved.

Independent readiness review of amendment candidate
`222942262ddeb959497056884c2a090a0f0a87bca1aed6c6d8e019783f6b3067`
confirmed the pinned adoption and result sites, legacy intent compatibility and
SPEC consistency with no findings. The parent verified the native reporter
sequence and protocol-22 schema separately. A1 is automatically approved for
the complete effective PLAN under the originating implementation request.

## Amendment A2 — 2026-11-24

Preceding effective PLAN SHA-256
`8243a2231b7ad6daa8b843094e9dae65b396346c3ea26ef73280df191e4f7cdb`.
The approved SPEC remains at the digest above.

- Add `codex-rs/tui/src/app/event_dispatch.rs` and
  `codex-rs/tui/src/app/agents_overview.rs` to U1 for the explicit in-place fork
  adoption and the primary-view detach to overview. The first passes a fork
  transition to the existing replacement path. The second revokes before
  leaving the active display and keeps current input available on failure.
  These sites are outside the original ownership table but already required by
  its lifecycle behavior.
- Use a TUI-generated private connection nonce solely to correlate failed-clear
  recovery with the old helper's random lease generation. Leave the v1 report
  and reply fields unchanged. After the old channel closes, the client invokes
  the same absolute helper in a verification-only mode. It passes the private
  nonce to locate the exact previous record, verifies the same terminal and
  acquired old effect lock, and requires absence of a live lease and unresolved
  split or start. Success permits adoption without restoring managed authority
  from that record, and failure keeps the current display available.
- Continue safe source and regression work if the approved locked commands
  refuse the upstream lockfile or the local Herdr lacks required tty and shim
  behavior. Retain the locked commands and exact live acceptance as delivery
  gates. Do not regenerate the upstream dependency graph or substitute process
  inspection, a different production installation, or a live shortcut.

This refinement preserves behavior, authorized profiles and panes, pinned
sources, validation, and delivery. The originating implementation request
automatically authorizes this amendment after independent readiness review.

Independent readiness review of amendment candidate
`03903aace1b7fb40d76dd71bf802033da0618330924a5d269c75082a46719320` confirmed
the navigation sites and unchanged approval and validation boundaries. It
requested explicit failed-clear recovery coverage. Add focused cases for an
exact disconnected generation, incorrect or stale nonce, live old lease,
unavailable or replaced lock, and unresolved split and start. Verify refusal
retains the active view, and verified revocation cannot restore old placement
authority. A2 is automatically approved for the complete effective PLAN under
the originating implementation request.

## Amendment A3 — 2026-11-24

Preceding effective PLAN SHA-256
`ab0a7a1b8f3e9299d959bc06e1b26d64782176017345aa4fec17b51bb2677fa8`.
The approved SPEC remains at the digest above.

- Add `codex-rs/cli/src/main.rs` to U1. The root CLI version declaration
  controls the installer probe. Advertise the exact agreed
  `herdr-client-binding-v1` marker on the patched Unix CLI while preserving the
  pinned package version and ordinary CLI routing.
- Add `codex-rs/tui/src/chatwidget/input_submission.rs` to U1 to distinguish
  the exact pending direct composer submission from the queued path. The
  pinned local `turn/start` turns both server outcomes into the same
  `StartResponse`, even when another caller won the start race. In addition
  to the foreground direct submission and its own response ID, require the
  first typed user message on that exact turn to carry the local request's
  unique client message ID. Read this immutable ID from a bounded ascending
  `thread/items/list` request on the same captured backend. Do not read or
  log content. Absent or different origin proof suppresses the placement
  receipt while the native tool still works. This corroborates a locally
  captured response and does not derive ownership from shared active-turn
  state or notifications.
- Verify the actual selected Unix endpoint at launch and at TUI view binding.
  Only matching endpoint paths and incarnations can enable managed reporting.
  Keep excluded commands routed to the recorded original executable before
  verifying the patched binary.
- Add `src/harness_herdr_hooks/adapters/codex.py` to U2 only for a named
  discovery namespace input. A shared context-only cursor pins one destination
  and lets a non-origin observer advance it when two panes show the same
  thread. Give each exact display its own rollout cursor and pending
  associations while retaining a shared parent-context effect ledger and
  one-shot replay records. Require the original receipt and exact display
  before admission. Cover both observer arrival orders.
- Invalidate the helper connection immediately at EOF or protocol failure.
  Serialize generation replacement behind any old in-flight effect gate and
  refuse to overwrite an unresolved old effect. When a previous start
  timed out, revocation verification may reconcile its exact persisted
  start claim against the exact attach lease and Herdr pane reference
  under the old gate. An unresolved split with no exact acknowledgement
  remains unresolved.

Add focused tests for distinct endpoint and stale binary admission, direct
origin ID versus steering and queued submission, immediate EOF while an effect
is held, old generation replacement, and exact delayed-start reconciliation.
No upstream server or wire format change, expanded runtime authority, or
validation substitution is authorized. The originating implementation request
automatically authorizes this amendment after independent readiness review.

Independent readiness review of amendment candidate
`48d4930bda42692a081c70204fd35b5ed41ff01de3f3098d12ae66ad8cc72ac1` confirmed
the pinned typed provenance, discovery and effect boundaries, and unchanged
acceptance gates with no findings. A3 is automatically approved for the
complete effective PLAN under the originating implementation request.

## Amendment A4 — 2026-11-24

Preceding effective PLAN SHA-256
`b9b1ad00f2ff83a7c5d1745c4165821d8f3bab97fd309db911bab6bf5efdad48`.
The approved SPEC remains at the digest above.

Add `codex-rs/tui/src/app/backend_selection.rs` to U1 for one existing
cross-backend navigation boundary. The pinned caller changes the displayed
backend before it reaches the common view adoption path. Confirm the old
lease's revocation immediately before the handoff and before any displayed
backend/input mutation. Handle refused revocation by keeping the current main
view and returning the existing continue outcome with a bounded error. The
local resume caller applies the same pre-handoff check. Supported endpoint
admission and runtime authority, exact SPEC behavior, approval boundaries,
pinned inputs, validation and delivery stay as approved. The originating
implementation request automatically authorizes this implementation-required
amendment after independent readiness review.

Independent readiness review of amendment candidate
`031b4f59c3242c76267b49193ff7af0ce067bbe00d49343eb3b6fb8354d5f54e` confirmed
the pinned pre-handoff boundary. Address its coverage finding by checking
both local and cross-backend success and refusal before composer or
displayed-backend mutation, including the bounded error and existing continue
outcome. A4 is automatically approved for the complete effective PLAN under
the originating implementation request.
