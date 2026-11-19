# Integration contracts

This document describes the implemented local contracts and their current
qualification limits. The project is DRAFT / experimental; these interfaces do
not imply complete native support.

## Operator CLI

The public commands are:

```text
harness-herdr-hooks install {codex,opencode} [--config-dir PATH]
harness-herdr-hooks status {codex,opencode} [--config-dir PATH]
harness-herdr-hooks uninstall {codex,opencode} [--config-dir PATH]
```

Exactly one harness is selected. Install and uninstall serialize updates under
the selected config root, use a private ownership manifest, preserve unrelated
entries, and refuse conflicting or changed unmanaged destinations. Codex also
owns a profile-local PATH adapter/config edit. Status distinguishes registered
handlers and configured adapter from observed native load/trust, backend,
observer, and pane outcomes; unknown observations are not success.

## Native events and identity

Codex 0.170.0 hooks are registered for `SessionStart`, `SubagentStart`, and
`SubagentStop`; bounded JSON validates required fields while tolerating
additional fields, and discards transcript/message contents. Child hook
`session_id` and `agent_id` identify the child; ancestry is independently
verified against the exact parent. Hook identities are hints, not backend
proof. A verified normal selected-profile shared daemon and an explicit Unix
endpoint are supported; `--no-daemon` and unknown launch modes are refused.
The socket alias/target, owner, private containing directory, incarnation,
profile, and Herdr pane/session binding are verified. Optional Herdr argv is
not required; process metadata and OS inspection establish process identity.

The OpenCode 1.19.5 plugin forwards bounded, allowlisted metadata for
`session.created`, `session.updated`, `session.status`, and `session.idle` over a
short-lived helper. The version-1 envelope includes event kind, server URL/PID,
session ID/parent/title/directory/creation time, and config/data/state root
hints. The hints do not establish authority: the helper checks the foreground
server process, loopback API, Herdr pane, and native session ancestry. The
plugin's bounded queue and helper timeout prevent an event callback from
waiting indefinitely. Transcript contents, credentials, and arbitrary
environment maps are excluded.

## Observer and attach behavior

The observer uses a context-scoped startup baseline plus pending verified
creation exceptions and persisted owned records to distinguish newly observed
children from old sessions. It does not backfill old conversations. Only a
verified, still-running and attachable child in the verified parent ancestry
may be opened. It attaches to the existing backend/session without submitting a
prompt. Unknown status or incomplete backend identity is not treated as
eligible. Codex reference command form is `codex resume --remote
unix://PATH ID`; OpenCode reference form is `opencode attach URL --session ID
--mini`. These forms were source-qualified but not validated as live native
child attachment; they are not an acceptance claim.

Herdr pane placement uses the bound parent tab and no-focus split. Existing
verified panes are reused. Session titles map one way to pane labels after
control sanitization and length bounds; titles never establish identity.
Completed children and sessions outside Herdr are skipped. A proven empty pane
from a failed pre-exec attach can be closed; panes with an attached/started or
unknown/live TTY are retained conservatively for the existing OpenCode behavior.
For Codex, an integration-created subagent pane closes only after its matching
turn generation is confirmed terminal and the pane's owned process/session
binding is revalidated. Reused panes, panes with unknown ownership or process
identity, and independent interactive-session panes remain open. Revocation
stops only the integration's own helper and leaves panes/agents alone.

Terminal cleanup is reconciled against persisted positive ownership even when
ordinary child discovery no longer returns that child. A missing child, missing
helper, unloaded helper, or `itemsView: notLoaded` alone is not terminal
evidence. A successful native status read reporting `notLoaded` may participate
only alongside metadata confirming terminal state for the matching turn/task
generation and no newer running work; cleanup then revalidates the original owned
pane and process, including proof that the original PTY process exited before
closing an empty display. Cleanup snapshots state under lock, performs native
checks and close outside that lock, then persists only if the generation and
ownership still match. A concurrent final close is guarded, and a manually
closed child is suppressed from reopening. Unknown, unowned, or ambiguous panes
are retained. Initial attachment is skipped until a successful startup baseline
is persisted, so existing children are not mistaken for new ones. Owned helper
replacement is a bounded parent-owned operation: it checks helper revision and
path and retires only a proven integration-owned stale helper. Read-only status
does not retire or reconcile helpers; the operation does not force a daemon
restart.

## Qualification limits

The Codex adapter routes supported ordinary interactive `codex` shell commands
through the profile-owned PATH prefix. It classifies commands before routing,
starts a destination client once with a bounded private payload, and retains a
usable shell after client exit. Informational/tooling commands, `exec`, resume,
absolute paths, deliberate PATH bypasses, remote hosted backends, and
`--no-daemon` sessions are outside this routing qualification. Terminal child
cleanup correlates stop hints with turn ID/generation and metadata-only terminal
turn state; `stop_hook_active=true` denotes re-entry after an earlier
same-turn continuation and does not itself mean the current request is done.

Current source and controlled operator/API evidence are summarized in
[validation](validation.md). Parent observed Codex 0.170.0, Herdr 0.9.5p22,
and one bare launch acknowledgement placed in an unfocused pane in the selected
tab, with its launch payload removed. The launch pane remained at the native
confirmation UI. This does not establish same-thread/subagent attachment,
no-added-turn behavior, completion/cancellation, client exit, or current
revision runtime loading. Native trust/reload, terminal pane closure, and full
profile/backend/race coverage remain unverified; macOS runtime remains a
separate predecessor gap. Do not infer support for an unobserved native path
from these contracts.
