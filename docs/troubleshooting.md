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
  observed trust/load, backend, observer, and pane outcome. Unknown is not
  success. Verify Codex CLI and running app-server 0.170.0, Herdr 0.9.5/protocol
  22, and exact selected profile/backend binding. The verified default daemon
  and explicit Unix endpoints are supported; `--no-daemon` and ambiguous modes
  fail closed. Outside-Herdr events remain silent. Do not bypass trust or change
  socket permissions.
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
- **Pane title is absent or unexpected:** names come one way from the native
  session title after sanitization. Pane names do not control native session
  titles. Duplicate prevention uses session identity, not title.
- **Helper or registration is removed:** uninstall revokes this integration's
  own registration/helper. State records are retained for recovery; panes and
  agents are left untouched. Verify `status` for the selected config root.

Native user-owned approval/trust and profile reload must follow Codex's own
controls. This delivery has not yet demonstrated active-profile hook loading,
native child display/cleanup, or ordinary launch routing. No automatic daemon
restart or trust bypass is supported. OpenCode native qualification and the
predecessor macOS gap remain separate.
