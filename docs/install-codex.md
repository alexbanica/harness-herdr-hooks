# Codex installation

The selected Codex configuration root is `CODEX_HOME`, or `~/.codex` when it is
unset. Install adds owned `SessionStart`, `SubagentStart`, and `SubagentStop`
handlers to that root's `hooks.json`. It also installs a private `codex`
command adapter and prepends its directory to that profile's concrete
`shell_environment_policy.set.PATH`, preserving the original PATH tail and
other settings. Private integration files use restricted permissions; install
does not change Codex daemon settings, socket permissions, or hook trust.
Python 3.11+, POSIX `sh`, and a repository checkout are required; OpenCode is
not.

## Install and inspect

```sh
git clone https://github.com/alexbanica/harness-herdr-hooks.git
cd harness-herdr-hooks
bin/harness-herdr-hooks install codex
bin/harness-herdr-hooks status codex
```

To target another Codex profile, use the same explicit path for every command:

```sh
bin/harness-herdr-hooks install codex --config-dir /path/to/codex-profile
bin/harness-herdr-hooks status codex --config-dir /path/to/codex-profile
```

The installer preserves unrelated hooks/settings and refuses conflicting,
ambiguous, changed, symlinked, or unowned destinations. Reinstall from a moved
checkout to update the same profile; inspect `status` afterward. Do not delete
or replace a conflicting path by guesswork.

## Runtime prerequisites and limits

The qualification target is Codex CLI and running app-server 0.170.0, Herdr
0.9.5 / protocol 22, Python 3.11+, POSIX `sh`, and the selected Codex
executable in `PATH`. Codex may use its verified selected-profile shared
default daemon or an explicit foreground Unix endpoint such as
`codex --remote unix:///absolute/path/to/codex.sock` (also
`--remote=unix:///absolute/path/to/codex.sock`). Explicit `--remote unix://`
selects that profile's native control socket. The exact process, socket alias
and target, owner, private directory, backend incarnation, profile, and Herdr
parent binding are checked. Missing Herdr argv is supported by independent
process evidence. `--no-daemon` and unknown launch modes are refused.

The installer writes a concrete PATH value because Codex's shell environment
configuration does not expand a literal `$PATH`. The selected profile must
load the changed configuration before future shell commands see the adapter;
reload/restart it through normal user controls. An already-running parent does
not acquire the change automatically. If Codex requests trust for changed
hooks, use its native trust flow. Installation does not bypass trust, restart an
active session, or alter daemon settings.

`status` reports registration and adapter configuration separately from
observed native trust/loading, backend binding, observer health, and pane
outcomes. It also reports task discovery stages separately: record recognition,
independent native task verification, and attachment. `current_health` describes
the latest observer pass; it does not erase meaningful stage/history outcomes.
Unknown means not observed, not success. Isolated operator checks passed, but
live automatic standalone capture and attachment have not passed in a correctly
bound parent. See
[validation](validation.md) and [troubleshooting](troubleshooting.md).

The adapter routes supported ordinary interactive `codex` shell commands from
a verified Herdr parent. It starts the native CLI once in an unfocused pane in
the same tab, preserving profile, cwd, arguments, and requested prompt; after
client exit it leaves a usable shell. Informational commands, tooling
subcommands, `exec`, existing-session resume, absolute executable paths,
deliberate PATH bypasses, remote hosted backends, and `--no-daemon` embedded
sessions are outside this routing qualification and retain native behavior.
Outside Herdr, the adapter delegates normally. The adapter's bounded launch
payload expires after 120 seconds if not claimed; it does not persist prompts
as retained metadata.

## Uninstall

Use the same profile selection as installation:

```sh
bin/harness-herdr-hooks uninstall codex
bin/harness-herdr-hooks uninstall codex --config-dir /path/to/codex-profile
```

Uninstall removes only unchanged owned handlers, adapter files, and PATH edit.
It preserves changed/conflicting entries and does not change other profiles,
terminate agents, or close panes.

## Standalone task discovery

The qualified capture input is the local Codex app/TUI rollout record for a
successful `codex_tui.create_thread` completion. Recognition requires the exact
typed `event_msg` / `item_completed` association and a returned child ID; the
verified parent pins the backend authority; independently verified native
task metadata supplies the task cwd. This is not
`PostToolUse` delivery, parsed `exec` JavaScript, or native Codex delegation
ancestry. A standalone task remains a separate session, and its pane is retained
after completion or client exit. No prompt is added. See
[contracts](contracts.md) for bounds and exclusions.
