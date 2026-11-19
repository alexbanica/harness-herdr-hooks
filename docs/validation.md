# Validation and support status

**Delivery status: DRAFT / experimental; Definition of Done is not met.** This
table separates isolated source/operator and native-API evidence from unmet
native acceptance. Passing the former does not establish full support.

| Area | Evidence obtained | Qualification limit |
| --- | --- | --- |
| Source/static | All 101 tests passed independently and on Python 3.11 and 3.12; Python compile, `sh -n`, Codex JSON, native Node plugin syntax, and diff checks passed. Controlled coverage includes version guard, stale generations, observer health/cleanup outcomes, Herdr schema without argv, Python 3.13, expiry/state roots, config absence/symlink identity, and Codex lifecycle/config/launch behavior. | Static/controlled checks do not prove native attachment, cleanup, or launch routing. |
| Operator install | Isolated native `features list`, shim `--version`, install/reinstall/uninstall passed. Install/config transaction and ownership checks are included in the 101-test suite. | Isolated profiles are not user-profile reload or native trust evidence. |
| Herdr API and controlled lifecycle fixtures | The isolated Herdr 0.9.5 server returned protocol-22 snapshots and process metadata; a sole foreground Bash PID passed the shell-readiness check. Separate controlled fixtures covered parent/title/fallback handling, sanitization, revocation, startup baselines, pending creation, and pane retention/cleanup. | The lifecycle fixtures used controlled Herdr metadata. They do not establish native child placement, concurrency, manual-close, profile/server races, or platform acceptance. |
| OpenCode native API | Isolated OpenCode 1.19.5 loopback API check created a synthetic parent/child metadata relation without prompts. Provider ancestor normalization and idle-skip behavior passed against a controlled Herdr stub. | No authorized real native child, added-turn comparison, complete profile/backend matrix, or full concurrency evidence. Fixture API evidence is not native child-attachment acceptance. |
| Codex native API | Read-only Codex CLI/app-server 0.170.0 and Herdr 0.9.5/protocol 22 checks loaded the existing parent, selected profile, and metadata API without a prompt or model turn. Isolated native features query and adapter shim checks passed. | These checks do not establish the changed active profile loaded the new adapter/hooks, trust, or native child/ordinary-launch behavior. |
| Native pane observation | Parent PATH did not begin with the new adapter. After isolating QA children, no new Herdr pane appeared; pre-existing tab panes were unchanged. | Parent session has not loaded the selected-profile change. No display, cleanup, or shell launch acceptance is claimed. |
| Credentials/accounts | The OpenCode fixture had no model configured. The isolated Codex account query, without token refresh, returned no account and required OpenAI authentication. | No real credentials were copied or used. User-authorized native child creation/attachment and provider acceptance remain outstanding. |

The operator results above came from isolated private profiles. This
documentation-only synchronization did not touch the active Codex profile or
re-run installer effects; links and obsolete source-branch directions were
checked in the documentation tree.

The current active source remains the retained checkout at
`/tmp/agent-worktrees/harness-herdr-hooks/codex-session-lifecycle`. Keep it in
place until a later install from a trusted stable checkout updates the owned
source references; no source removal or relink is part of this validation.

## Required acceptance still unmet

- Reopen/reload a user-owned parent session after loading the changed selected
  Codex profile; follow native trust prompts for changed handlers. Do not
  bypass trust or restart the shared daemon.
- Demonstrate a real Codex subagent attaching once to its existing backend,
  without an added model turn, and closing its integration-owned pane only
  after metadata-confirmed terminal completion. Exercise continuation/re-entry,
  idle, cancellation/failure, restart, duplicate/delayed events, reused turns,
  manual closure, and attachment/completion races. Verify ordinary interactive
  `codex` launch routing once, same-tab/unfocused placement, retained usable
  shell, and native semantics for excluded command classes.
- The existing OpenCode native attachment/trust and no-added-turn acceptance
  remains outstanding independently of HHH-002.
- Complete real profile/backend isolation, cross-harness and same-harness
  collision cases, full concurrency/restart/manual-close and attachment race
  coverage.
- Run equivalent runtime evidence on macOS. No macOS host was available.

No user instruction excluded these criteria. They remain required before
acceptance. Source implementation and isolated checks do not change this DRAFT
status. Native Codex qualification needs a user-owned parent that loads the
changed profile and renews hook trust if prompted; no trust bypass, session
restart, or daemon restart is authorized. OpenCode and predecessor macOS gaps
remain distinct.

Independent integrated code and contract reviews completed. Supported
corrections covered version guarding, stale turn generations, observer health
and cleanup outcomes, Herdr process metadata without argv, Python 3.13, expiry
and state roots, and config absence/symlink identity. Review also corrected
the interpretation of `stop_hook_active`: [version-matched Codex hook source](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/core/src/hook_runtime.rs)
shows it indicates re-entry after a same-turn continuation, so it is not
evidence that the current stop request is terminal.
