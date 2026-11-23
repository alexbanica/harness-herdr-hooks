# OpenCode migration

OpenCode integration is retired. New installation is unsupported because the
retired plugin only automated native child-session panes. This repository no
longer observes OpenCode sessions or subagents and does not create or manage
Herdr tabs for OpenCode.

## Remove a legacy managed plugin

Use a trusted current checkout and the same configuration directory used by
the old installation. The selected root is `OPENCODE_CONFIG_DIR`, otherwise
`$XDG_CONFIG_HOME/opencode`, otherwise `~/.config/opencode`.

```sh
bin/harness-herdr-hooks status opencode
bin/harness-herdr-hooks uninstall opencode
```

For an explicit profile path:

```sh
bin/harness-herdr-hooks status opencode --config-dir /path/to/opencode-config
bin/harness-herdr-hooks uninstall opencode --config-dir /path/to/opencode-config
```

Status and uninstall remain available to identify and remove an unchanged,
manifest-matched legacy plugin symlink. The ownership check preserves an
unmanaged, independently changed, or conflicting destination. Do not remove a
path manually based only on its name. The old installer lock may remain after
uninstall.

Migration revokes only that registration and retains integration state,
sessions, panes, tabs, and existing agents. It does not stop a running
OpenCode process that already loaded the plugin. Use OpenCode's normal
user-controlled reload/restart flow if needed. Do not expect the retired plugin
to attach sessions after migration. See [validation](validation.md) for current
source and migration evidence; earlier OpenCode runtime and tab observations
are historical only.
