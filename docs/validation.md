# Validation and support status

**Delivery status: DRAFT / experimental; Definition of Done is not met.** This
table separates isolated source/operator and native-API evidence from unmet
native acceptance. Passing the former does not establish full support.

| Area | Evidence obtained | Qualification limit |
| --- | --- | --- |
| Source/static | Independent final QA passed all 131 tests on Python 3.11.14 and 3.12.3; compilation, diff, and CLI help checks passed. Coverage includes generation-safe terminal proof, unknown-state retention and exact terminal proof with known `notLoaded`, manual-close suppression, helper revision/path/retirement/restart, and real close-chain watchdog regressions. | Static/controlled checks do not prove native attachment, cleanup, or launch routing. |
| Operator install | Isolated fake-native profiles passed native `features list`, shim `--version`, fresh install/reinstall/uninstall, inherited-adapter PATH, moved-source, and shim cases. Install/config transaction and ownership checks are included in the 131-test suite. | Isolated profiles are not user-profile reload or native trust evidence. |
| Herdr API and controlled lifecycle fixtures | The isolated Herdr 0.9.5 server returned protocol-22 snapshots and process metadata; a sole foreground Bash PID passed the shell-readiness check. Separate controlled fixtures covered parent/title/fallback handling, sanitization, revocation, startup baselines, pending creation, and pane retention/cleanup. | The lifecycle fixtures used controlled Herdr metadata. They do not establish native child placement, concurrency, manual-close, profile/server races, or platform acceptance. |
| OpenCode native API | Isolated OpenCode 1.19.5 loopback API check created a synthetic parent/child metadata relation without prompts. Provider ancestor normalization and idle-skip behavior passed against a controlled Herdr stub. | No authorized real native child, added-turn comparison, complete profile/backend matrix, or full concurrency evidence. Fixture API evidence is not native child-attachment acceptance. |
| Codex native API | Parent verified isolated native `--version`/features and relink/uninstall, then active profile's genuine Codex executable (`0.170.0`) and features. Live Herdr bootstrap verified exact root, pane, backend `0.170.0`, and Herdr `0.9.5p22`. A bare no-prompt `codex` launch was acknowledged once in pane `w9:pY` in parent tab `w9:t1`, without focus; its launch payload was removed. | This proves only the observed launch acknowledgement and placement. It does not prove same-thread attachment, no-added-turn behavior, subagent completion/cancellation, client exit, or restart/isolation. The launch pane remained at its confirmation UI; no confirmation was answered. |
| Native pane observation | Adapter metadata records the selected profile's genuine Codex executable. The legacy exact-owned observer was retired and ended before the active profile was relinked. The active source now points to this checkout; the older clean detached checkout was preserved. | Source registration does not prove the running runtime loaded this revision: the observed legacy runtime had ended and had no current-revision helper. User-owned profile reload and any native trust prompt remain prerequisites. Unknown, unowned, multiple foreground, and null-session panes were retained; known-unloaded cleanup requires successful native status plus exact terminal-turn evidence. No live evidence establishes automatic closure for these cases. |
| Credentials/accounts | The OpenCode fixture had no model configured. The isolated Codex account query, without token refresh, returned no account and required OpenAI authentication. | No real credentials were copied or used. User-authorized native child creation/attachment and provider acceptance remain outstanding. |

The operator results above came from isolated private profiles. This
documentation-only synchronization did not touch the active Codex profile or
re-run installer effects; links and obsolete source-branch directions were
checked in the documentation tree.

The active owned source reference now points to this checkout:
`/tmp/agent-worktrees/harness-herdr-hooks/codex-session-cleanup`. The prior clean
detached checkout was preserved. This source registration is distinct from
runtime load evidence; the observed legacy runtime ended and did not expose a
helper for this revision.

## Required acceptance still unmet

- Load/reload the changed selected Codex profile in a user-owned parent session
  and follow native trust prompts for changed handlers. Do not bypass trust or
  force a restart.
- Demonstrate a real Codex subagent attaching once to its existing backend,
  without an added model turn, then closing its integration-owned pane only
  after metadata-confirmed terminal completion. Exercise continuation/re-entry,
  cancellation/failure, restart, duplicate/delayed events, reused turns, manual
  closure, and attachment/completion races. The bare CLI acknowledgement above
  does not establish these behaviors or client exit to shell.
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

Independent integrated code and contract reviews completed in two waves.
Supported corrections covered version guarding, stale turn generations,
observer health and cleanup outcomes, Herdr process metadata without argv,
Python 3.13, expiry and state roots, config absence/symlink identity, final-close
race handling, suppression after manual closure, and helper revision/path/
retirement/restart behavior. QA also found and repaired an initial native-adapter
installation defect. Review also corrected
the interpretation of `stop_hook_active`: [version-matched Codex hook source](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/core/src/hook_runtime.rs)
shows it indicates re-entry after a same-turn continuation, so it is not
evidence that the current stop request is terminal.


## HHH-002 cleanup-lock correction evidence

The reviewed cleanup path previously held `StateStore.locked` while calling
`NativeRuntime.close_owned_pane`; the real runtime re-entered store generation
lookup and flock, causing a permanent deadlock. Cleanup now snapshots state under
the lock, performs native checks and pane closure after releasing it, then uses a
guarded persistence step. A real `NativeRuntime` plus real `StateStore` watchdog
regression and a state-advanced-during-close watchdog regression each failed on
the baseline within 4.007 and 4.010 seconds, respectively, and pass with the
correction. Independent review findings concerning the prior-generation closed
cleanup guard and an unbounded second watchdog test were corrected; resumed
generation completion and repeated-poll coverage were added. These source tests
verify the bounded regression cases, not native attachment or live cleanup.

The source correction does not establish that it caused the earlier recorded
attachment attempts to fail. The wrapper outcome and pane error were unavailable,
and native attachment/cleanup/routing acceptance remains unverified. The PR
metadata is DRAFT; the internal validation status above remains DRAFT with
Definition of Done unmet.
