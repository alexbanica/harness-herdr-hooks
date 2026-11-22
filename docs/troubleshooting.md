# Troubleshooting

The project is DRAFT / experimental. A successful install or `status` confirms
registration consistency only; it does not establish native trust, plugin/hook
loading, or complete pane attachment support.

- **Installer reports a conflict or changed owned entry:** inspect the selected
  profile's path manually. The installer preserves unmanaged/changed content;
  do not replace it by guesswork. Use the same `--config-dir` on status,
  reinstall, and uninstall.
- **Checkout moved or is missing:** `status` reports whether the recorded source
  still resolves. From the moved checkout, run `install` for the same harness
  and exact config root, then verify with `status`. To remove registrations whose
  old checkout is missing, use another trusted checkout's `uninstall` command
  with that same config root; ownership checks still apply.
- **No Codex pane appears:** confirm that the selected profile was loaded by a
  user-owned parent after install and that any native trust prompt for changed
  hooks was handled. Check status fields separately: registration/configuration,
  loaded helper revision, observed trust/load, backend, observer, and pane
  outcome. Observer states are `running`, `stale`, `unknown`, or `ended`. A
  registered path or source checkout does not prove the running helper loaded
  that revision. A native thread `notLoaded` response or missing items alone
  is not terminal evidence; it can participate only with successful status
  evidence plus exact matching terminal-turn metadata and no newer running work.
  Verify the required app-server interface and exact selected profile/backend
  binding, plus Herdr 0.9.5/protocol 22. Eligibility depends on successful
  initialization, identity, required methods, and valid required response
  fields. If a required step
  fails, use the concise diagnostic's stage and method to identify the failed
  contract. The observed daemon release is included when available. A reported
  release is diagnostic metadata. Supported endpoints are the verified default
  daemon and verified explicit Unix sockets. Outside-Herdr events remain silent. Do not bypass trust or change
  socket permissions.
- **Codex app-server method or response is incompatible:** the bounded error
  identifies the failing transport, initialization, method, or response stage
  and names the requested method, with the daemon release when available. It
  omits credentials, transcript content, and raw response dumps.
- **Ordinary `codex` command does not route:** the parent must load the selected
  profile's concrete `shell_environment_policy.set.PATH` after installation.
  Absolute executable paths, deliberate PATH overrides, informational/tooling
  commands, `exec`, resume, remote hosted backends, and `--no-daemon` sessions
  are outside routing. The adapter does not start another session when routing
  cannot be verified; inspect the bounded status/diagnostic and do not retry an
  uncertain launch.
- **OpenCode event is disabled:** the selected server must be its foreground
  loopback server with the expected unauthenticated local API. The plugin is
  disabled when `OPENCODE_CONFIG`, `OPENCODE_CONFIG_CONTENT`, or `OPENCODE_DB`
  is set. A config-directory override selects registration only; it does not
  select private data/state/backend/account. Correct the intended native profile
  using its normal controls; do not copy credentials or provider data.
- **A child is skipped:** completed, unknown-status, stale, unattachable, or
  unrelated children are not safe to open. No old sessions are backfilled.
  OpenCode `idle` alone does not prove that a session is finished or attachable.
  This is expected fail-closed behavior, not a prompt to resume the parent.
- **An owned Codex pane remains open after a child disappears:** disappearance
  from discovery, a missing or unloaded helper, and `notLoaded` item data do
  not prove completion. Cleanup requires positive terminal metadata for the
  exact turn/task generation, no newer running work, and revalidated pane and
  process ownership. Manual closure suppresses reopening for that child. A
  helper replacement uses the parent-owned bounded operation and only a proven
  integration-owned helper may be retired. Read-only `status` does not retire
  or reconcile a helper. Unknown, unowned, or ambiguous panes are retained.
- **Initial session baseline could not be established:** new-session attachment
  stays skipped until the observer obtains and persists the initial baseline.
  This avoids treating pre-existing sessions as new children; inspect observer
  status and allow the next normal lifecycle observation to retry.
- **Pane title is absent or unexpected:** names come one way from the native
  session title after sanitization. Pane names do not control native session
  titles. Duplicate prevention uses session identity, not title.
- **Helper or registration is removed:** uninstall revokes this integration's
  own registration/helper. State records are retained for recovery; panes and
  agents are left untouched. Verify `status` for the selected config root.

Native user-owned approval/trust and profile reload must follow Codex's own
controls. A live bare `codex` invocation was acknowledged once in an unfocused
Herdr tab, and its launch payload was removed; its pane remained at the native
confirmation UI. This does not demonstrate same-thread/subagent attachment,
completion cleanup, client exit to a usable shell, or active-profile loading of
the current source revision. No automatic daemon restart or trust bypass is
supported. OpenCode native qualification and the predecessor macOS gap remain
separate.

## Standalone task discovery

For a missing standalone task pane, inspect `status` fields independently:
recognition, verification, attachment, and `current_health`. Health describes
the latest observer pass; a later healthy pass does not erase an earlier
recognition or attachment outcome. Bounded reasons include `parent_file_missing`
or `parent_file_mismatch` (the exact parent rollout cannot be bound),
`unsafe_parent_file`, `unsupported_envelope` / `unsupported_record_format`,
`metadata_unavailable` / `status_deferred`, `task_mismatch`,
`invalid_cwd` / `cwd_mismatch`, `candidate_expired`, `retry_exhausted`, and
`attachment_pending`. These diagnostics do not include prompt or transcript
content. Only successful typed `codex_tui.create_thread` completion records
from the verified parent qualify; `PostToolUse`, `exec` text, native delegation
ancestry, titles and timestamps are not substitutes. No historical task
backfill occurs.

Live qualification requires the actual Herdr-bound parent pane/session to
match the invoking Codex parent and its native rollout file. A different
Codex session ID is an identity mismatch; do not compensate with a different
profile, task, or pane or restart the shared daemon. Keep any retained
installation source in place until an explicitly authorized replacement is
installed and verified. See [validation](validation.md).

## HHH-005 subagent tabs

- **No subagent tab appears:** creation is lazy; there must be a newly eligible,
  running, attachable child under a verified Herdr main session. Existing or
  finished children are not backfilled. Check the bounded status diagnostic
  and selected harness/profile/server binding. Missing or ambiguous ancestry
  fails closed.
- **Nested child appears elsewhere or no tab is reused:** only verified native
  ancestry and the persisted root association establish sharing. Titles, cwd,
  short IDs and inherited environment do not. Do not rename or adopt a tab to
  repair an identity mismatch; inspect the reported root/server/workspace and
  association state.
- **Tab label is generic or changed:** before root title metadata arrives, the
  harness name is used. Root title changes update a still-owned tab; child
  title changes affect only the pane. The label is sanitized and bounded, and
  its displayed ID may expand to resolve collisions. A manual label does not
  establish ownership.
- **An empty tab remains:** the integration closes only a positively owned tab
  whose contents are verified empty. Unknown ownership or contents fail
  closed. Retained OpenCode child panes and user-added panes keep a tab open.
  Removing the final pane manually is supported; a later genuinely new child
  may create a new tab, while duplicate events for already removed displays
  stay suppressed.
- **Workspace coordination reports an unsafe anchor:** the canonical per-UID
  `.local/state` anchor is resolved from the OS account record and rejects
  symlinks, wrong ownership, unsafe permissions, or unsafe path components. It
  deliberately does not fall back to profile-specific coordination. Correct
  the account-home path through normal system administration; do not override
  it with `HOME`, XDG, or another profile variable.
- **Native behavior is uncertain:** isolated tests and targeted Herdr protocol
  operations do not prove native Codex/OpenCode attachment or grouping. Current
  Codex hook trust/reload remains user-owned; OpenCode native qualification
  was unavailable. Do not infer native support from successful installation.
