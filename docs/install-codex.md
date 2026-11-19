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

Native executable discovery skips candidates that already resolve through a
managed adapter. Reinstall reuses the owned concrete adapter entry and its PATH
tail/native settings rather than selecting the adapter itself or adding another
prefix. The adapter does not search another profile or delegate across profile
boundaries.

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
observed native trust/loading, loaded helper revision, backend binding,
observer health, and pane outcomes. Observer states distinguish `running`,
`stale`, `unknown`, and `ended`; a registered source path does not prove that
a running parent loaded that revision. Native thread `notLoaded` or missing
items alone is not terminal evidence. A successful native status read reporting
`notLoaded` can participate in cleanup only with exact matching terminal-turn
metadata and no newer running work. Isolated operator checks passed. A live bare `codex` invocation was
acknowledged once and placed in an unfocused pane in the selected tab; the
confirmation UI remained open and no confirmation was answered. Native
same-thread/subagent attachment, no-added-turn behavior, terminal cleanup,
client exit to a usable shell, and current-revision runtime loading remain
unverified. See
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

The observed native launch above established acknowledgement and pane placement
only; it did not reach confirmation, client exit, or shell retention. A missing
child from discovery or a missing/unloaded helper is never proof of terminal
completion. Codex cleanup requires positive terminal metadata for the matching
turn/task generation, absence of newer running work, and revalidation of the
integration-owned pane/process. Manually closed children are suppressed from
reopening. Unknown or ambiguous ownership is retained. The adapter preserves
the selected profile's existing PATH tail and unrelated native configuration.

## Uninstall

Use the same profile selection as installation:

```sh
bin/harness-herdr-hooks uninstall codex
bin/harness-herdr-hooks uninstall codex --config-dir /path/to/codex-profile
```

Uninstall removes only unchanged owned handlers, adapter files, and PATH edit.
It preserves changed/conflicting entries and does not change other profiles,
terminate agents, or close panes.
