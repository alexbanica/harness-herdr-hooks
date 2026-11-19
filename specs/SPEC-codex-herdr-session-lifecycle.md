# SPEC: Codex sessions and subagent pane lifecycle in Herdr

Status: Approved

- ID: HHH-002
- Date: 2026-11-19
- Approval: Approved on 2026-11-19 by the user's explicit response "approve"
  to the complete HHH-002 specification approval question.
- Reviewed Proposed file SHA-256:
  `738a4667ed3b57ad17d3493d38d960a8c8dd7009d8267c496c9590baa3597f03`.
- Research base: `main`, commit `e4ee497cb1c8d2273d2487c4e932b27ea398a580`.
- Predecessors: [HHH-001 SPEC](SPEC-harness-herdr-hooks.md), effective original
  plus A1 and A2, and [HHH-001 PLAN](PLAN-harness-herdr-hooks.md).
  These files remain unchanged, including their approval records.

## Purpose and requested outcome

Make the installed integration work when Codex is launched normally inside
Herdr, without requiring an explicit `--remote` argument. A newly started native
subagent appears in an unfocused pane in the parent's existing tab and its owned
pane closes automatically when that subagent task completes. An agent's ordinary
interactive `codex` launch opens a separate session in the same tab; that pane
remains available after the session becomes idle or exits.

Authority is the user's 2026-11-19 request to "make it work" and subsequent
answers: "Automatically close on completion", "Yes, keep that separate session's
pane open", and "Require automatic detection of ordinary Codex launches".
These requests define behavior, not artifact approval or evidence of success.

## Scope, definitions, and deliberate installation effect

The new qualification target is this user's Linux/WSL environment: Codex CLI
0.170.0 and Herdr 0.9.5/protocol 22. Qualify the actual running backend version as
well as the CLI; different versions are not presumed compatible. Preserve the
existing explicit-endpoint path and OpenCode behavior. This change neither
qualifies macOS nor removes the predecessor's outstanding platform evidence.

- Parent: the exact current Codex session bound to the originating Herdr pane.
- Subagent: a native thread-spawn child whose identity and ancestry are verified
  against the parent's existing Codex backend.
- Separate session: a new interactive Codex conversation initiated by an agent
  shell command using ordinary PATH lookup, such as `codex` or `codex <prompt>`.
- Completion: the native subagent task has finished, failed, or been cancelled;
  a stop hook which requests continuation, temporary idle status, missing
  metadata, or a transport failure is insufficient by itself.
- Owned pane: a pane created by this integration, with a current verified
  session/backend/server binding. Finding an existing matching pane does not
  grant permission to close it.

Automatic ordinary-launch routing uses a managed command adapter selected by
Codex's supported shell-tool environment configuration. The installer may add
an owned PATH prefix for that adapter to the selected Codex profile. The user
and agent continue to invoke `codex`; no special launcher command or manually
started watcher is required. The adapter starts the requested session directly
in its destination pane once, rather than launching it twice and moving work.

This affects future shell commands after Codex loads the selected configuration.
Document any required user-owned reload/restart; do not restart active work.
Preserve existing PATH settings and unrelated configuration. Do not shadow or
replace the native executable globally, modify shell startup files, change
daemon settings, or install anything for another profile implicitly.

Direct absolute executable paths, commands that deliberately override PATH,
noninteractive `codex exec`, arbitrary third-party API-created root sessions,
remote hosted backends, and `--no-daemon` embedded sessions are outside this new
automatic-launch qualification. Informational commands and existing-session
resume commands must retain native behavior without opening duplicate panes.
These boundaries must be visible in setup and troubleshooting documentation.

## Required behavior

1. Bootstrap automatically from trusted native hooks for an ordinary Codex
   parent inside Herdr. Discover its existing selected-profile shared daemon
   without demanding a `--remote` flag. Explicit endpoints remain authoritative
   when provided; never redirect an explicit selection to a different server.
2. Validate Codex's native advertised socket alias, protected physical socket,
   owning user, containing private directory, endpoint incarnation, and backend
   profile. Verify that the exact parent is loaded on that backend and matches
   the current Herdr pane/session/tab/server. A familiar path or inherited
   environment alone is not sufficient. Never change socket permissions.
3. Do not require optional Herdr process arguments at bootstrap, attachment,
   adoption, ownership checks, or cleanup. Use independently verified process,
   session, and backend evidence; if required evidence remains ambiguous, report
   a bounded diagnostic without guessing or mutating another pane.
4. Interpret released hook identities correctly. For the qualified native
   subagent hooks, session_id and agent_id identify the child; independently
   establish its parent/ancestor relationship. Register and handle native start
   and stop events without treating the child ID as the parent's ID. Validate
   required fields while tolerating harmless additional fields; ignore message
   and transcript contents not needed for identity or lifecycle.
5. Open one unfocused split in the exact parent's current tab for a new running,
   attachable subagent. Attach the existing child on its owning backend without
   a new prompt, inference turn, replacement runtime, or permission/model change.
   A child which finished before attachment opens no pane.
6. After confirmed subagent task completion, close only its integration-created
   pane after revalidating ownership and confirming that no subsequent child
   work or unrelated foreground activity has taken its place. Keep the parent
   pane and backend untouched. Unknown state leaves the pane intact with a
   diagnostic. An explicitly resumed subagent undertaking new work may open a
   new owned pane; duplicate events for completed work cannot reopen one.
7. For an ordinary interactive Codex launch through the managed adapter, use
   the launching command's native thread identity and verify it against the
   actual parent pane/backend before routing. Open the intended command once
   in an unfocused pane of that parent's tab, preserving its working directory,
   selected profile, arguments, and requested initial prompt. Do not add another
   prompt or turn. Fail before launching if routing cannot be verified; do not
   silently create the session in an unrelated location or retry its inference.
8. Retain the separate session's pane through idle, completion, and native client
   exit; leave a usable shell when the client exits. Do not classify it as a
   disposable subagent. Nested requests use the verified requesting session's
   current tab. Launch acknowledgement and failures are bounded and observable.
9. Suppress recursive adapter/hook activation for integration display clients.
   Repeated events, concurrent starts, delayed metadata, helper restarts, and
   terminal events must not duplicate a pane or repeat a session launch.
   Respect manual closure: do not reopen solely on a title/status update.
10. Preserve one-way title synchronization, private scoped state, profile and
    harness isolation, and owned-only uninstall. Outside Herdr, retain native
    command behavior and silently skip pane automation. Never backfill unrelated
    old sessions or adopt every session in a shared daemon.
11. Installation/status must distinguish registration, selected-profile adapter
    configuration, native trust/loading, backend qualification, observer health,
    and actual pane attachment evidence. Explain any renewed trust required by
    changed handlers. Provide useful bounded failure reasons without secrets,
    conversation text, or bulk environment/configuration dumps.

## Delta and preserved behavior

HHH-002 replaces HHH-001's Codex retention rule (requirements 9 and 14) only for
integration-created subagent panes after verified task completion. Separate
sessions and existing/unowned panes remain retained. It adds automatic ordinary
interactive launch routing and the managed selected-profile shell environment
adapter. It replaces the delivered explicit-remote-only bootstrap restriction
with verified default-daemon discovery for the qualified launch mode, and
corrects child hook identity handling and optional-argv assumptions.

Preserve existing public install/status/uninstall entrypoints, unrelated hooks,
OpenCode plugin/configuration, other profiles, current agent work, no-op behavior
outside Herdr, exact same-tab placement, unfocused splits, title sanitation,
duplicate prevention, and no repeated inference. Predecessor artifacts remain
immutable. No deployment, release, main merge, unrelated maintenance, or native
daemon restart is authorized by this specification.

## Acceptance and validation

Use meaningful deterministic checks for identity/lifecycle/configuration races,
then perform native Linux/WSL checks separately. Source inspection is not native
attachment evidence. The following are required for HHH-002 delivery:

- A trusted hook in normally launched Codex verifies the existing daemon and
  parent, automatically starts observation, and reports the correct binding.
- A real sufficiently long-running native subagent opens once in the correct
  unfocused same-tab pane, displays the same running thread without an added
  model turn, and closes that owned pane after confirmed completion.
- A stop/continuation cycle, temporary idle status, cancelled/failed task,
  restart, duplicate hook, delayed metadata, and completion/attachment race
  produce the declared results without closing unrelated work. Reused native
  threads and manual pane closure do not cause duplicate or stale cleanup.
- An agent's ordinary interactive `codex` command routes automatically without
  a special command, including the qualified shell-snapshot environment. The
  requested session starts once in the parent's tab and its pane remains usable
  after client exit. Informational/resume commands and outside-Herdr launches
  preserve their native semantics. Deliberate bypasses are documented accurately.
- Missing Herdr argv, default socket aliases, stale aliases, foreign ownership,
  changed backend incarnation, absent parent, and mismatched profiles fail
  safely. Do not lower physical socket protections or restart the daemon.
- Install/reinstall/status/uninstall preserve unrelated hooks and PATH/config
  entries, restore only still-owned modifications, refuse changed-entry
  conflicts, and do not touch another profile or OpenCode. Verify preserved
  explicit-endpoint behavior and affected common OpenCode paths.
- README and Codex installation, isolation, contract, validation, and
  troubleshooting documentation match the final behavior. Remove obsolete
  source-branch installation directions because the source is now on main.

An unavailable required native check remains an explicit DRAFT delivery gap;
approval does not manufacture that evidence or waive predecessor gaps.

## Evidence and limits

2026-11-19 read-only host-visible probes confirmed the existing parent has no
explicit remote argument, Herdr's Codex process metadata omits argv, and the
Herdr session ID matches this conversation. Following the selected-home native
socket alias found a user-owned 0600 socket in a 0700 directory. A read-only
initialize, loaded-thread query, and thread/read without turns verified the
selected Codex home and this active loaded parent. No prompt, model turn,
configuration change, or daemon start was used for those probes.

Version-matched primary source collected by an independent explorer:

- [Codex daemon selection](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/app-server-daemon/src/lib.rs),
  lines 2771–2778, and
  [transport socket paths](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/app-server-transport/src/transport/mod.rs),
  lines 52–67.
- [Unix socket alias and verification](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/app-server-transport/src/transport/unix_socket.rs),
  lines 30–31, 62–67, 92–134, 307–324, and 470–478.
- [Native child hook construction](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/core/src/hook_runtime.rs),
  lines 125–160, 355–430, and 1035–1053. This corrects earlier informal claims
  that the hook necessarily carries a parent session ID or lacks a child ID.
- [Shell environment policy](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/config/src/shell_environment_policy.rs),
  lines 10–22, and [per-command environment construction](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/protocol/src/shell_environment.rs),
  lines 59–75 and 102–153, establish literal PATH overrides and the invoking
  thread's CODEX_THREAD_ID. [Shell snapshot restoration](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/core/src/tools/runtimes/mod.rs),
  lines 2385–2402, 2498–2523, and 2754–2781, preserves explicit overrides.
  Installation must construct a concrete PATH value; a literal `$PATH` entry
  is not expanded by this configuration interface.

Native end-to-end attachment, completion cleanup, and automatic ordinary-launch
routing remain to be demonstrated; these are requirements, not current results.
