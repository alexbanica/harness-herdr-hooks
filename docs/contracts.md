# Integration contracts

This describes the current standalone-session and fresh interactive Codex
flows. Native subagent handling, OpenCode event handling, and automated Herdr
tab lifecycle were removed. Earlier validation records for those behaviors are
historical; they do not describe the current contract.

## Operator commands and installation

```text
harness-herdr-hooks install codex [--config-dir PATH]
harness-herdr-hooks status codex [--config-dir PATH]
harness-herdr-hooks uninstall codex [--config-dir PATH]
```

New Codex installs register only the managed `SessionStart` hook used by the
retained flows. Upgrade removes unchanged managed legacy `SubagentStart` and
`SubagentStop` registrations. Changed or unmanaged entries are preserved.
OpenCode install is retired; status and uninstall retain ownership-checked
support for discovering and removing an older managed plugin link. See the
[Codex](install-codex.md) and [OpenCode migration](install-opencode.md)
instructions.

## Standalone Codex creation and placement

The event source is a newly appended typed local rollout record for a
successful `codex_tui.create_thread` completion. It must correlate the exact
bound parent, turn, item, and one returned child ID. The event nominates a
candidate; the exact child is independently re-read on the selected Codex
profile backend and must be identified and attachable. Existing bounded
discovery, duplicate suppression, and overflow recovery apply. No history
backfill, prompt persistence, `PostToolUse` dependency, `exec` text parsing,
title/cwd/time inference, or native subagent ancestry is used.

The parent session is resolved from current authenticated Herdr session
bindings. Matching panes are deduplicated by workspace and tab. A single
destination tab is required; multiple matching panes in that tab use the
lexically first pane ID as split anchor. Missing or cross-tab-ambiguous
bindings cause no pane effect. Standalone discovery, destination selection,
and attachment do not require a foreground PID, argv match, or process-tree
match. Herdr's optional pane/workspace/tab environment markers do not establish
the standalone destination.

An exact existing display may be reused only when its native session reference
matches the verified child. Otherwise, a durable split intent for the exact
creation association and destination is saved before calling Herdr. Only that
call's exact acknowledgement may claim the new pane; its ID, workspace, tab,
and unfocused state are checked and persisted before attach. An acknowledged
pane is started through Herdr's managed Codex route with the verified profile
and exact selected socket, resuming the child ID without sending a prompt.
An exact child-session reference on that pane is required for attachment
acknowledgement.

Split and managed-start calls are one-shot external effects. If a call times
out, its acknowledgement is lost, or a crash occurs before durable claim, the
intent remains unresolved. Replay does not create another pane, issue managed
start again, claim success, or close the pane. The bounded unknown outcome is
retained for recovery and the operator can inspect the existing pane/session.
Standalone panes remain through idle, completion, cancellation, and Codex
exit. On client exit the pane retains a usable shell. A new creation result
must not reopen a manually closed display.

## Fresh interactive Codex command route

The separate profile-owned shell adapter routes only supported fresh
interactive Codex commands from a verified Herdr parent. It preserves profile,
cwd, arguments, and requested prompt and places one launch in the caller's
existing tab. This route retains its existing process/backend and launch
verification; the standalone flow's no-PID rule does not change that gate.
Informational/tooling commands, `exec`, resume/fork and other excluded modes,
absolute paths, deliberate PATH bypasses, remote hosted backends, and
`--no-daemon` remain outside the routing qualification and retain native
behavior. Outside Herdr the integration performs no pane automation.

## State, identity, and titles

The selected Codex profile/backend and Herdr server/session bindings are
verified independently. Codex hook or rollout identifiers nominate records;
they do not prove identity. Codex profile and socket isolation, exact session
identity checks, bounded input parsing, and private integration state remain
in force. Persistent records contain only bounded identifiers, destination
and ownership metadata, cursors/hashes, and effect outcomes needed for
deduplication and recovery; they exclude prompts, raw tool results, transcript
text, and partial records.

Session titles may update the pane label after sanitization and length bounds.
Titles never establish identity. Existing panes and tabs are not moved,
renamed as tabs, or removed by this integration. The integration does not call
Herdr tab creation, tab rename, tab close, or pane close for retired
subagent/legacy records. Legacy callbacks are no-ops.

## Qualification limits

The bounded rollout envelope was previously observed with Codex CLI 0.170.0
and Herdr 0.9.5/protocol 22 on Linux/WSL. Native delivery of app-owned
`PostToolUse` events is not required or claimed. Current source and controlled
checks, plus the latest live attempt and its limits, are recorded in
[validation](validation.md). Historical subagent and tab results in that file
do not qualify the current standalone flow.
