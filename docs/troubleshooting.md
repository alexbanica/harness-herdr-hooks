# Troubleshooting

The project is DRAFT / experimental. Installation status confirms registration
state only; it does not establish live event delivery, attachment, no-added-turn
behavior, or client exit to a usable shell.

- **Installer reports a conflict or changed entry:** inspect the selected
  profile's path. The installer preserves unmanaged or independently changed
  content. Use the same `--config-dir` for status, reinstall, and uninstall;
  do not replace a conflict by guesswork.
- **Checkout moved or is missing:** from another trusted checkout, run
  `install` or `uninstall` against the same config root and inspect `status`.
  Ownership checks still apply.
- **Old Codex subagent hooks remain:** a controlled reinstall removes only
  unchanged managed `SubagentStart`/`SubagentStop` registrations and installs
  the retained `SessionStart` hook. Independently changed and unmanaged hooks
  remain. A running Codex process may still have old code loaded; reload using
  normal Codex controls and follow any trust prompt.
- **Old OpenCode plugin remains:** use the current checkout's ownership-checked
  `status opencode` and `uninstall opencode` with the original config
  directory. The retired integration cannot be newly installed. A running
  OpenCode process may retain already loaded code until normally reloaded.
- **No standalone pane appears:** check that Codex produced a successful typed
  `codex_tui.create_thread` result from the exact verified parent, and that the
  returned child is available on the selected profile/backend. The parent must
  map through current Herdr session bindings to a unique existing tab. A
  missing mapping or matches spanning tabs are skipped. Standalone placement
  does not require a foreground PID or process tree. Do not substitute a
  similarly named session, another profile, or a different pane.
- **A standalone task is skipped or deferred:** `status` separates
  recognition, verification, attachment, and current observer health. Bounded
  reasons can identify missing/mismatched parent rollout, unsupported record,
  unavailable backend metadata, task mismatch, invalid/mismatched cwd,
  expired candidate, retry exhaustion, or attachment pending. These details
  omit prompt and transcript content. Only newly appended typed successful
  creation records are considered; no historical task backfill, `PostToolUse`,
  parsed `exec` text, native delegation ancestry, or title/time inference is
  used.
- **A pane split or attachment outcome is uncertain:** inspect the exact
  destination tab and pane/session references before taking action. Durable
  intents prevent the helper from repeating a split or managed start after a
  lost acknowledgement or crash. It retains the pane and bounded unresolved
  outcome; it does not guess ownership, close the pane, or retry the effect.
- **Attachment adds a prompt or turn:** the standalone route is designed to
  resume the exact verified session through Herdr's managed Codex route without
  prompt submission. This behavior is not established by the current live
  evidence; report the observed session and status rather than retrying.
- **The standalone client exits:** its pane is intended to remain open with a
  usable shell through completion, cancellation, idle, and client exit. This
  has not been verified live in the current attempt.
- **A fresh interactive `codex` command does not route:** that separate route
  requires a verified Herdr parent and the selected profile's concrete
  `shell_environment_policy.set.PATH` to be loaded. Its existing process and
  launch checks still apply. Unsupported commands, resume/fork, absolute paths,
  deliberate PATH bypasses, remote hosted backends, and `--no-daemon` retain
  native routing. Do not retry an uncertain launch.
- **No pane automation occurs outside Herdr:** this is expected. The helper
  does not establish a destination from a title or environment marker alone.
- **State remains after uninstall:** uninstall revokes the integration-owned
  registration and does not terminate agents, close panes/tabs, or erase
  retained state. State is retained for recovery.

Current source checks and the latest live attempt are summarized in
[validation](validation.md). Historical native-subagent/tab qualification
notes do not describe current behavior.
