# Validation and support status

**Delivery status: DRAFT / experimental; Definition of Done is not met.** This
table separates isolated source/operator and native-API evidence from unmet
native acceptance. Passing the former does not establish full support.

| Area | Evidence obtained | Qualification limit |
| --- | --- | --- |
| Source/static (HHH-002 checkpoint) | All 104 standard-library tests passed on Python 3.11 and 3.12; independent QA also passed all 104 on Python 3.12.3. Python compilation and diff checks passed. Controlled coverage includes version guard, stale generations, observer health/cleanup outcomes, Herdr schema without argv, Python 3.13, expiry/state roots, config absence/symlink identity, Codex lifecycle/config/launch behavior, and cleanup-lock watchdog regressions. | Historical checkpoint evidence; HHH-004 final integrated source evidence is recorded below. Static/controlled checks do not prove native attachment, cleanup, or launch routing. |
| Operator install | Isolated native `features list`, shim `--version`, install/reinstall/uninstall passed. Install/config transaction and ownership checks are included in the 104-test suite. | Isolated profiles are not user-profile reload or native trust evidence. |
| Herdr API and controlled lifecycle fixtures | The isolated Herdr 0.9.5 server returned protocol-22 snapshots and process metadata; a sole foreground Bash PID passed the shell-readiness check. Separate controlled fixtures covered parent/title/fallback handling, sanitization, revocation, startup baselines, pending creation, and pane retention/cleanup. | The lifecycle fixtures used controlled Herdr metadata. They do not establish native child placement, concurrency, manual-close, profile/server races, or platform acceptance. |
| OpenCode native API | Isolated OpenCode 1.19.5 loopback API check created a synthetic parent/child metadata relation without prompts. Provider ancestor normalization and idle-skip behavior passed against a controlled Herdr stub. | No authorized real native child, added-turn comparison, complete profile/backend matrix, or full concurrency evidence. Fixture API evidence is not native child-attachment acceptance. |
| Codex native API | Read-only Codex CLI/app-server 0.170.0 and Herdr 0.9.5/protocol 22 checks loaded the existing parent, selected profile, and metadata API without a prompt or model turn. Isolated native features query and adapter shim checks passed. The user reports all hooks active and trusted; current profile runtime observation reports `native_hook_loading`. | These checks do not establish native child attachment or ordinary-launch behavior. The current tool-request thread (`01a1f354`) differs from the actual Herdr pane thread (`01a1f3f9`); the read-only router check returned `Codex hook root does not match pane thread`. |
| Native pane observation | Three created bindings recorded failed attachment attempts with no wrapper outcome. Their panes were closed, so the attachment error is unavailable. The current read-only router check reported a thread/root mismatch. | Do not infer that hooks are unloaded or untrusted. Native attachment, cleanup, and routing acceptance remain unverified. The active helper/backend was not restarted; no trust bypass or pane mutation was performed. |
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
metadata is user-marked ready for review; the internal validation status above
remains DRAFT with Definition of Done unmet.

## HHH-004 standalone creation-event evidence

The source changes and independent review/QA results below use the approved
HHH-002 pinned baseline `274b54c`; that baseline remains the source qualification
target. A newer predecessor branch head is not merged into this delivery and is
not covered by these results. Full implementation acceptance remains blocked.

| Area | Evidence obtained | Qualification limit |
| --- | --- | --- |
| Source/static | Final independent QA passed all 156 tests. `sh -n bin/harness-herdr-hooks`, `node --check integrations/opencode/plugin.js`, `python3 -m json.tool integrations/codex/hooks.json`, `python3 -m compileall -q src tests`, and `git diff --check` passed. A separate parent-side compileall run used `PYTHONPYCACHEPREFIX=/tmp/hhh004-recovery/final-pycache`. | These checks do not prove live app event capture or automatic native attachment. |
| Record observer | Independent QA1 temporary-thread cursor replacement probe passed: a new append after the serialized boundary was captured, with no historical backfill. Unit cases cover typed recognition, partial writes, malformed/oversized input, privacy, restart, replacement/truncation, deduplication, retry and observer races. | Fixture and temporary-file evidence is not the actual running Herdr parent rollout. |
| Installation/configuration | Isolated public install/status/reinstall/uninstall passed and preserved unrelated values/hooks. Fresh profiles without a `shell_environment_policy.set` table retain an empty table after uninstall on both baseline and current source. | This is pre-existing installer behavior and does not establish active user-profile reload/trust. No byte-exact restoration claim is made for fresh config files. |
| Live A5 binding | At 2026-11-19 15:28 UTC, Herdr `w9:p1`, tab `w9:t1`, native parent `01a1f3f9-dc23-7f20-88a9-9b0719f7439a` differed from invoking Codex thread `01a1f43b-b82c-7d03-8747-79ff4a335b60`. The binding check failed closed. | A5 remains blocked pending a correctly bound actual parent. No live installer run, harmless task creation, or pane mutation was performed. This is a missing live identity binding, not missing PLAN permission. |

The checked-out retained installation source is
`/tmp/agent-worktrees/harness-herdr-hooks/codex-session-cleanup/bin/harness-herdr-hooks`
for `/home/alexbanica/.codex`; it was left untouched. Do not remove or relink it
without a later verified installation from a trusted checkout. The delivery
branch is `feat/codex-standalone-task-discovery`, based on the pinned approved
baseline, with a DRAFT PR targeting `feat/codex-herdr-session-lifecycle` as the
planned delivery. These validation results were recorded before publication;
the parent delivery report supplies the verified commit and PR evidence.

The project remains DRAFT and Definition of Done is unmet because A5 live
qualification remains outstanding. Existing predecessor OpenCode/macOS and
other native qualification gaps remain independent. No result here establishes
full native compatibility.
