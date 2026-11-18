# OpenCode installation

The selected OpenCode config directory is `OPENCODE_CONFIG_DIR`, otherwise
`$XDG_CONFIG_HOME/opencode`, otherwise `~/.config/opencode`. This selects plugin
registration only; it does not select a private OpenCode database, data/state
root, server, account, or provider. The installer links
`plugins/harness-herdr-hooks.js` and records its ownership in
`.harness-herdr-hooks.json` in that config directory. It requires Python 3.11+,
POSIX `sh`, and a checkout of this repository. It does not require Codex.
The installer also uses `.harness-herdr-hooks.lock` in that config root for
serialization; the lock may remain after uninstall.

## Install and inspect

The public source branch is `feat/initial-hooks`; default `main` contains the
planning artifacts until its source PR is merged:

```sh
git clone --branch feat/initial-hooks https://github.com/alexbanica/harness-herdr-hooks.git
cd harness-herdr-hooks
bin/harness-herdr-hooks install opencode
bin/harness-herdr-hooks status opencode
```

To select a different configuration root, pass the same path on each command:

```sh
bin/harness-herdr-hooks install opencode --config-dir /path/to/opencode-config
bin/harness-herdr-hooks status opencode --config-dir /path/to/opencode-config
```

The installer preserves an unmanaged destination and refuses a conflict. To
update or recover a moved checkout, run `install` from its new location against
the same selected config root and then inspect `status`. The link is updated
only when the ownership record still matches. Do not remove a conflicting path
by guesswork.

## Runtime prerequisites and limits

The target is OpenCode 1.19.5, Herdr 0.9.5 / protocol 22, Python 3.11+, POSIX
`sh`, and the selected `opencode` CLI in `PATH`. Runtime observation uses the
OpenCode loopback unauthenticated local API for the actual server process bound
to the parent pane. `OPENCODE_CONFIG`, `OPENCODE_CONFIG_CONTENT`, and
`OPENCODE_DB` disable this integration because those override paths are not
qualified. The effective config directory is not proof that data, state, server,
account, or provider are private; see [isolation](isolation.md).

Plugin registration and isolated API/operator behavior have passed the checks
listed in [validation](validation.md). Native plugin enablement/trust and
user-owned reload/restart behavior have not been fully qualified. If OpenCode
asks for normal plugin trust, use its native procedure; no trust-bypass option
is documented. Do not restart a server automatically to recover. A successful
link/status does not establish native plugin loading, authorized child-session
attachment without an added turn, or complete profile/backend/race support.
Those remain DRAFT acceptance gaps.

## Uninstall

Use the same configuration root used for installation:

```sh
bin/harness-herdr-hooks uninstall opencode
```

Or, for the explicit config example:

```sh
bin/harness-herdr-hooks uninstall opencode --config-dir /path/to/opencode-config
```

Uninstall removes only the manifest-matched symlink and ownership manifest. It
does not remove session state, close panes, or stop agents. Retained state is
used to support recovery and is not evidence that an integration remains
registered.
