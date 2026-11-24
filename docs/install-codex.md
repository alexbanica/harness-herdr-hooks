# Codex installation

The selected profile is `CODEX_HOME`, or `~/.codex` when unset. Install
registers the managed `SessionStart` hook and installs a private `codex`
command adapter in that profile. The adapter directory is prepended to the
profile's concrete `shell_environment_policy.set.PATH`, preserving its
existing tail and unrelated settings. Install does not change Codex daemon or
socket settings and does not bypass hook trust. Python 3.11+, POSIX `sh`, and
a repository checkout are required.

## Install and inspect

```sh
git clone https://github.com/alexbanica/harness-herdr-hooks.git
cd harness-herdr-hooks
bin/harness-herdr-hooks install codex
bin/harness-herdr-hooks status codex
```

### Opt in to client-bound pane placement

The client-bound route is opt-in per profile and requires the patched pinned
Codex executable. Build it from OpenAI Codex tag `rust-v0.172.0`, commit
`3d86e43b075adeba2193ec5c22ac92f55afd82e6`, source tree
`82eb586eff8b4d378eafc4fec640605ef7d6dbf1`, with Rust `1.99.1`. The delivered
patch is `integrations/codex/client-pane-binding.patch`, SHA-256
`f5a1a6b145d2acdc082db878858dc1c3aef172c47629be4dd8acefb07896b046`.
Use the pinned toolchain and verify a disposable checkout before applying the
patch:

```sh
git clone https://github.com/openai/codex.git /tmp/codex-client-binding
git -C /tmp/codex-client-binding checkout 3d86e43b075adeba2193ec5c22ac92f55afd82e6
test "$(git -C /tmp/codex-client-binding rev-parse 'HEAD^{tree}')" = 82eb586eff8b4d378eafc4fec640605ef7d6dbf1
cd /tmp/codex-client-binding/codex-rs
rustc --version
git apply --check /path/to/harness-herdr-hooks/integrations/codex/client-pane-binding.patch
git apply /path/to/harness-herdr-hooks/integrations/codex/client-pane-binding.patch
cargo build --locked -p codex-cli
cargo test --locked -p codex-tui herdr_display_binding
```

Then enable the route for the selected profile, using the absolute path to the
built executable:

```sh
bin/harness-herdr-hooks install codex --client-binding-codex /absolute/path/to/codex
bin/harness-herdr-hooks status codex
```

The installer checks the pinned version and capability marker, executable
ownership, canonical path and digest, and records the executable in its
profile manifest. The route starts only through the managed local interactive
adapter. Admission requires a private authenticated local Herdr socket.
Codex session checks separately use the selected profile's pinned local Codex
endpoint. These endpoints serve different purposes. Remote or ambiguous
endpoints are not admitted. The existing legacy Herdr Codex session
reporter must be absent from that profile; installation stops on that conflict.
Unconfigured profiles and excluded direct/native launch routes retain their
existing behavior. A claimed standalone child must be launched through the
verified shim and publish the exact child lease matching its durable pane
claim; bypassing the shim does not qualify.

For another profile, use the same explicit config directory for each command:

```sh
bin/harness-herdr-hooks install codex --config-dir /path/to/codex-profile
bin/harness-herdr-hooks status codex --config-dir /path/to/codex-profile
```

The installer preserves unrelated hooks/settings and refuses conflicting,
ambiguous, changed, symlinked, or unowned destinations. Reinstall from a moved
checkout against the same profile and inspect `status`. Do not delete or
replace a conflicting path by guesswork.

## Upgrade from subagent/tab integration

An upgrade retires only unchanged managed `SubagentStart` and `SubagentStop`
entries and installs the retained `SessionStart` hook. Independently changed
or unmanaged entries are preserved. Old sessions, panes, tabs, history, and
state records are not migrated or removed. A running Codex process that has
already loaded older hook code is not stopped by install; use the normal
user-controlled profile reload/restart process before relying on the new
registration. If Codex requests trust for changed hooks, use its native trust
flow. Do not bypass trust or restart a shared daemon automatically.

## Runtime behavior and limits

With the opt-in enabled, pane authority comes from the exact interactive TUI
client's verified terminal and active conversation lease. The helper compares
the duplicated PTY identity to a unique protocol-22 Herdr pane tty through the
authenticated Herdr socket. Codex session checks use the selected profile's
pinned local Codex endpoint. Missing tty data, a mismatch, stale coordinates,
multiple possible displays, or a changed/disconnected view grants no pane
effect. After resume, a conversation qualifies only after its new active lease
has been acknowledged. A successful creation receipt is accepted only for the
exact parent, own admitted user turn and exact returned child. The effect still targets one
unfocused pane in the same workspace and tab and resumes that exact child.

For standalone tasks, the local Codex app/TUI rollout record must report a
successful `codex_tui.create_thread` result associated with the verified
parent. The exact returned session is checked against the selected Codex
backend. Its origin must resolve through current Herdr session bindings to one
existing tab. Multiple matching panes in that same tab are acceptable; a
missing or cross-tab-ambiguous destination is skipped. This path does not use
foreground PID, process arguments, or process-tree membership to select the
parent or attach the session. It does require the verified Codex profile,
backend/session identity, and current Herdr parent binding.

The standalone path opens or reuses one pane in that existing tab. It attaches
the exact session without sending a prompt or adding a turn, retains the pane
through idle, completion, cancellation, and client exit, and leaves a usable
shell after exit. Pane split and managed start each have durable one-shot
intents. Missing acknowledgements or crashes leave a bounded unresolved
outcome; the helper does not blindly repeat an effect or close the pane.

The separate ordinary interactive route applies its existing process and
launch checks to supported fresh Codex shell commands. It starts once in a pane
in the caller's existing tab, carrying the requested prompt and arguments, and
leaves a usable shell after exit. Resume/fork and other excluded commands keep
native routing. Unsupported or uncertain launch modes are not retried by the
adapter.

`status` separates registration/configuration from observed runtime and pane
outcomes. A registered hook or source path does not prove that a running
profile loaded the current code. Current source assurance and the latest
native attempt are summarized in [validation](validation.md); live capture,
exact same-tab attachment, no-added-turn evidence, usable shell after exit,
and current-revision runtime loading remain unverified.

## Uninstall

```sh
bin/harness-herdr-hooks uninstall codex
bin/harness-herdr-hooks uninstall codex --config-dir /path/to/codex-profile
```

Uninstall removes only unchanged owned handlers, adapter files, and PATH edit.
It preserves changed or conflicting entries and does not change other
profiles, terminate agents, close panes/tabs, or erase retained state.

## Standalone discovery limits

Only newly appended, typed successful creation records are considered. The
exact record must correlate the parent, turn, item, and returned child ID;
the selected backend independently verifies the session. Historical tasks are
not backfilled. Native `PostToolUse` delivery, parsed `exec` JavaScript,
delegation ancestry, and title/cwd/time inference are not used. The pane is
retained after task completion and client exit. See the detailed
[contracts](contracts.md) and [isolation boundaries](isolation.md).
