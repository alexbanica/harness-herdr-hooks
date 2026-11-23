# Validation and support status

**Current delivery status: DRAFT / experimental; current Definition of Done is not met.** The current scope retains standalone Codex session panes and the separate ordinary fresh interactive command route. Native subagent discovery/attachment, OpenCode event handling, and automated tab creation/naming/retirement were removed. Results below the historical-record heading refer to predecessor behavior and are not evidence for this current scope.

## Standalone session panes only — current revision

This record applies to approved SPEC `SPEC-standalone-session-panes-only.md`
(SHA-256 `cd5f54056039a7736e5ececa290c8261f8b14cd80e37fedb45740ed0b75b4687`)
and PLAN `PLAN-standalone-session-panes-only.md`
(SHA-256 `01288d3cf8bad95701792933b2cb28a7c12156577a713d9256704da7596e1fe1`),
including the approved same-tab/no-PID amendment.

| Area | Evidence obtained | Qualification limit |
| --- | --- | --- |
| Focused source QA | Independent final QA reported 69 focused tests and 150 full-suite tests passed; `git diff --check` passed. | These checks do not establish live event capture or native attachment. The commands ran from the isolated checkout. |
| Live attempt | The parent installed the current source into a clean disposable profile. Herdr 0.9.5 / protocol 22 named server launched native Codex in pane `w2:p1`, tab `w2:t1`. Startup showed sign-in; the Herdr snapshot reported `agent_session` null. The named server was stopped and the disposable hooks were uninstalled. | No native task creation was attempted because the parent session was not established. Same-tab attachment, exact session acknowledgement, no-added-turn behavior, and post-exit usable shell remain unverified. |
| Scope and effects | The live attempt used a disposable profile and named Herdr server. | No production profile, production panes, or Git state were changed by the live attempt. No current live result establishes that current hooks were loaded by a user-owned authenticated parent. |
| Migration and legacy events | The independent source suite covered the integrated source per its report. | Runtime behavior of an already-loaded predecessor process is not changed by registration migration; user-controlled reload remains necessary. No live OpenCode or legacy callback exercise was performed. |

Final QA used these commands in the isolated checkout:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /usr/bin/python3 -m unittest -q test_codex_install test_standalone_task_discovery test_standalone_shell test_standalone_task_state test_interactive_launch test_runtime_status
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -q
git diff --check
```

Standalone placement now resolves the originating session through current Herdr
bindings and requires one existing destination tab; no foreground PID/process
check is a prerequisite for standalone discovery or attachment. The separate
fresh interactive command route retains its own existing verification. Split
and managed-start effects use durable one-shot intents; uncertain outcomes are
retained and are not blindly replayed. Native subagent/tab results below are
historical only.

The remaining live acceptance is to use a correctly bound authenticated Herdr
parent, trigger one supported standalone creation, verify the exact returned
session in one unfocused pane in the existing parent tab, establish that attach
added no turn, and verify that client exit leaves a usable shell. Current
runtime loading/trust and any platform-specific qualification not evidenced by
the source report remain separate limitations. Until then, the project remains
DRAFT.

## Historical validation records

The following sections preserve earlier evidence for predecessor scopes. Their
claims about native subagents, OpenCode event handling, process checks for
child attachment, and managed subagent tabs are archival. They do not describe
or qualify the current implementation.

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

## Codex adapter compatibility

The approved Codex adapter compatibility change was checked with 23 focused
tests and 275 full-suite tests. Both suites and `git diff --check` passed.
The fixtures exercised Codex 0.170.0, 0.171.0, and future or unknown release metadata.

The parent performed a read-only host-access probe using the isolated real
adapter with the existing installed manifest and socket. It verified app-server
0.171.0 initialization, `thread/loaded/list`, and a metadata-only
`thread/read` whose returned thread ID matched the selected loaded ID. The default sandbox denied access to the endpoint, so the probe used host
access. It reported the daemon release and ID match without emitting thread
contents. The earlier Codex 0.170.0 runtime observations are recorded above.

Live pane attachment remains unverified. The earlier shared-daemon investigation
found missing pane markers and missing native pane session references.

## HHH-005 named subagent tabs

This evidence applies to the integrated HHH-005 implementation under approved
SPEC SHA-256
`379efe75181c91d8a8349c31986223fb55519a4c54464ebc45214bdb3b14a8b4` and
effective PLAN SHA-256
`13d541d4c1988aba8e8588812f2c65ad7406aad7ac2ad3e96df2188944409889`. PLAN
amendments A1/A2 refine the canonical workspace coordination anchor and its
safe path admission; the original approved artifact text and status remain
preserved.

| Area | Evidence obtained | Qualification limit |
| --- | --- | --- |
| Deterministic source QA | Final QA passed 271 tests on Python 3.12.3 and 3.11.14. | This does not prove native harness attachment or live lifecycle behavior. |
| Timing-sensitive overflow case | An initial Python 3.12 run expected 128 sessions and observed 118. The focused check and full suite passed on rerun; no repeat cycle reproduced it. | The discrepancy remains a low, timing-sensitive concern, not an established regression. |
| Static checks | `compileall`, shell syntax, Node syntax, JSON parsing and structural checks passed on the final source. | Static checks do not establish runtime loading or native behavior. |
| Isolated operator checks | Isolated public install/status/uninstall checks passed for both harnesses. An additional preservation sentinel passed install/status/uninstall for both: unrelated config bytes/prefix and `0640` modes were preserved; Codex uninstall restored unrelated original bytes while retaining its existing empty `shell_environment_policy.set` table. No real profile was written. | These checks do not establish active user-profile registration, native trust, or native attachment. |
| Herdr protocol observation | On Nov 19, targeted Herdr 0.9.5 / protocol 22 operations `tab.create`, `pane.split`, `tab.rename` and last-pane closure were observed without focus change. | This is protocol-operation evidence only. It is not Codex or OpenCode native harness qualification. |
| Codex runtime | Current user-owned profile trust/reload remains pending. | No native Codex subagent attachment, nested grouping, no-added-turn, title synchronization, or complete lifecycle qualification is claimed. The parent may relink the profile after this documentation stage; this record does not assert it is already installed. |
| OpenCode runtime | Native qualification was unavailable, as confirmed by the user. | Native plugin loading, child attachment, nested grouping, no-added-turn, title synchronization, and lifecycle qualification remain unverified. |

Independent code and contract reviews completed, and eight findings were
corrected before final QA. These assurance results do not substitute for native
acceptance. HHH-005 native acceptance remains DRAFT pending Codex and
OpenCode qualification; existing predecessor gaps also remain. This status does
not claim that source implementation or isolated checks failed.
