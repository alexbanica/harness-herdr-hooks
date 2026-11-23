# SPEC — Standalone session panes only

Status: Approved

Approved by the user's explicit response `approve` on 2026-11-22.
Reviewed proposed revision SHA-256
`e438caeb0b709347f1c0651744806fd3751402a6d1ee9a53cb8d2d4c8d9b6f25`.

## Purpose

Show newly created standalone Codex sessions in Herdr panes. Remove the
integration's handling of native subagents and its automated creation of
Herdr tabs.

The current main baseline is `00d4b79e3bb9b9cafa137860fcaf559d97f684ae`.
The standalone feature is already on main through `ab01373`. The local
`feat/codex-standalone-task-discovery` branch and retained remote-tracking
tip contain earlier and follow-up implementations. The follow-up
`2dc4df6` is locally available and records standalone shell retention
and discovery overflow recovery. The branch was absent on origin when
checked. Preserve the applicable standalone behavior when integrating
that follow-up with main.

## Required behavior

- Recognize a successful, newly observed standalone Codex
  `mcp__codex_tui__create_thread` call and result associated with an
  independently verified Herdr parent conversation. Verify the exact new
  thread, selected profile, backend identity and attachability before
  attaching. Retain bounded discovery and overflow recovery.
- Display the existing standalone session in one unfocused pane in the
  verified parent's current tab. Reuse an independently verified existing
  display when available and respect manual closure. The attachment must
  add no turn. Preserve title updates and retain the pane through idle,
  completion, cancellation and client exit, with a usable shell on exit.
- Keep existing ordinary interactive launch routing for supported fresh
  Codex sessions in a pane in the verified parent's current tab. Resume,
  fork, and other excluded commands keep their existing native routing.
  Outside Herdr the integration performs no pane automation.
- Remove native subagent discovery, event processing, pane attachment,
  completion cleanup, coordination state writes, and user-facing status
  for both Codex and OpenCode. Retire the OpenCode integration because its
  pane automation is for native child sessions. New installs register
  only the managed Codex hooks required by the retained flow.
- Remove the integration's automatic tab creation, naming, ownership
  and retirement. Legacy subagent hooks or bindings that reach the new
  runtime must produce no pane or tab effects. Preserve old panes, tabs,
  sessions and history through upgrade. Retain an ownership-checked path
  to remove obsolete managed registrations, including an old OpenCode
  link, and preserve unrelated or independently changed configuration.
- Preserve Codex interface-based compatibility, profile and socket
  isolation, verified parent binding and race checks. A missing or stale
  Herdr parent reference may still block standalone attachment. Changing
  how Codex and Herdr establish that reference is outside this change.

## Earlier approved behavior

This replaces the native subagent and tab behavior in
[SPEC-session-subagent-tabs.md](SPEC-session-subagent-tabs.md),
[SPEC-codex-herdr-session-lifecycle.md](SPEC-codex-herdr-session-lifecycle.md)
and [SPEC-harness-herdr-hooks.md](SPEC-harness-herdr-hooks.md), with their
respective approved plans retained as history. It preserves the standalone
behavior from [SPEC-codex-standalone-creation-events.md](SPEC-codex-standalone-creation-events.md)
and [SPEC-codex-standalone-task-discovery.md](SPEC-codex-standalone-task-discovery.md),
and the Codex interface policy from
[SPEC-codex-adapter-compatibility.md](SPEC-codex-adapter-compatibility.md).

## Acceptance

1. A verified new standalone session opens exactly one pane in the existing
   parent tab. Replayed events, finished candidates, invalid or foreign
   parent references, and repeated attachment attempts cause no duplicate
   panes or tabs.
2. Codex and OpenCode native subagent events, including completion and legacy
   callbacks, cause zero Herdr pane and tab effects. Existing panes and
   tabs survive the upgrade.
3. Standalone task overflow recovers within existing bounds, and clients
   that exit leave usable shells. Ordinary supported fresh-session launch
   continues to open a pane in the caller's existing tab.
4. Fresh install and upgrade fixtures verify that managed obsolete hook
   entries can be retired, unmanaged entries survive, and stale registered
   hooks cannot trigger any effects. Verify legacy OpenCode uninstall.
5. Run the relevant regressions and full suite. Verify the standalone
   creation path in a qualified Herdr parent and report live limitations
   separately. Update operator documentation for standalone behavior and
   migration from earlier installs.

## Amendment 1 — 2026-11-22 — Same-tab placement without PID checks

Amendment status: Approved

### Changes against the previous version

A new individual session qualifies for a pane when a supported Codex
creation result identifies a new standalone thread and the originating
conversation maps to one existing Herdr tab. Open one pane in that tab.
Neither the originating nor the new session needs a foreground PID or
process-tree match for discovery, placement, or attachment. Replace the
previous behavior's inherited process-pin requirement for this flow.

Use the creation result's originating conversation and Herdr's current
session bindings to find the tab. Multiple matching panes in the same
Herdr tab select that tab once. If a tab cannot be identified or the
matches span tabs, skip pane creation. An inherited daemon pane marker
alone cannot identify the tab. Confirm the returned new thread on the
selected Codex backend and keep duplicate prevention so the same creation
result opens only one display. Use Codex session identity for attachment
acknowledgement and replay handling.

### Preserved behavior and impact

The standalone flow can create only a pane in the existing tab.
Native subagent handling for Codex and OpenCode and automatic tab creation
are removed. Keep the previously approved standalone trigger, retention,
shell recovery, and installation migration. The independent ordinary
interactive command route retains its existing behavior.

Add acceptance coverage for a standalone session opening a pane with no
foreground PID or process metadata, a single destination shared by
multiple matching parent panes, and zero pane effects for missing or
conflicting tab mappings. Verify the exact child session rather than
inferring it from process information. This amendment does not add a
mechanism to repair stale Herdr session references.

### Approval record

Approved by the user’s explicit response `approve` on 2026-11-22.
Reviewed complete proposed revision SHA-256
`e56a94f95aabc18735b14190c55baacb4ed9e333406c0ad77255652b799be7a7`.
