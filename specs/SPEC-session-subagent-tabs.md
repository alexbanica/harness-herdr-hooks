# SPEC: One named subagent tab per main session

Status: Approved

- ID: HHH-005
- Date: 2026-11-19
- Authority: Human-invoked `spec-plan`; planning only. The user requested a new
  tab per main session, confirmed both Codex and OpenCode, accepted the name
  `Subagents: <session title> [short ID]`, requested closure when empty, and
  confirmed “one subagent tab per main session”.
- Research checkout: `main`, `dabbc6eb20fde4528238b490b9f424e929e0e477`.
- Approval: Approved on 2026-11-19 by the user's explicit response "approve"
  to the complete HHH-005 specification approval question.
- Reviewed Proposed file SHA-256:
  `0d2513fcd260264780046a3d8fbd7c59735dd433507a1d48561426534e01002b`.

## Purpose and scope

Keep a main conversation's delegated work together without crowding its original
tab. For both supported harnesses, newly attached subagents appear as panes in
one dedicated, named Herdr tab belonging to their verified main session. The
main session stays in its original pane. Nested subagents share that same
dedicated tab rather than creating tabs recursively.

This changes placement and adds tab naming, ownership, recovery, and empty-tab
cleanup. It does not introduce new session discovery mechanisms, change native
attachment semantics, broaden supported backend/platform combinations, or change
whether an individual child pane closes on task completion.

## Predecessors and exact delta

The following artifacts are read-only predecessors, including their amendments
and approval records:

- [HHH-001 SPEC](SPEC-harness-herdr-hooks.md) and
  [PLAN](PLAN-harness-herdr-hooks.md): replace requirement 5's same-tab placement
  and prohibition on creating tabs for subagents. Extend requirements 11–14's
  one-way naming behavior to the integration-owned dedicated tab. Preserve the
  original main tab/workspace names and existing pane-title synchronization.
- [HHH-002 SPEC](SPEC-codex-herdr-session-lifecycle.md) and
  [PLAN](PLAN-codex-herdr-session-lifecycle.md): replace requirement 5's Codex
  subagent placement only. Preserve native identity/backend verification,
  completion cleanup, ordinary interactive launch routing and retention.
- [HHH-003 SPEC](SPEC-codex-standalone-task-discovery.md) and
  [PLAN](PLAN-codex-standalone-task-discovery.md), and its replacement
  [HHH-004 SPEC](SPEC-codex-standalone-creation-events.md) and
  [PLAN](PLAN-codex-standalone-creation-events.md): preserve standalone-task
  discovery, classification, placement, and retention. They do not become
  disposable native subagents merely because an agent created them.

The untracked predecessor pairs are existing user work, not delivered source.
Their presence and approvals are not evidence that their implementation exists.
This specification does not authorize implementing them or changing their bytes.

## Definitions

- **Main session:** the verified originating conversation for a subagent tree,
  within one harness, profile, backend incarnation and Herdr server/workspace.
  A native subagent is never a new main session merely because it has an
  attached pane or launches nested delegation. A separately classified
  independent conversation is its own main session for its own subagents.
- **Subagent tab:** a tab created and durably associated by this integration
  with that exact main-session identity. Titles, cwd, inherited environment,
  and short IDs are display hints, never ownership or ancestry proof.
- **Empty:** no remaining panes or unrelated work in the dedicated tab. A
  retained child attachment or a user-created shell pane makes it nonempty.
  A creation-time bootstrap shell is removable only while independently
  verified to remain integration-owned and unused.

## Required behavior and invariants

1. Create the tab lazily for the first newly eligible, running, attachable
   subagent. Do not create empty tabs on main-session startup, installation,
   title updates, or discovery of already finished children. Use the verified
   main session's Herdr server and workspace; keep the main pane in place.
   Tab creation, attachment and title updates must not steal focus.
2. Attach each subagent once in that tab, retaining its own working directory,
   harness session identity and existing pane name synchronization. Reuse the
   first tab's initial pane for attachment where applicable; do not leave an
   extra unused shell pane. Further children use additional unfocused panes.
3. Siblings and all verified nested subagents share the main session's tab.
   Multiple observers and concurrent root/nested events must converge on at
   most one live managed tab and one attachment per child. Resolve ancestry
   and the root association before mutation; ambiguous ancestry fails closed
   with a bounded diagnostic rather than creating another tab or using an
   unrelated one.
4. Different main sessions receive distinct tab associations even when titles,
   directories, or short IDs match. Keep harnesses, profiles, backends and
   server incarnations isolated. No title-based adoption of pre-existing tabs.
5. Name the tab `Subagents: <main session title> [short main session ID]`.
   Until the title is available, use the harness name as the title component.
   Start with eight session-ID characters, extending the displayed ID if
   needed to distinguish managed labels within the workspace. Sanitize control
   characters and truncate the title component to fit supported display limits
   while preserving the prefix and distinguishing suffix. Identity always
   uses the full verified context, regardless of displayed text.
6. Synchronize subsequent main-session title changes one-way to the still-owned
   tab. Child-title changes update their pane names without renaming the tab.
   Never rename the original main tab/workspace or the native conversation.
   Missing title metadata preserves the last valid label; it cannot trigger a
   new tab or attachment. Manual labels do not establish ownership.
7. Close a dedicated tab when its last pane disappears, including after normal
   owned-pane cleanup, manual pane closure, or failed initial attachment. If
   Herdr removes an empty tab automatically, recognize that as successful
   removal. Never close an occupied tab, unrelated tab, retained child pane,
   or user shell to manufacture emptiness. Recheck identity and contents at
   cleanup, coordinate cleanup against concurrent attachment, and fail closed
   if ownership or safe emptiness cannot be established.
8. A later newly eligible subagent may create a new dedicated tab after empty
   cleanup or manual tab closure. Closure suppresses reopening the removed
   child attachments through duplicate events, polling, title updates or
   helper restart. Existing suppression rules remain effective.
9. Recovery must revalidate the server incarnation, main association, tab and
   child bindings before reusing, renaming, attaching, or cleaning up. Unknown
   creation outcomes must not cause blind repeated tab creation. Stale tab
   IDs and legacy same-tab bindings cannot grant ownership of another tab.
10. Do not migrate existing panes or backfill old sessions. Already attached
    legacy panes keep their established placement and safe lifecycle rules;
    newly eligible subagents use the new policy. Preserve existing unrelated
    or manually moved panes. An invalidated workspace/tab association is not
    permission to move work or guess a replacement destination.
11. Main-session exit does not authorize killing its children, closing occupied
    tabs, or stopping native backends. Empty owned-tab cleanup remains allowed
    when independently provable; missing authority leaves work intact with a
    bounded diagnostic. Outside Herdr, preserve silent no-op behavior.
12. Preserve existing pane-lifetime distinctions: verified Codex subagent
    completion follows HHH-002's owned-only cleanup; OpenCode retains its
    predecessor post-attachment lifetime. Closing an empty tab is not new
    automatic completion cleanup for OpenCode. Independent/standalone
    conversations retain their declared placement and lifetime and, if they
    themselves delegate, have their own dedicated subagent tab.
13. Preserve trust, permissions, profile environment, official Herdr integration,
    owned-only install/uninstall, and private state. No additional prompt,
    inference turn, replacement runtime, daemon restart, global configuration
    change, unrelated tab cleanup, release, deployment or main merge follows
    from this specification.

## Acceptance and validation requirements

Deterministic tests must cover both harnesses and the following boundaries:

- Two main sessions, identical titles, nested delegation and concurrent first
  children yield distinct per-main tabs with no duplicate tab or child pane.
- Main pane/tab and focus remain unchanged; first and subsequent children use
  their exact sessions and cwd, without an extra blank pane or inference turn.
- Missing/late title, explicit rename, hostile control characters, long titles,
  and abbreviated-ID collisions produce safe, distinguishable labels. A child
  rename affects only its pane.
- Last-pane removal, first-attachment failure, already auto-removed tabs, and a
  concurrent new child/cleanup race give the specified empty-tab behavior.
  Retained OpenCode panes, independent sessions and user-added work prevent
  empty-tab closure.
- Duplicate events, restart/unknown create outcomes, manual tab closure, reused
  IDs/server replacement, invalid ancestry and cross-profile/backend metadata
  never adopt, rename, close or attach to unrelated work.
- Existing same-tab bindings remain valid for their prior safe lifecycle; no
  migration, historical backfill, new inference or outside-Herdr mutation occurs.

Native Linux/WSL qualification must separately demonstrate both Codex and
OpenCode attachment to a real dedicated tab, nested grouping, unchanged main
focus, title synchronization and safe empty-tab removal. Preserve evidence of
the harness-specific retention rules. Controlled fixtures and CLI help are not
proof of live tab semantics or native attachment. Any unavailable required
native evidence remains a disclosed delivery gap, not an inferred pass.

## Documentation and evidence limits

Update README plus relevant integration contracts, lifecycle/isolation,
validation and troubleshooting documentation. Explain one tab per main session,
nesting, names/fallbacks, retained OpenCode panes, empty-tab removal, independent
session distinctions, manual closure, legacy panes and recovery diagnostics.
Distinguish installed configuration, loaded helpers and demonstrated behavior.

Read-only research verified parent-tab checks in `herdr.py` and
`coordinator.py`, full-context identities in `model.py`, ancestry handling in
both adapters, and the predecessor placement rules. Installed Herdr help
advertises named unfocused tab creation and tab renaming; no live tab operation
was performed for this planning work. Protocol details, atomic cleanup behavior
and actual native qualification must be established in implementation planning
and execution rather than assumed from command availability.
