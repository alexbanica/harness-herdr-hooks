# Codex installation

The selected Codex configuration root is `CODEX_HOME`, or `~/.codex` when it is
unset. The installer adds owned command handlers for `SessionStart` and
`SubagentStart` to that root's `hooks.json`; it does not change `config.toml`,
permissions, daemon settings, or hook trust. It requires Python 3.11+, POSIX
`sh`, and a checkout of this repository. It does not require OpenCode.
The same root contains the private `.harness-herdr-hooks.json` ownership
manifest and `.harness-herdr-hooks.lock` serialization file. The lock and an
empty `hooks.json` may remain after uninstall.

## Install and inspect

From the public repository, select the source branch explicitly because the
default `main` branch contains planning artifacts until the source PR is merged:

```sh
git clone --branch feat/initial-hooks https://github.com/alexbanica/harness-herdr-hooks.git
cd harness-herdr-hooks
bin/harness-herdr-hooks install codex
bin/harness-herdr-hooks status codex
```

To target a different Codex profile, use the same explicit configuration path
for each command:

```sh
bin/harness-herdr-hooks install codex --config-dir /path/to/codex-profile
bin/harness-herdr-hooks status codex --config-dir /path/to/codex-profile
```

The installer preserves unrelated hooks and refuses an identical unmanaged
handler or a changed/ambiguous owned entry. `status` reports whether the
registration and source checkout still match. To update or recover after moving
the checkout, run `install` again from its new location for the same profile;
inspect `status` afterward. Do not delete or replace a conflicting path by
guesswork.

## Runtime prerequisites and limits

The supported target is Codex CLI 0.169.0, Herdr 0.9.5 / protocol 22, Python
3.11+, POSIX `sh`, and the selected Codex executable in `PATH`. For child
observation, start Codex in the Herdr pane with an explicit native foreground
backend, for example `codex --remote unix:///absolute/path/to/codex.sock` (the
equivalent `--remote=unix:///absolute/path/to/codex.sock` form is accepted).
Choose the real socket path for the intended backend. The integration verifies
that selected endpoint against the foreground process and socket; it refuses an
implicit daemon or embedded fallback. Do not change Codex daemon settings to
make it pass.
An explicit empty `--remote unix://` operand is also recognized and resolves
to the selected Codex home's native control socket.

The managed hooks and source paths have passed isolated operator checks, but
native hook feature enablement/trust and reload behavior are not fully
qualified. Follow Codex's normal native review/trust procedure if it presents
one; no trust-bypass setting or flag is documented here. Whether a user-owned
reload or restart is needed after installation has not been qualified. Do not
assume that a successful installer `status` means the native hook loaded or
that a child pane will open. Native no-added-turn child attachment and full
profile/backend/race acceptance remain unverified; see
[validation](validation.md) and [troubleshooting](troubleshooting.md).

## Uninstall

Use the same profile selection used during installation:

```sh
bin/harness-herdr-hooks uninstall codex
```

Or, for the explicit profile example:

```sh
bin/harness-herdr-hooks uninstall codex --config-dir /path/to/codex-profile
```

Uninstall removes only manifest-matched handlers and its ownership manifest.
It does not change other Codex settings, terminate agents, or close panes.
