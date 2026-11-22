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
usable shell after client exit. Standalone attachment invokes its helper without
a shell-level `exec`, so the original shell remains available; the helper still
replaces itself with the native client using `os.execvpe`. The subagent wrapper
behavior is unchanged. Informational/tooling commands, `exec`, resume,
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

## Codex standalone creation events

In addition to native subagent events, Codex observes only newly appended,
typed local rollout records for a successful `codex_tui.create_thread`
completion. The record must name the exact bound parent and include turn/item
identities and one unambiguous returned child ID. The event is a candidate
association, not ancestry proof: the exact task is re-read from the same
verified profile/backend and must be positively running/attachable. Native task
metadata supplies cwd for an ID-only result; an optional result cwd is retained
only as a normalized-path SHA-256 and must match native metadata. Missing cwd,
unknown status, or unavailable metadata defers or rejects attachment.

The rollout file must be the owner-controlled regular file bound to the
verified parent's native path under that profile's sessions directory. The
reader does not backfill its initial boundary, follows only appended records,
and correlates parent/turn/item IDs. It handles partial writes,
replacement/truncation, restart, duplicates and concurrent observers. A private
cursor and minimum ID-only associations/outcomes support recovery and
deduplication; prompts, raw results, conversation text and partial bytes are
not persisted. Limits are 1 MiB per read/record, 256 records per pass, JSON
depth 12, 128 pending associations and 512 characters per ID. If a pass would
exceed the pending limit, the cursor advances atomically with the bounded state:
up to 128 associations are retained, excess candidates are skipped, and one
ID-only aggregate rejected marker records the overflow for that read. Polling
continues, and status health reports the bounded `pending_limit` reason. Metadata
verification allows at most three attempts within a 30-second window; retry
time is monotonic within a process and persisted timestamps are bounded on
restart. Unsupported
envelopes fail closed with a bounded status reason.

This dependency is version-qualified to the observed Codex CLI 0.170.0 app/TUI
rollout envelope and Herdr 0.9.5/protocol 22 on Linux/WSL. It is not a stable
public Codex API guarantee. Native `PostToolUse` delivery for the app-owned tool
is unverified and not used. No `exec` JavaScript parsing, `codexDelegation`
inference, title/cwd/time parent inference, broad history scan, or arbitrary
root-task discovery is supported. Standalone tasks are separate sessions, not
native subagents; their panes remain after completion and client exit and are
not closed by subagent cleanup.

Status exposes recognition, verification, and attachment separately. Its
`current_health` reflects the latest observer pass, while stage outcomes retain
meaningful prior outcomes. Current health reports bounded reasons such as
parent-file binding failure, unsupported record, metadata unavailability,
invalid/mismatched cwd, expired candidate, or exhausted retry. Attachment stage
reports pending, attached, deferred, rejected, or unknown as applicable; it is
not a separate detailed failure-reason channel. Status does not expose prompt
or transcript content.

## HHH-005 subagent-tab contract

For a verified main-session root, the first newly eligible running, attachable
native subagent lazily creates one unfocused managed tab in that root's verified
Herdr server/workspace. Later siblings and verified nested subagents share it;
independent main sessions have separate associations. Each child attaches once
with its own native identity and cwd. Existing panes are not migrated, and
legacy same-tab bindings retain their prior lifecycle.

The tab label is `Subagents: <main title> [short main ID]`. Until a title is
available, the harness name is used. The displayed ID begins with eight
characters and expands as needed to distinguish managed labels. Control
characters are removed and the title portion is bounded; the full verified
identity, not the label, controls ownership. Main title changes rename only the
still-owned tab. Child title changes rename only that child's pane. These
operations preserve main placement and focus.

When a managed tab becomes verifiably empty, Herdr removes it automatically,
including after manual last-pane closure or failed first attachment. The
integration recognizes that removal as success; it does not issue `tab.close`. The integration does not empty occupied tabs: retained
OpenCode children and user-added shell panes prevent removal. Codex's existing
owned completion cleanup remains in force; OpenCode's prior post-attachment
pane retention remains in force. Manual removal suppresses duplicate events for
removed child displays; genuinely new eligible work can create a later tab.
Ambiguous ownership, ancestry, changed server incarnation, unsafe cleanup, or
unknown creation outcomes fail closed with a bounded diagnostic. An invalid
association never authorizes guessing a replacement tab.

### HHH-005 qualification

Deterministic source QA passed 271 tests on Python 3.12.3 and 3.11.14. Static
checks and isolated public install/status/uninstall checks passed; details and
limits are in [validation](validation.md). A transient first Python 3.12 run
observed 118 sessions where the test expected 128; the focused check and full
reruns passed, with no reproducible regression. The concern was low and timing-
sensitive; no repeat cycle reproduced it. Herdr 0.9.5 / protocol 22 targeted
`tab.create`, `pane.split`, `tab.rename`, and last-pane closure were observed on
Nov 19 without focus change. This did not qualify either harness's native
subagent attachment, nested grouping, or full lifecycle. Codex trust/reload is
pending the user, and OpenCode native qualification was unavailable. Overall
status remains DRAFT.
