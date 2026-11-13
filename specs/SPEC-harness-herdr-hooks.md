# SPEC: Harness Herdr Hooks

Status: Proposed

- ID: HHH-001
- Date: 2026-11-13
- Intended public repository: `alexbanica/harness-herdr-hooks`
- Approval: Pending explicit approval of this complete specification.

## Purpose and authority

Provide installable Codex hooks and an OpenCode plugin that automatically show
new agent-created sessions in Herdr and synchronize their pane names. Integration
code lives in its own public repository, separate from RpiInfrastructure. This
specification records requested behavior; it does not claim implementation,
runtime validation, publication, installation, or approval.

The user selected the repository name, Codex and OpenCode support, automatic
opening of agent-created sessions, and a different pane in the same tab as the
parent. The user explicitly instructed:

- Parent outside Herdr: "then don't do anything - skip".
- Already finished child: "skip - no need to open a pane with a finished session".

No existing approved artifact is revised. In particular, this independent
project does not restore RpiInfrastructure's retired session-manager skill,
change its native-agent workflow, or alter its installer.

## Scope and definitions

- A parent is a Codex or OpenCode session already running in a Herdr pane.
- A child is a new session created by that agent through a supported task,
  fork, or subagent mechanism with a verifiable parent relationship.
- A child pane displays that same running session through its existing runtime;
  it is not a copied prompt, a new inference run, or a transcript viewer.
- An eligible child is newly created after observation begins, still running,
  and attachable through the parent's existing runtime.
- An owned pane is one this integration created for a particular harness and
  session ID. A verified existing pane displaying that same session is reused.

Include native helper sessions as well as separately created agent tasks when
the harness exposes their identity, ancestry, and existing-session attachment.
Support Linux and macOS with prerequisites installed. The initial qualification
targets are Codex CLI 0.169.0 using its shared local daemon, Herdr 0.9.5, and
OpenCode's documented V2 server-plugin/session API. Legacy OpenCode V1 and
Windows are outside this delivery.

## Required behavior

### Hook-driven lifecycle and parent routing

1. Install through Codex's supported hook configuration and OpenCode's supported
   plugin mechanism. Any helper needed for discovery or name synchronization
   starts automatically from those integrations; no manually started watcher or
   separately administered service is required.
2. Establish the exact parent session, Herdr server, and parent pane before
   opening anything. Inherited environment variables alone are insufficient
   when a shared runtime could have inherited another terminal's context.
3. If the parent is outside Herdr, return silently without creating a pane,
   launching a helper, or writing integration state for that event. Do not use
   another workspace or tab as a fallback. Missing or ambiguous parent identity
   must never cause placement in an unrelated pane or tab.
4. Observe newly created children, including creation paths whose event is not
   delivered as a child-start hook. A hook-started metadata observer may fill
   that gap. Do not backfill old conversations on installation or restart.
5. Create one unfocused split pane in the parent's current Herdr tab, using the
   child's working directory. Nested delegation stays in the same tab through
   verified ancestry. Do not create tabs, workspaces, or Git worktrees.
6. Repeated events, parallel hooks, client resumes, and helper restarts must not
   create duplicate panes or observers. Reuse a verified existing session pane.
   If a user closes a child pane, do not reopen it merely because observation
   continues or a title changes.

### Attach without repeating work

7. Check that the child is still running and attachable immediately before
   opening its pane. Skip a child that has already finished. Do not open a
   history viewer or resume the parent to make an inactive child attachable.
8. Attach to the child's existing runtime and exact session ID, without sending
   a prompt, starting or steering a model turn, cloning the session, changing
   its model/permissions, or creating a replacement runtime. Preserve existing
   hook trust and sandbox settings.
9. If completion races with attachment, remove only a newly created pane that
   failed to attach; do not leave an empty/error pane for the finished child.
   Once attachment succeeds, later completion does not close the pane.
10. If the running child cannot be attached safely, fail closed for that child
    with a bounded diagnostic. Keep the parent's work unaffected. Lack of
    attachment capability is not permission to repeat inference or substitute
    a transcript pane.

### Name synchronization

11. Set the child's pane display name from its harness session title. Until a
    title is available, use the harness name and a shortened session ID.
12. Synchronize later generated titles and explicit session renames from
    Codex/OpenCode to the corresponding Herdr pane. This is one-way; do not
    rename harness sessions from Herdr, or rename the parent's tab/workspace.
13. Treat titles as data. Remove terminal controls and respect Herdr's display
    and alias limits without confusing two sessions with the same title.
    Identity and duplicate prevention use session IDs, not titles.
14. Synchronize only correctly identified session panes. Continue title updates
    for an already opened pane after its child finishes, while the parent
    context and pane remain available. Do not create a new pane for that update.

### Installation, state, and failure handling

15. Provide documented local install/link and uninstall commands for each
    harness. Preserve unrelated configuration and the official Herdr
    integrations. Remove only entries/files owned by this project.
16. Keep runtime associations and locks in user-local state outside the source
    checkout. Never publish credentials, local conversation contents, or runtime
    state. Read only the session metadata needed for identity, ancestry, title,
    running/attachable state, and working directory.
17. Use bounded, idempotent retries for startup/metadata races. Hook failures,
    Herdr unavailability, unsupported versions, and observer failure must not
    block, cancel, or repeatedly restart agent work. Do not auto-install tools,
    start Herdr, or change a harness's daemon settings to recover.
18. A helper is scoped to verified parent contexts and exits when none of its
    parent contexts remain. Never close existing session panes or terminate
    their agents as helper cleanup. Starting/resuming the integration's display
    client must not recursively open more panes.

## Evidence and compatibility boundaries

- Herdr's installed protocol 22 schema supports splitting a selected pane with
  focus disabled and renaming panes. No live pane was created during research.
- Exact Codex 0.169.0 source supports attaching to a running parent-owned native
  child through its owner, and rejects that route for inactive/unloaded native
  children. `thread/list` exposes parent/ancestor filters. The same-daemon CLI
  attachment path remains a runtime validation requirement, not proven evidence:
  https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/app-server/src/request_processors/thread_processor.rs
- Codex hook event coverage and parent correlation must be qualified against the
  actual supported version; source from `main` is not proof for a release.
- OpenCode documents plugin subscriptions, session creation/rename events,
  parent metadata, and existing-session CLI selection. OpenCode is not installed
  in the planning environment, so runtime acceptance is still required:
  https://opencode.ai/docs/build/plugins/server
  https://opencode.ai/docs/api
  https://opencode.ai/docs/cli/commands/

## Regression boundaries and exclusions

Do not change existing agent prompts, instructions, delegation, scheduling,
permissions, model choice, or conversation contents. Do not deploy a service,
publish a package registry release, modify RpiInfrastructure, or migrate its
retired runtime. GitHub repository publication is distinct from installing these
integrations into a user's active harness configuration.

## Acceptance and validation

Validate the following with appropriate syntax/structural checks and isolated
operator/runtime smoke checks. Do not claim runtime evidence from source review.

- For each harness, a new running agent-created child opens once in a separate,
  unfocused pane in the exact parent's tab; the displayed ID matches the child.
- Demonstrate native helper and separate-task creation paths where supported;
  document explicit capability limits. Verify nested ancestry, concurrent events,
  repeated hook delivery, and restart adoption without duplicate panes.
- Creation and subsequent title changes update the right pane, including two
  sessions with the same title and titles containing control characters.
- Outside-Herdr parents cause a silent no-op, even if another Herdr context is
  available. Stale/ambiguous parent state never opens a pane in the wrong tab.
- Already finished children open no panes. An attach/completion race leaves no
  failed new pane. A child finishing after successful attachment retains its pane.
- Attachment adds no prompt or model turn and creates no replacement session or
  runtime. Unsupported attachment fails without disturbing the parent.
- Closing a child pane suppresses reopening. Existing unrelated panes and all
  existing agent work remain untouched.
- Install/uninstall preserve unrelated hooks/plugins and leave credentials and
  runtime data out of the public source tree. Helpers stop when their verified
  parent contexts disappear, leaving existing panes intact.

Source/static validation and per-harness runtime results must be reported
separately. Missing runtime evidence or an unsupported required creation path
remains an explicit delivery gap; it must not be described as complete support.

## Documentation

Document Codex and OpenCode separately: prerequisites and qualified versions,
install/link/uninstall, any hook trust step, expected same-tab pane placement,
one-way naming, observer lifecycle, no-op/finished-session behavior, attachment
limits, and troubleshooting. Include a short example showing an agent spawning
a child and the resulting pane. Use public repository topics including `codex`,
`opencode`, `herdr`, `hooks`, and `ai-agents` for discoverability. Do not add a
manual watcher launch as the normal user flow.

## Amendment 1 — 2026-11-13 — Installation, documentation, and harness isolation

- Amendment ID: HHH-001-A1
- Previous version: Original HHH-001 body above, proposed and not approved.
- Approval: Approved — complete effective HHH-001 including original body and HHH-001-A1; explicit user approval on 2026-11-13.
- Request and purpose: The user requested that the specification "should cover
  documentation, how to install + proper agent harness isolation". Make those
  delivery requirements explicit and independently verifiable.

### Changes against the previous version

| Section / requirement | Before | After | Reason |
| --- | --- | --- | --- |
| Scope definitions; requirements 6, 13, and 16 | Harness/session identity and parent routing were required, without a complete isolation identity. | Use harness kind, effective profile/config and data/state roots, actual backend instance, and session ID together; independently verify parent ancestry and the Herdr server/tab/pane binding. | Prevent routing collisions and state reuse across profiles, servers, and harnesses. |
| Requirements 1 and 15 | Per-harness install/link/uninstall was required in broad terms. | Installation is explicitly selected per harness and target profile, with idempotent registration, conflict handling, trust instructions, verification, upgrade, and owned-only uninstall. | Make installation reproducible without changing the other harness. |
| Requirements 8, 16, and 18 | Existing-runtime attachment, local state, and scoped helpers were required. | Add explicit configuration, environment, state, observer, credential, context, and cleanup boundaries below. | Ensure the integration preserves native harness isolation. |
| Documentation and acceptance | A short documentation checklist and general validation requirements. | Add complete user-facing documentation and concrete installation/isolation acceptance coverage below. | Make usable documentation and safe installation part of delivery, not a follow-up. |

### Effective installation and documentation requirements

19. Provide a top-level README that explains what the integration does and shows
    the shortest supported path from cloning the public repository to using it.
    Codex and OpenCode each have a self-contained install/link section; using
    one must not require installing, configuring, or running the other.
20. Installation must identify the selected harness and effective target profile
    before writing configuration. Respect the harness's native config-location
    overrides. Resolve configuration, data/database locations, and backend
    endpoint independently; a config-directory override does not prove a private
    server, database, or credential store. Do not redirect an unknown profile to
    another profile's default directory or mutate repository/project
    configuration implicitly.
21. Document exact copyable commands, prerequisites and qualified versions,
    configuration files/entries touched, any hook enablement/trust and restart
    steps, and a verification command or operator procedure. Normal setup is
    user-scoped and needs no elevated privileges or manual watcher launch.
22. Reinstallation/linking is idempotent. Preserve unrelated hooks, plugins,
    native Herdr integrations, permissions, credentials, and configuration. Fail
    clearly on an unmanaged file conflict instead of overwriting it. Uninstall
    removes only proven project-owned registrations, links/files, and helpers;
    it must not disable a shared hook feature needed by other integrations.
23. Document how to update an installation, verify the effective version and
    selected profile, unlink/uninstall, and recover from a moved or missing
    linked checkout. Documentation must match the final supported installer and
    runtime behavior; do not publish speculative commands as working examples.
24. Include the support/capability matrix for each harness, a parent/child usage
    walkthrough, naming behavior, helper lifecycle and local state locations,
    installation ownership boundaries, and troubleshooting for missing panes,
    skipped completed children, unavailable Herdr, unsupported attachment,
    missing trust, stale context, and profile/server mismatch. State known limits
    and separate validated behavior from unverified platform/runtime claims.

### Effective harness isolation requirements

25. Give each harness adapter an explicit boundary. A Codex event is interpreted
    using Codex identity, metadata, configuration, and runtime interfaces only;
    an OpenCode event uses the OpenCode equivalents. Do not infer the harness
    from a title, working directory, or whichever executable/server is easiest
    to find. A common Herdr adapter may share presentation code, not identities.
26. Scope associations, duplicate prevention, locks, observer ownership, and
    suppression records by the composite identity defined in the delta table.
    A matching session ID or working directory in another harness/profile/server
    is never authority to attach, rename, suppress, or clean up its pane.
27. Validate the original parent relationship and actual backend instance before
    acting. A shared daemon's inherited environment, a familiar socket path, or
    a reused pane ID alone does not prove the current binding. On mismatch or
    ambiguity, leave other contexts untouched; do not search for an unrelated
    running agent to use as a substitute.
    Preserve intentional sharing within an existing native backend; do not
    create a new backend or promise separate accounts/databases merely because
    configuration files differ. Require an exact session-to-backend binding.
28. Construct attachment/observer environments for the selected harness and
    profile. Preserve its own effective runtime/configuration and required shared
    terminal environment, while removing foreign harness overrides and stale
    parent/session markers. Do not forward the parent's whole environment as an
    identity record, repurpose HOME, or point one harness at the other's config,
    state, credential, or conversation store.
29. Do not copy prompts, transcripts, model context, credentials, authentication
    headers, permission settings, or model choices between harnesses, profiles,
    or sessions. Native harness delegation remains the owner of any intended
    parent-child context sharing; the integration only attaches presentation
    clients to existing children and reads the minimal required metadata.
30. Scope helper lifetime, retry budgets, diagnostics, and state cleanup to the
    selected harness/runtime/parent binding. A failed or uninstalled Codex
    integration must not stop OpenCode observers or vice versa. Installation and
    cleanup for one profile must not modify another profile's records or panes.
31. Use private user-local runtime state with suitable owner-only access. Keep
    configuration secrets, transcript contents, local absolute paths from real
    users, and runtime records out of published source and documentation
    examples. Do not expose local server authentication in diagnostics.
32. Preserve the child's existing working directory, filesystem access, native
    context boundaries, sandbox, and permissions. This integration does not
    provision source-code isolation, containers, or Git worktrees; the harness
    retains responsibility for those existing choices. Opening a pane must not
    relax isolation or move the child's work to another checkout.

### Additional acceptance and validation

- Follow each harness's documented setup from a clean clone/profile and verify
  the resulting registration, trust instructions, automatic start, and visible
  child pane. Exercise reinstall, upgrade/relink, and uninstall while preserving
  an unrelated pre-existing hook/plugin and an unmanaged conflicting file.
- Demonstrate single-harness installation while the other harness is absent,
  and selected-profile installation while a second profile remains unchanged.
  Validate the commands and paths used in README examples against the actual
  implementation; static documentation review alone is insufficient.
- Qualify Codex and OpenCode simultaneously in separate parent contexts, then
  qualify multiple profiles/backend instances of one harness. Show that child
  attachment, title updates, duplicate prevention, closed-pane suppression,
  restart adoption, and cleanup remain in their owning context. Use controlled
  metadata inputs to check colliding IDs and titles without requiring real ID
  collisions. These are bounded structural/operator checks, not a new automated
  test suite for operational code.
- Check stale/foreign harness environment markers and incorrect backend/Herdr
  bindings: no unrelated pane opens or changes, and attachment does not switch
  profile or server. Verify selected child environment routing without dumping
  secrets, and confirm metadata access avoids foreign conversation stores.
- Disable, fail, or uninstall one harness integration and verify the other
  continues functioning. Check owner-only state access and confirm the source
  tree/documentation contain no runtime state or credentials.

Isolation research references (documentation/source evidence only, not runtime
validation): Codex configuration/state ownership is described in
https://github.com/openai/codex/blob/main/codex-rs/core/src/config/mod.rs .
OpenCode documents config overrides separately from shared-server/database and
credential ownership at https://opencode.ai/docs/config/ ,
https://opencode.ai/docs/cli/ , and https://opencode.ai/docs/cli/providers/ .
Codex `main` evidence must be checked against the qualified release before
depending on a particular override in implementation.

### Preserved behavior and impact

The original body plus this amendment is the complete effective specification.
Requirements 19–32 and the delta table refine the named original requirements;
all other original requirements remain in force. Preserve the public repository
name, Codex/OpenCode scope, native child identity, same-tab unfocused split panes,
one-way title updates, silent no-op outside Herdr, skip of already finished
children, no repeated inference, no duplicate/reopened panes, and retention of
panes that were successfully attached before completion. The project remains
separate from RpiInfrastructure. No PLAN exists or is changed by this amendment.
No installation, isolation, or runtime checks have yet been performed.

### Approval record

- Decision: Approved on 2026-11-13 by the user's explicit response "approve"
  to the complete-specification approval question.
- Approved scope: The entire original HHH-001 body plus amendment HHH-001-A1,
  including documentation, installation, and harness isolation requirements.
- Reviewed pre-approval file SHA-256:
  `c98edbc2c645ccdeff0c54780c86407093fa2d82a91be2fbd6dbf8e24bb542fe`.
- Effective revision: HHH-001 + HHH-001-A1, Approved. This record supersedes
  historical pending-approval statements for this complete effective revision.
- Original body and document-level Status: Proposed are preserved under the
  amendment rules. Approval applies to the complete effective revision, not
  merely the amendment or a header.
- Implementation authority: This specification approval permits PLAN authoring;
  it does not approve a PLAN or authorize implementation in this planning session.

## Amendment 2 — 2026-11-13 — Pin released OpenCode compatibility

- Amendment ID: HHH-001-A2
- Previous version: Complete effective HHH-001 + HHH-001-A1, approved on
  2026-11-13; the preceding approved content remains unchanged.
- Approval: Approved — complete effective HHH-001 including HHH-001-A1 and HHH-001-A2; explicit user approval on 2026-11-13.
- Request and purpose: Correct the OpenCode compatibility assumption discovered
  while preparing the implementation PLAN for the approved user request. The
  earlier research used current documentation whose V2 plugin/event description
  was not qualified against a released runtime. Pin the released interface before
  implementation planning, without changing the requested user experience.

### Changes against the previous version

| Section / requirement | Before | After | Reason |
| --- | --- | --- | --- |
| Scope and definitions: initial qualification targets | OpenCode's documented V2 server-plugin/session API; legacy OpenCode V1 excluded. | OpenCode release `v1.19.5`, source commit `810c0eba1a7348036f8bdf61e6632d0c36c6876c`, using the plugin/event and existing-server attachment interfaces shipped in that release. Codex CLI 0.169.0 and Herdr 0.9.5 remain the other qualification targets. | A release tag provides an auditable implementation target; a generic V1/V2 label did not establish compatibility. |
| OpenCode integration under requirements 1, 4, and 12 | Current V2 server-plugin event subscription was the research basis. | Consume the release-documented plugin callback `event: async ({ event }) => { ... }`, including `session.created`, `session.updated`, and lifecycle/status information supported by the qualified release. Discover parent relationships and running status through that same release's native session metadata/interfaces. | The tagged V2 `PluginContext` has no event-subscription member; the released event callback must not be confused with the newer documentation. |
| Evidence and compatibility: OpenCode existing-session selection | Documentation-level existing-session CLI selection; no version-qualified command. | The released attachment form is `opencode attach <url> --session <id> --mini`, without a prompt. The URL identifies the already running, verified parent backend. Do not use an unqualified `opencode mini --server ...` command from newer docs. | In 1.19.5, mini is an option on the TUI/attach command, not a standalone command. Runtime verification of same-child attachment without a new turn is still required. |
| Scope exclusions; requirements 21, 23, and 24 | Broad legacy-V1 exclusion alongside a V2 API target. | Qualify the named release/interface, document its actual installation and attachment behavior, and reject unqualified interface shapes safely. No blanket exclusion based solely on a V1/V2 label applies to the qualified release. Other release/API variants remain unsupported unless separately qualified. | Preserve useful OpenCode support without claiming compatibility from documentation or version labels alone. |

### Evidence and provenance

- Official release tag and commit:
  https://github.com/anomalyco/opencode/releases/tag/v1.19.5 .
- Tagged attach command, including URL, session, and mini options:
  https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/cmd/attach.ts .
- Tagged TUI command:
  https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/cmd/tui.ts .
- Tagged plugin documentation, including the native event callback:
  https://github.com/anomalyco/opencode/blob/v1.19.5/packages/web/src/content/docs/plugins.mdx .
- Tagged V2 plugin/context source, which does not establish the event subscription
  assumed by the earlier research:
  https://github.com/anomalyco/opencode/blob/v1.19.5/packages/plugin/src/v2/promise/plugin.ts
  and https://github.com/anomalyco/opencode/blob/v1.19.5/packages/plugin/src/v2/promise/context.ts .

These are source/documentation findings only. No OpenCode binary, server, client,
session, or Herdr pane was started, and no runtime compatibility is claimed.

### Preserved behavior and impact

If approved, the original HHH-001 body plus HHH-001-A1 plus this amendment is the
complete effective specification. This amendment supersedes only the compatibility
targets, interface research assumptions, and associated exclusion identified in
the delta table. All other original and HHH-001-A1 requirements remain in force.

Preserve the public repository `alexbanica/harness-herdr-hooks`, Codex and OpenCode
support, automatic hook/plugin lifecycle, running agent-created children in
unfocused panes in the parent's existing tab, exact identity/backend and harness
isolation, one-way name synchronization, installation/documentation requirements,
duplicate prevention, no repeated inference, silent no-op for parents outside
Herdr, skipping already finished children, and retention of panes attached before
completion. No transcript viewer or replacement agent run is introduced.

Acceptance now qualifies OpenCode against the released interface above; all prior
installation, isolation, source/static, and runtime acceptance obligations remain.
The PLAN must use these pinned interfaces and preserve the documented difference
between source evidence and live runtime evidence. No PLAN has been approved or
implemented. RpiInfrastructure remains unchanged.

### Approval record

- Decision: Approved on 2026-11-13 by the user's explicit response "approve"
  to the complete-specification approval question including HHH-001-A2.
- Approved scope: Entire original HHH-001 body plus HHH-001-A1 and HHH-001-A2.
- Reviewed pre-approval file SHA-256:
  `9a410e65ba314af74d91707c0029738e5351dca53b77cfff40342aaa30614577`.
- Current effective revision: HHH-001 + HHH-001-A1 + HHH-001-A2, Approved.
  Historical pending-approval statements do not describe this current revision.
- Original body, document-level Status: Proposed, and preceding approval records
  are preserved under the amendment rules. This approves the complete effective
  specification, not just the latest delta.
- Implementation authority: PLAN authoring only in this planning session; no
  PLAN approval or implementation authority is inferred from this decision.
