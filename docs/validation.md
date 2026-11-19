# Validation and support status

**Delivery status: DRAFT / experimental; Definition of Done is not met.** This
table separates isolated source/operator and native-API evidence from unmet
native acceptance. Passing the former does not establish full support.

The first table and the following source/profile paragraphs record earlier
HHH-002 predecessor observations, including native API and pane evidence. They
do not establish HHH-004 A5 live qualification.

| Area | Evidence obtained | Qualification limit |
| --- | --- | --- |
| Source/static | Earlier HHH-002 final QA passed 131 tests on Python 3.11.14 and 3.12.3; see the HHH-004 combined-tree evidence below for the final integrated suite and checks. | Static/controlled checks do not prove native attachment, cleanup, or launch routing. |
| Operator install | Earlier HHH-002 isolated fake-native profiles passed native `features list`, shim `--version`, fresh install/reinstall/uninstall, inherited-adapter PATH, moved-source, and shim cases. See the HHH-004 combined-tree evidence below for the final isolated public-profile checks. | Isolated profiles are not user-profile reload or native trust evidence. |
| Herdr API and controlled lifecycle fixtures | The isolated Herdr 0.9.5 server returned protocol-22 snapshots and process metadata; a sole foreground Bash PID passed the shell-readiness check. Separate controlled fixtures covered parent/title/fallback handling, sanitization, revocation, startup baselines, pending creation, and pane retention/cleanup. | The lifecycle fixtures used controlled Herdr metadata. They do not establish native child placement, concurrency, manual-close, profile/server races, or platform acceptance. |
| OpenCode native API | Isolated OpenCode 1.19.5 loopback API check created a synthetic parent/child metadata relation without prompts. Provider ancestor normalization and idle-skip behavior passed against a controlled Herdr stub. | No authorized real native child, added-turn comparison, complete profile/backend matrix, or full concurrency evidence. Fixture API evidence is not native child-attachment acceptance. |
| Codex native API | Parent verified isolated native `--version`/features and relink/uninstall, then active profile's genuine Codex executable (`0.170.0`) and features. Live Herdr bootstrap verified exact root, pane, backend `0.170.0`, and Herdr `0.9.5p22`. A bare no-prompt `codex` launch was acknowledged once in pane `w9:pY` in parent tab `w9:t1`, without focus; its launch payload was removed. | This proves only the observed launch acknowledgement and placement. It does not prove same-thread attachment, no-added-turn behavior, subagent completion/cancellation, client exit, or restart/isolation. The launch pane remained at its confirmation UI; no confirmation was answered. |
| Native pane observation | Adapter metadata records the selected profile's genuine Codex executable. The legacy exact-owned observer was retired and ended before the active profile was relinked. The active source now points to this checkout; the older clean detached checkout was preserved. | Source registration does not prove the running runtime loaded this revision: the observed legacy runtime had ended and had no current-revision helper. User-owned profile reload and any native trust prompt remain prerequisites. Unknown, unowned, multiple foreground, and null-session panes were retained; known-unloaded cleanup requires successful native status plus exact terminal-turn evidence. No live evidence establishes automatic closure for these cases. |
| Credentials/accounts | The OpenCode fixture had no model configured. The isolated Codex account query, without token refresh, returned no account and required OpenAI authentication. | No real credentials were copied or used. User-authorized native child creation/attachment and provider acceptance remain outstanding. |

The operator results above came from isolated private profiles. This
documentation-only synchronization did not touch the active Codex profile or
re-run installer effects; links and obsolete source-branch directions were
checked in the documentation tree.

At the earlier HHH-002 observation, the active owned source reference pointed
to `/tmp/agent-worktrees/harness-herdr-hooks/codex-session-cleanup`; the prior
clean detached checkout was preserved. This source registration is distinct
from runtime load evidence; the observed legacy runtime ended and did not expose
a helper for that revision.

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

## HHH-004 checkpoint evidence before PLAN-A1 integration

The following records describe published checkpoint `93457ef` on the original
HHH-002 source pin `274b54c`. PLAN-A1 integrates the advanced predecessor
`4774fc5`; these checkpoint results do not establish the combined tree. At that
checkpoint, combined-tree evidence had not yet been recorded; final evidence
appears below.

| Area | Evidence obtained | Qualification limit |
| --- | --- | --- |
| Source/static | Final independent QA passed all 156 tests. `sh -n bin/harness-herdr-hooks`, `node --check integrations/opencode/plugin.js`, `python3 -m json.tool integrations/codex/hooks.json`, `python3 -m compileall -q src tests`, and `git diff --check` passed. A separate parent-side compileall run used `PYTHONPYCACHEPREFIX=/tmp/hhh004-recovery/final-pycache`. | These checks do not prove live app event capture or automatic native attachment. |
| Record observer | Independent QA1 temporary-thread cursor replacement probe passed: a new append after the serialized boundary was captured, with no historical backfill. Unit cases cover typed recognition, partial writes, malformed/oversized input, privacy, restart, replacement/truncation, deduplication, retry and observer races. | Fixture and temporary-file evidence is not the actual running Herdr parent rollout. |
| Installation/configuration | Isolated public install/status/reinstall/uninstall passed and preserved unrelated values/hooks. Fresh profiles without a `shell_environment_policy.set` table retain an empty table after uninstall on both baseline and current source. | This is pre-existing installer behavior and does not establish active user-profile reload/trust. No byte-exact restoration claim is made for fresh config files. |
| Live A5 binding | At 2026-11-19 15:28 UTC, Herdr `w9:p1`, tab `w9:t1`, native parent `01a1f3f9-dc23-7f20-88a9-9b0719f7439a` differed from invoking Codex thread `01a1f43b-b82c-7d03-8747-79ff4a335b60`. The binding check failed closed. | A5 remains blocked pending a correctly bound actual parent. No live installer run, harmless task creation, or pane mutation was performed. This is a missing live identity binding, not missing PLAN permission. |

## HHH-004 combined-tree evidence after PLAN-A1 integration

The following final QA and operator evidence applies to the integrated tree
combining published checkpoint `93457ef` with predecessor `4774fc5` under
effective PLAN SHA-256
`8c0594892ca542773798416155144a5395f69f5e83e931d2dd429b422c4076b6`, including
automatically approved HHH-004-PLAN-A1, and unchanged SPEC SHA-256
`a506853924126c74aca1d73b9b36d2c379db3bd0e52b46238bb5440dc2e53423`. It
supersedes checkpoint-only source and operator results above for the combined
tree; it does not establish live native acceptance.

| Area | Evidence obtained | Qualification limit |
| --- | --- | --- |
| Source/static | Independent final QA passed all 189 standard-library tests with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -q`. `PYTHONPYCACHEPREFIX`-isolated `python3 -m compileall -q src tests`, `sh -n bin/harness-herdr-hooks`, `node --check integrations/opencode/plugin.js`, `python3 -m json.tool integrations/codex/hooks.json`, and `git diff --check` all passed. Focused regression checks also passed. | These source and static checks do not prove native attachment, pane cleanup, or launch routing. The compile cache used a private temporary directory; no cache artifacts are evidence of runtime qualification. |
| Operator install | Independent QA's fresh minimal-profile fake-Codex install, status, reinstall, and uninstall checks all returned 0. In a separate parent probe, all four actions returned 0 while preserving a foreign event hook and unrelated `other.keep`/configuration values; that probe's fresh configuration retained an empty `shell_environment_policy.set` table after uninstall. | These isolated observations do not establish byte-exact fresh-file restoration, user-profile reload, or native trust evidence. The preservation result is from the separate parent probe, not the independent QA cycle. |
| A5 live binding | At 2026-11-19 16:06 UTC, invoking thread `01a1f43b-b82c-7d03-8747-79ff4a335b60` differed from native Herdr parent `01a1f3f9-dc23-7f20-88a9-9b0719f7439a` in `w9:p1`/`w9:t1`; preflight remained blocked. | A5 remains blocked pending a correctly bound actual parent. No live install, task, pane effect, or runtime qualification was performed. This is a missing live identity binding, not missing PLAN permission. |

The combined-tree QA and operator checks leave the project DRAFT. The A5 live
qualification and the independent OpenCode, macOS, and other native acceptance
gaps listed above remain outstanding.

For [HHH-004-PLAN-A1](../specs/PLAN-codex-standalone-creation-events.md), independent
readiness review reported no findings before automatic approval. The integrated
code-review wave (`HHH004-A40-code` plus its coverage completion) and contract
review covered the combined boundary. Its one supported P2 finding concerned
title synchronization after reusing a display without a wrapper outcome. The
correction accepts matching durable reused ownership without granting cleanup
rights; positive reuse/title/manual-close and negative unacknowledged-created
binding regressions passed. Final independent QA (`HHH004-A60-QA`) reported no
findings and passed the 189-test standard-library suite. This assurance does not
approve unrelated predecessor work or satisfy A5.

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
