# Harness Herdr Hooks

Harness Herdr Hooks displays newly created, independently verified standalone
Codex sessions in an unfocused pane in the verified parent session's existing
Herdr tab. It also retains a separate route for supported fresh interactive
Codex shell commands. The integration does not discover or attach native
subagents and does not create, name, or retire Herdr tabs. OpenCode integration
has been retired.

**Status: DRAFT / experimental.** Source checks and isolated migration/operator
checks passed, but live standalone capture and attachment were not demonstrated
in a correctly bound parent. See [validation](docs/validation.md) for current
evidence and remaining gaps.

## Quick start

```sh
git clone https://github.com/alexbanica/harness-herdr-hooks.git
cd harness-herdr-hooks
bin/harness-herdr-hooks install codex
bin/harness-herdr-hooks status codex
```

Install registers the managed Codex `SessionStart` hook and the profile-owned
command adapter. Reload the selected profile through Codex's normal controls
and follow any native trust prompt. Installation does not bypass trust or
restart a running client. OpenCode installation is retired; see
[OpenCode migration](docs/install-opencode.md).

## Standalone session panes

In a supported Codex app/TUI local rollout, a successful
`codex_tui.create_thread` result from a verified parent can identify a new
standalone session. The integration verifies that exact session on the
selected Codex backend and maps the originating parent session to one existing
Herdr tab. Standalone placement does not require a foreground PID or process
tree. If the parent has no unique verified tab, the event is skipped.

The exact session is displayed in one pane in that tab. A durable one-shot
intent precedes each non-idempotent pane effect. If an acknowledgement is lost
or the result cannot be proved, the integration retains the intent and reports
a bounded uncertain outcome; it does not blindly repeat the split or managed
start. Attachment adds no prompt or turn. The pane is retained through idle,
completion, cancellation, and client exit, leaving a usable shell.

## Fresh interactive Codex commands

The profile-owned adapter separately routes supported fresh interactive
`codex` shell commands from a verified Herdr parent. It preserves the selected
profile, working directory, arguments, and requested prompt, starts the command
once in a pane in the caller's existing tab, and leaves a usable shell after
client exit. This route keeps its existing process and launch verification;
the standalone session-only path does not depend on that PID gate. Unsupported
or uncertain launch modes retain native routing.

## State, migration, and qualification

The integration stores bounded identity and recovery records under the
selected private state root. Uninstall revokes its registrations but leaves
sessions, panes, tabs, and retained state alone. Reinstalling Codex removes
unchanged managed legacy subagent hooks. Run the OpenCode uninstall command
to remove its owned plugin link. Both operations preserve unmanaged and
independently changed entries. Existing processes may keep running the code
they already loaded. See
[Codex setup](docs/install-codex.md), [OpenCode migration](docs/install-opencode.md),
[contracts](docs/contracts.md), and [isolation](docs/isolation.md).

Native subagent/tab behavior described in older validation records is
historical and superseded. Current source assurance does not prove live
standalone capture, same-tab display, no-added-turn attachment, shell recovery,
or runtime loading of the current revision. The project remains DRAFT; see
[validation](docs/validation.md) and [troubleshooting](docs/troubleshooting.md).
