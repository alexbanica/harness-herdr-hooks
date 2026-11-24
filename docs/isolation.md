# Isolation boundaries

The retained standalone flow requires the selected Codex profile/backend, the
exact originating parent session, and its current Herdr session binding. The
creation record nominates a candidate; it does not establish identity. The
backend must return the exact child session, and the current authenticated
Herdr server must map the parent to one existing destination tab. A title,
working directory, inherited environment marker, config path, or guessed
process relation is not authority. Standalone placement does not depend on a
foreground PID or process tree.

## Codex and Herdr boundaries

The optional client-bound route adds a per-helper lease under the private
`client-bindings` state namespace. Admission requires the exact pinned local
Codex TUI, a managed local interactive launch, a private authenticated local
Herdr socket, and a terminal identity matching one protocol-22 pane tty.
Codex session checks separately use the selected profile's pinned local Codex
endpoint. Pane ID, tty, workspace or tab values inherited from a
shared app-server or shell do not prove the foreground client's display.
Missing tty data or more than one matching display fails closed.

An active lease binds the displayed conversation to the verified Herdr
server, workspace, tab and pane. View changes require acknowledged revocation;
the helper serializes lease and pane effects under generation locks. A creation
receipt is limited to the originating TUI's admitted user turn and exact typed
child result. After a resume, the new conversation is eligible only after its
new active lease is acknowledged. Receipts are single-use and bounded.
Ambiguous clients, stale
endpoints, view changes, native delegation, direct/native launch, or shim
bypass do not authorize placement. The legacy Herdr Codex session reporter
conflicts with this source of session references and must be absent before
managed mode can be enabled. These checks do not claim support for remote or
unpatched clients.

Codex uses bounded local rollout metadata and the app-server interfaces needed
to verify the selected profile and exact session. An explicit endpoint is
accepted only when it is already associated with a verified standalone
session on that profile and passes the same ownership, incarnation, and
thread checks. Arbitrary sockets are not searched. `CODEX_HOME` (or its
existing default) selects the profile; it does not prove that the backend is
private.

The parent-to-Herder mapping comes from current session bindings on the
authenticated server, not pane/tab/workspace environment markers. Matching
panes are deduplicated by workspace and tab. A unique tab is required; no
match or mappings across multiple tabs produce no pane effect. The lexical
first pane ID in a unique destination is the split anchor. The destination is
rechecked before the split.

The standalone effect environment is bounded to the verified Codex profile,
display marker, and existing absolute integration state root hint. Credentials,
provider configuration, arbitrary environment maps, conversation text,
prompts, raw results, and transcript content are not copied into integration
state or the display environment. The attachment resumes the exact session
through Herdr's managed Codex route and submits no prompt or new turn.

The separate fresh interactive command route retains its own process,
backend, and launch checks. Its process verification does not apply to
standalone session discovery or attachment. Outside a verified Herdr parent,
the integration performs no pane automation.

## Durable effects and retained state

Runtime metadata is stored under `$XDG_STATE_HOME/harness-herdr-hooks` or
`~/.local/state/harness-herdr-hooks`, unless the existing absolute
`HARNESS_HERDR_STATE_ROOT` is configured. Private files contain bounded IDs,
context and destination bindings, rollout cursor/file identity, hashes, and
effect intents/outcomes needed for deduplication and recovery. They exclude
prompt and transcript contents.

Before splitting, the integration persists a one-shot intent tied to the exact
creation association and destination. Only an exact Herdr acknowledgement
allows a pane claim. Before managed start, it persists an intent tied to that
pane and exact child. If an acknowledgement is missing, a crash occurs, or
the returned session cannot be confirmed, the outcome stays bounded and
uncertain. Replay does not split again, repeat managed start, infer ownership
from an unrelated pane, or close the existing pane. Manual closure is
respected and suppresses reopening that display.

Existing tabs and panes are never moved, renamed as tabs, or retired by this
integration. No code path for this feature creates, renames, or closes Herdr
tabs; legacy native subagent events and bindings produce no pane/tab effects.
Uninstall revokes owned registrations but retains state, sessions, panes,
tabs, and agents for operator recovery.

## Qualification boundary

Source tests cover identity checks and bounded effect sequencing, but they do
not prove a live standalone creation, same-tab attachment, no-added-turn
behavior, shell usability after client exit, or current-revision runtime
loading. The latest parent-observed live attempt and its exact limits are in
[validation](validation.md). Earlier native subagent and tab observations are
historical evidence and do not qualify this contract.
