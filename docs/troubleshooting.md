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
- **No pane appears:** confirm that the parent is actually in the intended
  Herdr pane, the native event was loaded, the Herdr protocol is supported, and
  the selected backend is explicitly qualified. Outside-Herdr events are
  intentionally silent. Incomplete or ambiguous identity fails closed. Native
  hook/plugin trust and reload behavior are not yet fully qualified, so this
  remains a DRAFT acceptance gap; do not change permissions or restart Herdr to
  compensate.
- **Codex reports missing/ambiguous backend:** start the foreground Codex
  process with its intended explicit `--remote unix://PATH` or `--remote=URI`
  endpoint and verify the user-owned socket exists. Implicit daemon or embedded
  fallback is intentionally refused. Do not change daemon settings.
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

Native user-owned approval/trust and any reload/restart steps must follow the
harness's own controls. Those procedures are not yet qualified here; no
automatic server restart or trust bypass is supported.
