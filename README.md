# Harness Herdr Hooks

Harness Herdr Hooks observes new Codex and OpenCode sessions created from a
verified parent session in a Herdr pane. For qualified Codex app/TUI local
rollouts, it also recognizes a successful `codex_tui.create_thread` result
from that exact parent and verifies the returned task independently. When a
running task can be attached through its existing native backend, it opens
that same session in an unfocused pane in the parent's Herdr tab. It never
sends a prompt or starts replacement work for that attached task. A supported
ordinary interactive Codex command is routed with its requested prompt once and
leaves a usable shell after the client exits. Session titles flow one way to Herdr pane names. Finished or
unverified children are skipped; activity outside Herdr is a silent no-op.

**Status: DRAFT / experimental.** Source and isolated operator/API checks pass
for the behaviors listed in [validation](docs/validation.md), but complete
native acceptance is blocked. Standalone task discovery depends on a
version-qualified local rollout record format; live automatic capture and
attachment have not been demonstrated in a correctly bound user-owned parent.
Other native Codex hook trust/reload, profile/backend and race coverage, and
macOS runtime evidence remain outstanding. This project does not claim complete
support or Definition of Done.

## Quick start

Clone the repository, then install and check only the harness you use:

```sh
git clone https://github.com/alexbanica/harness-herdr-hooks.git
cd harness-herdr-hooks
bin/harness-herdr-hooks install codex
bin/harness-herdr-hooks status codex
```

For OpenCode, substitute `opencode` for `codex` in both commands. Each installer
works independently; the other harness's native CLI or configuration is not
needed. See [Codex setup](docs/install-codex.md) or
[OpenCode setup](docs/install-opencode.md) for profile selection, native
qualification limits, and uninstall. Installing a registration does not by
itself establish native runtime support.

## What is required for a pane

Use the selected harness in a Herdr pane with Herdr 0.9.5 / protocol 22, Python
3.11+, POSIX `sh`, and the selected native CLI in `PATH`. Codex 0.170.0
qualifies verified selection of its normal shared default daemon as well as an
explicit Unix endpoint; `--no-daemon` and uncertain launch modes are refused.
OpenCode requires its bound loopback, unauthenticated local API. Unsupported,
ambiguous, completed, or out-of-Herdr cases fail closed or skip as described in
[the contracts](docs/contracts.md).

Codex installation adds an owned adapter directory to the selected profile's
literal `shell_environment_policy.set.PATH`. Reload/restart that Codex profile
through its normal user controls before expecting future shell commands to use
it; trust changed hooks if Codex asks. The installer does not restart Codex,
bypass trust, or change daemon settings. See [Codex setup](docs/install-codex.md).

## Example

From a qualified Codex or OpenCode session already running in a Herdr pane, use
the native child feature. Codex standalone discovery applies specifically when
the app's `codex_tui.create_thread` tool returns successfully and its typed
completion is recorded in the verified parent rollout. A new, independently
verified, running and attachable task can appear in another pane in that same
Herdr tab, without a repeated prompt. This live capture path remains unqualified;
see [validation](docs/validation.md) and [contracts](docs/contracts.md).

## Local state and ownership

The integration links Codex hooks or the OpenCode plugin only in the selected
user configuration root. It preserves unmanaged entries and refuses conflicts.
Runtime metadata is stored under
`$XDG_STATE_HOME/harness-herdr-hooks` (default `~/.local/state/harness-herdr-hooks`)
with private directory/file permissions. State records are retained after
uninstall for recovery; revoking the registration stops this integration's own
helper and leaves panes and agents alone. See [isolation](docs/isolation.md)
and [troubleshooting](docs/troubleshooting.md).
