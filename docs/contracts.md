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
entries, and refuse conflicting or changed unmanaged destinations. Status
reports registration/source consistency. It does not verify that a native
hook/plugin was loaded, trusted, or runtime-qualified.

## Native events and identity

Codex hooks are registered for `SessionStart` and `SubagentStart`; the bounded
JSON input is checked against the pinned Codex 0.169.0 fields. Hook fields are
identity hints, not backend proof. Codex requires a unique explicit Unix endpoint
among the verified foreground Codex processes, then verifies socket ownership,
permissions, and incarnation and checks the Herdr pane/session binding.
Implicit daemon or embedded fallback is refused.

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
unknown/live TTY are retained conservatively. Revocation stops only the
integration's own helper and leaves panes/agents alone.

## Qualification limits

Current source and controlled operator/API evidence are summarized in
[validation](validation.md). Native hook/plugin trust and reload, authorized
real native child attach with no added model turn, full profile/backend/race
coverage, and macOS runtime remain unverified. Do not infer support for an
unobserved native path from these contracts.
