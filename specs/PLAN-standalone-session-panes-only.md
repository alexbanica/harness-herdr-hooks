# PLAN — Standalone session panes only

Status: Approved

Approved by the user’s explicit response `approve,` on 2026-11-22.
Reviewed proposed revision SHA-256
`5e04b9b463078858e73eb68d32af449c268cf0eb3d01b29731c1b182111bac2b`.

## Authority and delivery

Implement [the approved SPEC](SPEC-standalone-session-panes-only.md) at
SHA-256 `cd5f54056039a7736e5ececa290c8261f8b14cd80e37fedb45740ed0b75b4687`,
including approved Amendment 1.
Supersede native subagent and new-tab behavior in the earlier harness,
Codex lifecycle, and subagent-tabs SPECs and companion PLANs referenced by
the SPEC. Preserve their bytes and approval history. Preserve standalone
creation-event discovery, verified same-tab placement, and Codex interface
compatibility from their SPECs and companion PLANs. The untracked
`PLAN-codex-standalone-task-discovery.md` is outside edit ownership.

## Existing branch and worktree

Use the existing local `feat/codex-standalone-task-discovery` branch.
No replacement branch is created. Its verified local tip is
`45252db1f116d9e36e18cd25329faae80f6bf6b7`. The remote branch was absent
during planning. The retained tracking ref records
`2dc4df610b3db0a70c1fa9d7088cc2ee506263b0`, a direct descendant and
locally available follow-up for shell retention and overflow recovery.
Pin refreshed `origin/main` at
`00d4b79e3bb9b9cafa137860fcaf559d97f684ae`.

Before source edits, verify the three expected commits, exact local tip,
branch attachment state, origin branch absence, and exact refreshed main.
A changed ref or unavailable pinned commit requires reconciliation before
proceeding. Use a clean attached worktree at
`/tmp/agent-worktrees/harness-herdr-hooks/standalone-session-panes-only`.
The obsolete registered worktree at the different
`/tmp/agent-worktrees/harness-herdr-hooks/codex-standalone-task-discovery`
path is outside this operation. Capture invoking artifact bytes and index
state for later byte-verified transfer.

Fast-forward the feature branch to `2dc4df6` in the attached worktree.
The branch and main diverged after earlier squash merges. A merge-tree preview
found overlapping source, documentation and test conflicts. Use a
non-rewriting merge of pinned main into the feature branch with the exact
pinned main tree as the deliberate integration baseline. Before transfer or
edits, with the attached worktree clean, prepare the merge using
`git merge --no-commit --no-ff -s ours <pinned-main>`. Replace its staged and
working tree with the exact pinned main tree using
`git restore --source=<pinned-main> --staged --worktree -- .` from the
implementation worktree root. Require merge HEAD to equal pinned main,
`git write-tree` to equal the pinned main tree, and no unstaged or untracked
paths. Commit the verified integration with both parents and record its SHA.
U1 reapplies the relevant immutable standalone-only follow-up delta from
`45252db..2dc4df6` with regressions. This keeps both histories and verifies
the desired combined behavior without reviving superseded code from an
automatic conflict resolution. This integration commit is intermediate.

Parent stages accepted paths only, commits the reviewed implementation on
the attached feature branch, pushes that branch to `origin` without force,
and verifies the exact SHA, upstream and committed artifacts. Reuse an open
PR to `main` only if its exact branch and head match. Otherwise open and
verify a PR from the republished branch. Release the implementation
worktree's attachment after delivery. Leave invoking main, its files, and
unrelated work intact. No merge into main, production-profile install,
daemon restart, or changes to existing panes are authorized.

## Execution units

Execute units in order and serialize all mutation and validation. The parent
owns integration, corrections, delivery, and record verification. Use fresh
bounded native specialists with five-minute assignments.

| Unit | Owner and path boundary | Work and checks |
| --- | --- | --- |
| U1 | Developer owns `src/harness_herdr_hooks/{attach,cli,coordinator,herdr,model,state,tabs,launch}.py`, `src/harness_herdr_hooks/adapters/{codex,opencode}.py`, and the runtime tests named below | Add failing coverage first. Reapply the standalone-only pinned follow-up for exit-shell retention and overflow recovery, and preserve main’s profile checks. Replace standalone process checks with the session-to-tab and attachment rules below. Remove native child discovery, association, automation, stop processing and subagent-tab routing, including the dedicated tabs module. Keep standalone attach and duplicate suppression, title handling, shell preservation, overflow recovery and ordinary same-tab fresh launch. Reject legacy callbacks at runtime and prevent legacy records from driving effects. |
| U2 | Developer owns `src/harness_herdr_hooks/install.py`, `integrations/codex/hooks.json`, `integrations/opencode/{package.json,plugin.js}`, `tests/test_codex_install.py` and `tests/test_codex_config.py` | Register only the retained Codex start hook. Migrate owned legacy Codex handlers with the existing transaction and ownership rules. Retire OpenCode installation and event delivery while retaining ownership-checked removal of old links and status needed for migration. Exercise fresh install, reinstall, legacy, unmanaged, changed, and rollback cases in disposable profiles. |
| U3 | Parent, code reviewer, contract reviewer and QA agent. Source read-only for reviewers and QA | Run integrated checks, review the actual diff, apply one consolidated correction batch, run affected checks, then final QA and live qualification. |
| U4 | Documentation writer owns `README.md` and `docs/{contracts,install-codex,install-opencode,isolation,troubleshooting,validation}.md` | Update operator instructions, including migration for each old installer, supported triggers, qualification limits and observed validation evidence. Retain historical observed results as history. |
| U5 | Parent owns the approved SPEC/PLAN transfer, final reconciliation and Git | Verify complete scope and finish delivery. |

U1 runtime tests are `tests/test_{codex_backend,codex_events,codex_integration,interactive_launch,lifecycle_state,pane_ownership,runtime_status,standalone_shell,standalone_task_discovery,standalone_task_state,subagent_completion,subagent_tabs,tab_attachment,tab_coordination,tab_hooks,tab_roots,tab_routing,tab_state,tab_transport,workspace_anchor}.py`.
Remove cases specific to deleted subagent or tab behavior, keeping or moving
retained coverage to those files. Use the existing gateway patterns for effect
spies. Exercise no-effect legacy callbacks and attachment identifiers with real
legacy fixture records, rather than relying only on absent code. Ensure no
automation issues Herdr `tab.create` or pane closure from legacy subagent data.
Keep standalone task record parsing and Codex transport untouched except for
necessary direct consumer adjustments already named in the ownership boundary.

### Standalone placement and attachment

- Split the standalone authority path from the existing ordinary shell-launch
  path. Resolve the originating session by exact Codex ID or verified session
  path in the current snapshot of the authenticated Herdr server. Deduplicate
  matches by workspace and tab. If a single destination remains, choose the
  lexically first matching pane ID as the split anchor. Recheck the binding and
  destination immediately before splitting. Persist one durable split intent
  keyed by the creation association and exact destination before the external
  call. Associate a pane only from that call's exact acknowledgement. Verify
  its ID, workspace, tab and unfocused state and persist the claim before
  attachment. After a crash or lost split acknowledgement with no persisted
  pane claim, retain the intent and report bounded uncertainty. Neither infer
  ownership from an unrelated pane nor automatically split again or close
  anything. Test success followed by a lost reply, a crash before recording
  the claim, and replay in each case.
- Retain the selected profile's owned socket and incarnation, native parent
  and child metadata checks, bounded creation-record discovery, and exact
  association checks. Select the verified profile endpoint independently of
  Herdr foreground process information. Bootstrap from the hook-selected
  `CODEX_HOME` (or its existing default) and the owned selected-profile socket
  alias. An explicit socket may be reused only from a previously verified
  standalone association on that profile and must pass the same owned-socket,
  incarnation and thread checks. Do not guess from arbitrary sockets.
  `HERDR_SOCKET_PATH` supplies the Herdr server address hint only. Validate its
  ownership, peer and protocol with the current client before reading the
  exact parent binding. The pane, tab and workspace environment markers are
  ignored for standalone placement. If the socket address is absent or no
  unique binding verifies on that server, produce no pane effect. Bind
  observer work to the resolved session, and use the revalidated destination
  for every pane effect. Document the address prerequisite.
- For standalone work, do not call the integration's PID-based
  `verify_parent`, `process_info`, process-argv match or PTY cleanup paths.
  Reuse an existing display only when the native session ref independently
  matches the exact child on the verified server. For a newly created pane
  use Herdr's managed `agent.start` on that exact pane. Extend the standalone
  split environment allowlist to `CODEX_HOME` (verified canonical profile
  root), `HARNESS_HERDR_DISPLAY=1`, and the existing absolute
  `HARNESS_HERDR_STATE_ROOT` hint. Display clients must be excluded from
  standalone observer bootstrap by the durable display pane/session claim,
  even when a shared daemon's hook environment lacks the display marker.
  Send `kind=codex`, exact `pane_id`, a deterministic opaque name derived from the
  claimed pane and binding, `args=["resume", "--remote", "unix://<verified-socket>", "<child-id>"]`
  and `timeout_ms=4000`. Use Herdr's canonical Codex launch route with the
  pane's selected profile. Validate the typed reply and exact pane ID. The
  existing five-second request cap and a separate bounded exact-session
  acknowledgement apply. A name collision, unsupported route, malformed reply,
  timeout or exact-session mismatch is a bounded unresolved start outcome.
  Do not inject shell input, send a prompt, or fall back to PID logic.
- Atomically persist one start intent for the exact binding and claimed pane
  before the external call. After a crash or an uncertain response, reconcile
  against the exact child session reference on the same claimed pane and
  server. If the outcome is unresolved, retain the pane and intent. A replay
  must not split again, reissue managed start, report success or close the pane.
  Validate failures before and after claim persistence, during the call and
  after a lost acknowledgement. Verify that a launched native client exits
  to a usable shell in live QA.
- Programmatic Herdr client changes for managed start and session-only
  acknowledgement belong to U1 in `herdr.py`. Contract review covers that
  client contract as well as removed event handlers. Standalone effect tests
  must fail if any operation consults foreground process metadata. Exercise
  one match, several matching panes in a single tab, cross-tab ambiguity,
  no match, missing or stale inherited markers, unavailable and ambiguous backend evidence, non-default profile, display re-entry, changed destination before split, exact
  child acknowledgement and a repeated creation result after uncertain start.

During update, existing live panes and threads stay in place. Legacy binding
files remain readable where needed for safe rejection, and they are neither
deleted wholesale nor reinterpreted as standalone authority. Verify the
ownership manifest before retiring registrations and preserve independently
changed entries. Existing copies of old code in running processes are a
deployment concern, documented for operators. This work does not stop them.

## Assurance and validation

Full assurance applies because installed hook registration, external event
consumption, and persisted ownership used for pane effects change together.
This is one pane automation domain. Architect plan assurance is inapplicable.
Independent PLAN readiness review, integrated code review and contract
review, and final read-only QA are required. Contract review covers removal
of Codex subagent event consumption, the OpenCode event entry point and
standalone use of Herdr managed agent start,
including upgrade and stale caller behavior. Security review has no explicit
request. Consolidate supported findings and rerun affected checks before QA.

From the isolated checkout run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /usr/bin/python3 -m unittest -q test_codex_install test_standalone_task_discovery test_standalone_shell test_standalone_task_state test_interactive_launch test_runtime_status
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -q
git diff --check
```

Record direct fixture coverage for legacy no-effects, exact candidate binding,
duplicate/retry/overflow behavior, existing-display reuse, client exit and
migration with unrelated entries. Include a positive same-tab launch control.

For live qualification use a disposable Herdr parent and selected Codex profile
whose current Herdr session reference matches the parent on its owning daemon.
Do not require foreground PID or process-tree evidence for this live path.
Install only into that disposable profile, using the isolated checkout. Use the
native trust flow if required. Capture the exact parent tab and pane baseline,
trigger one native supported standalone creation, verify that one unfocused
pane in the same tab attaches to the returned thread, confirm pane retention
and shell usability after client exit, and record observable evidence that
attachment itself sent no new turn. A different session in that tab cannot
substitute for an exact match. Reclaim test-only resources when their ownership
is certain. Existing active user panes and the production profile are outside
this test. If a verified parent, usable client, or native trust is unavailable,
record the exact failed prerequisite. Do not substitute synthetic events for
live qualification.

## Requirement-to-delivery trace

| Approved SPEC anchor | Work and evidence |
| --- | --- |
| Required behavior 1 and acceptance 1 | U1 exact creation association, bounded observer, verified profile, backend and runnable identity. U3 replay, finished/foreign/mismatched cases and positive live qualification. |
| Required behavior 2 and acceptance 1, 3 | U1 standalone same-tab, no-turn attachment, title, deduplication, manual closure and shell retention. U3 controlled fixtures and live readout. |
| Required behavior 3 and acceptance 3 | U1 preserved launch classification and same-tab placement. U3 interactive and outside-Herdr coverage. |
| Required behavior 4–5 and acceptance 2, 4 | U1 no-effect retired event and binding paths. U2 owned installation retirement and old OpenCode uninstall. U3 code and contract review, negative effects, disposable upgrade tests. |
| Required behavior 6 and acceptance 5 | U1 preserves Codex compatibility, exact parent and socket, and effect ordering. U3 full suite, qualified live test or specific blocker. U4 operator guidance and actual qualification evidence. |
| Approved SPEC Amendment 1 | U1 session-only tab resolution, standalone managed resume and exact session acknowledgement. U3 zero process-query fixtures, ambiguous tab denials, no duplicate after uncertain start and live same-tab attachment. |
| Artifact and delivery integrity | U5 verified exact artifacts, base, commit, upstream, remote and PR. |

## Definition of Done

All retained behavior and requested removals are evidenced, review findings are
resolved, the focused and full suites and live qualification pass, operator
docs are synchronized, and commit, push and PR verification are complete.
Missing immutable input, a changed base, unsafe ownership or workspace, required
validation failure, missing live prerequisites, or rejected delivery are
specific blockers. Continue independent authorized work. If safe, deliver an
incomplete checkpoint on the approved branch and mark the PR DRAFT with exact
remaining criteria. A DRAFT push is intermediate recovery, not completion.

## PLAN assurance evidence

Initial independent readiness review P-READY1 checked the approved SPEC, pinned main,
immutable follow-up, complete draft SHA-256
`12927a4be9ecc1170bb52c8089249a1ece3db2289ca700d874b05983d813a900`,
and the direct installer, runtime and test boundaries. It identified that
`tests/test_subagent_tabs.py` directly imports the module U1 removes.
U1 now owns that test with the same removal and retained-coverage rules.
The reviewer found no other coverage, upgrade, assurance or delivery gaps.

Revised readiness review PLAN-READY2 checked the approved effective SPEC,
branch topology, same-tab selection, migration, and installed protocol-22
schemas against draft SHA-256
`0bf7cbcd07234a7b994478ea72274a4224d4b5dff192765cf66036c177be3b7c`.
The corrections specify profile propagation and display suppression,
Herdr and Codex endpoint discovery boundaries, a durable launch intent,
and the managed-start request and acknowledgement. A separate merge-tree
preview exposed overlapping conflicts. The plan now verifies a main-tree
integration baseline and reapplies the pinned standalone-only follow-up.

Final readiness review PLAN-READY3 rechecked the corrected draft
`18d23c9b793f5531c3918aa4bce6bb14dfd17b3e6556903f17311306a865942e`.
Its remaining finding was duplicate splitting after a lost response or crash.
The plan now requires durable intent before the split, exact acknowledgement
before claiming a pane, replay suppression while unresolved, and fixtures
for both failure sequences.
