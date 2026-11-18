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

- **Codex:** Only Codex hook payload and native app-server interfaces are used.
  The foreground Codex process must select an explicit `--remote unix://PATH`
  or `--remote=URI` endpoint. The selected socket is checked as a user-owned
  socket with a pinned incarnation. The integration refuses implicit shared
  daemon and embedded fallback. `CODEX_HOME` (or `~/.codex`) selects the Codex
  profile; it does not prove that the backend is private.
- **OpenCode:** Only OpenCode plugin/API identity is used. The runtime is bound
  to the parent foreground server PID and loopback unauthenticated API. The
  plugin disables itself if `OPENCODE_CONFIG`, `OPENCODE_CONFIG_CONTENT`, or
  `OPENCODE_DB` is set. `OPENCODE_CONFIG_DIR` or XDG config selection chooses
  registration only; config, data, state, server, account, and provider are
  separate resources. A config override does not create private backend or
  account isolation.

The adapters do not copy credentials, provider configuration, environment
maps, conversation text, or transcripts into integration state. Child attach
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
[validation](validation.md). Full native cross-profile/backend isolation,
authorized real child attach, native trust/reload, all race/concurrency paths,
and macOS runtime behavior are not qualified. These remain acceptance work; no
complete support claim is made.
