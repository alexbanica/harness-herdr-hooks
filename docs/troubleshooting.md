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
- **Client-bound install refuses the executable:** confirm the absolute path
  names the pinned patched `rust-v0.172.0` executable, its recorded digest is
  current, and the capability marker is present. Build only from the pinned
  tag and patch documented in [Codex setup](install-codex.md). The standard
  Cargo build and focused test are currently blocked by locked dependency
  resolution; see [validation](validation.md). Do not treat a version string
  alone as client-binding qualification.
- **Client binding reports no display or rejects startup:** verify the
  managed adapter launched the local interactive client and that its private
  Herdr endpoint is the selected profile's pinned endpoint. Admission requires
  the helper's terminal to match one protocol-22 pane tty. Missing tty data,
  stale inherited coordinates, multiple matching panes, a direct/native
  launch, a background client, or shim bypass gives no pane authority. Check
  that the profile's legacy Herdr Codex session reporter is absent; managed
  installation rejects that conflict.
- **You need a fresh-process pane control:** inspect `herdr workspace list`
  and `herdr pane list`, then name the selected working pane explicitly in
  `herdr pane split --pane PANE_ID --direction right --cwd PATH --no-focus`.
  Capture the pane ID from that acknowledgement and pass it explicitly to
  `herdr agent start NAME --kind codex --pane NEW_PANE_ID`. Independently check
  that the new pane is in the selected existing tab. This verifies explicit
  pane targeting and process start only; a fresh no-argument Codex process
  does not prove attachment to an already created child.
- **Creation is not attached after a view change:** only an acknowledged
  active lease and a matching one-use receipt for the initiating client's
  admitted user turn and exact returned child can authorize placement. Resume,
  native delegation, an ambiguous client, or a stale receipt does not qualify.
  Inspect the existing tab and durable effect status before retrying; an
  unresolved pane effect is not replayed.
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
