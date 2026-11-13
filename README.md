# Harness Herdr Hooks

Harness Herdr Hooks observes new Codex and OpenCode sessions created from a
verified parent session in a Herdr pane. When a running child can be attached
through its existing native backend, it opens that same session in an unfocused
pane in the parent's Herdr tab. It never sends a prompt or starts replacement
work. Session titles flow one way to Herdr pane names. Finished or unverified
children are skipped; activity outside Herdr is a silent no-op.

**Status: DRAFT / experimental.** Source and isolated operator/API checks pass
for the behaviors listed in [validation](docs/validation.md), but complete
native acceptance is blocked. Native hook/plugin enablement and trust, authorized
real native child attachment without an added turn, complete profile/backend and
race coverage, and macOS runtime evidence remain unqualified. This project does
not claim complete support or Definition of Done.

## Quick start

The public repository's initial source is on `feat/initial-hooks`; `main` has
the planning artifacts until that branch is merged. Clone the source branch,
then install and check only the harness you use:

```sh
git clone --branch feat/initial-hooks https://github.com/alexbanica/harness-herdr-hooks.git
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
3.11+, POSIX `sh`, and the selected native CLI in `PATH`. The observed parent,
Herdr pane, harness profile, and backend must all be verified. In particular,
Codex requires an explicitly selected foreground `--remote unix://PATH` (or
`--remote=URI`) endpoint; implicit daemon or embedded fallback is refused.
OpenCode requires its bound loopback, unauthenticated local API. Unsupported,
ambiguous, completed, or out-of-Herdr cases fail closed or skip as described in
[the contracts](docs/contracts.md).

## Example

From a qualified Codex or OpenCode session already running in a Herdr pane, ask
the native agent to spawn a child using its normal task or subagent feature. A
new, verified, still-running and attachable child is shown in another pane in
that same Herdr tab; it does not receive a new prompt. Its pane label follows
the child title when available. Exact existing-session attach command forms are
documented as reference only; they have not been accepted as end-to-end native
child evidence. See [validation](docs/validation.md).

## Local state and ownership

The integration links Codex hooks or the OpenCode plugin only in the selected
user configuration root. It preserves unmanaged entries and refuses conflicts.
Runtime metadata is stored under
`$XDG_STATE_HOME/harness-herdr-hooks` (default `~/.local/state/harness-herdr-hooks`)
with private directory/file permissions. State records are retained after
uninstall for recovery; revoking the registration stops this integration's own
helper and leaves panes and agents alone. See [isolation](docs/isolation.md)
and [troubleshooting](docs/troubleshooting.md).
