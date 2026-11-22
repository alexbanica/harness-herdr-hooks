# Isolation boundaries

The integration acts only when the parent is proven to be in a Herdr pane and
the selected harness event agrees with that pane's native session and backend.
Herdr server, workspace, tab, pane, harness kind, profile/config/data/state
roots, backend instance, and session identity are checked as applicable. A
matching title, working directory, session ID, inherited marker, or config path
alone is not authority. If identity or ancestry is incomplete or ambiguous, the
event is skipped or fails closed. Outside Herdr, the helper returns before
reading event input or touching integration state.

## Harness boundaries

- **Codex:** Only bounded Codex hook metadata and native app-server interfaces
  are used. Codex 0.170.0 supports the verified selected-profile shared default
  daemon and explicit Unix `--remote` endpoints; `--no-daemon` and unknown
  launch modes are refused. The socket alias/target, user ownership, private
  directory, process identity, and backend incarnation are pinned. Optional
  Herdr foreground argv is not required. `CODEX_HOME` (or `~/.codex`) selects
  the profile; it does not prove that the backend is private. Codex's owned
  command adapter is added only to that profile's literal shell PATH setting.
- **OpenCode:** Only OpenCode plugin/API identity is used. The runtime is bound
  to the parent foreground server PID and loopback unauthenticated API. The
  plugin disables itself if `OPENCODE_CONFIG`, `OPENCODE_CONFIG_CONTENT`, or
  `OPENCODE_DB` is set. `OPENCODE_CONFIG_DIR` or XDG config selection chooses
  registration only; config, data, state, server, account, and provider are
  separate resources. A config override does not create private backend or
  account isolation.

The adapters do not copy credentials, provider configuration, arbitrary
environment maps, conversation text, or transcripts into integration state.
Ordinary interactive Codex launch arguments are carried in a private bounded
payload for at most 120 seconds, deleted after acknowledgment or expiry, and
not retained as metadata. Child attach
clients receive a bounded allowlist of environment values, not the full parent
environment. No provider or account is created by installation. The OpenCode
loopback API itself is unauthenticated, so the current binding is not evidence
of independent account isolation.

## State and cleanup

By default, private runtime metadata is stored below
`$XDG_STATE_HOME/harness-herdr-hooks` or `~/.local/state/harness-herdr-hooks`.
`HARNESS_HERDR_STATE_ROOT` can select an absolute integration state root.
Directories/files are created with private permissions. Records contain
identity/binding, observer, and pane lifecycle metadata needed for recovery and
duplicate suppression; uninstall retains these records. Uninstall revokes the
registration and stops this integration's own helper. It does not terminate
agents, close panes, remove providers, or claim that retained records were
deleted.

Only a verified eligible child can be attached or renamed. Pane labels are
one-way from the native title, with controls removed and display limits applied;
titles are never identity. Manual close suppression and existing pane reuse are
scoped to verified context. The implementation uses a context-scoped startup
baseline, pending verified-creation exceptions, and persisted owned records;
it does not expose a public revision or generation API.

## Qualification boundary

Source/operator and controlled API checks cover bounded parsing, context
verification, synthetic event behavior, and cleanup cases recorded in
[validation](validation.md). Native Codex selected-profile loading/trust,
cross-profile/backend isolation, authorized real child display and completion
cleanup, ordinary launch routing, and all race/concurrency paths remain
unqualified. macOS runtime is a separate outstanding predecessor gap. These
remain acceptance work; no complete support claim is made.

## Standalone Codex task records

Codex standalone discovery reads only newly appended qualified creation records
from the exact verified parent's owner-controlled rollout file inside the
selected profile's sessions directory. The typed event nominates a child;
native metadata from that same backend independently establishes task identity,
cwd and attachability. No other profile/backend is searched to make a candidate
fit. Persistent state contains bounded IDs, cursor/file identity, hashes for an
optional normalized cwd, context/destination pins, and retry/outcome metadata;
it excludes prompts, raw tool results, transcript text and partial record
bytes. This local-record association is not cryptographic ancestry proof and
does not establish native subagent lineage.

## HHH-005 subagent-tab state

Tab identity is rooted in the full verified main-session context, harness,
profile/backend incarnation, Herdr server and workspace. Titles, cwd, inherited
environment and displayed short IDs are not ancestry or ownership proof.
Siblings and verified nested children share the root association; independent
sessions do not. Existing panes are not migrated, and a stale or invalidated
association cannot authorize adoption or movement to another tab.

Root-specific tab claims, child bindings and lifecycle records remain in the
selected integration state root. To coordinate label reservations and tab
operations across profiles and both harnesses, the implementation uses one
canonical private workspace anchor beneath the current OS UID's account home
(`.local/state`), resolved from the account database rather than inherited
`HOME`, XDG, or profile variables. It admits path components through no-follow
directory checks, rejects symlinks, non-directories, unsafe ownership or
permissions, and does not fall back to profile-local coordination. Missing
`.local/state` components may be created only below an admitted owner-controlled
parent with private mode. Existing safe modes are preserved. This anchor is
initialized only after verified Herdr runtime binding; it is not a public
configuration override. Diagnostics identify rejected anchor components
without weakening isolation.

Cleanup revalidates ownership and contents and coordinates against new
attachments. Empty managed tabs may close; retained children and user work are
never closed to manufacture emptiness. Source tests of the anchor and protocol
fixtures are not evidence of native harness qualification; see
[validation](validation.md).
