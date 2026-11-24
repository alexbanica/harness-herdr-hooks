# Deliver the explicit Codex pane launcher

Status: Approved

The user approved the proposed revision on 2026-11-24 with “approve - but also perform cleanups”. Reviewed SHA-256 `11798031a055d1caa5dee010a999ab3c8d5a6cb2dfea5bd3017390ff8d7688b6`. Units L2 and L4 require actual removal of the superseded repository code, tests and documentation during implementation. The Git delivery section covers cleanup of the transferred planning files.

The [approved SPEC](SPEC-codex-pane-launcher.md) has SHA-256 `c7e360566c0066dc469e546fc5f487215a9c7cda7333a2f0d4d0988dad97cd94`. The deliverable is a stock-Codex launcher, a discoverable Codex instruction, and the tests and operating instructions for them. This PLAN replaces the automatic behavior of the [hook pair](PLAN-harness-herdr-hooks.md), the [standalone pane pair](PLAN-standalone-session-panes-only.md), and the [client-binding pair in PR #7](https://github.com/alexbanica/harness-herdr-hooks/blob/babf077/specs/PLAN-codex-client-pane-binding.md). Their specifications are linked in the approved SPEC. Same-tab, unfocused placement carries forward. All predecessor planning records are outside edit ownership.

## Invocation and handoff

Ship a portable Codex skill directory at `skills/codex-pane/` containing only `SKILL.md` and the executable Python 3 standard-library script `scripts/codex-pane`. A single directory can be linked into the user's Codex skills directory. The skill resolves the executable relative to its own directory from any project. Its description covers requests to open a Herdr pane with a new Codex session or to create another Codex session in Herdr. Ordinary conversations require no background process or registration.

```text
codex-pane [--pane PANE_ID] [--cwd DIRECTORY] [--message-stdin]
```

Omit the message option for an idle session. With the option, read UTF-8 text through EOF, preserve line endings and trailing whitespace, and reject an empty or unrepresentable message before splitting. Use a literal stdin channel in the agent instruction. Include a copyable quoted shell example using a fixed printf format and single-quoted literal data, and explain exact input for multiline text containing quotes. Pass the decoded message to Herdr as one argument after the option terminator. Never interpolate it into executable shell code. Validate the cwd before effects and default to the agent command's actual working directory.

Use the installed local Herdr CLI for structured replies. Direct dependencies are `herdr --skill`, the bundled protocol 22 schema, the predecessor's recorded split/start control, and the named source patterns for typed session matching in `model.py` and snapshot fields in `herdr.py`. Confirm real reply shapes against these and bounded disposable examples. No upstream patch, observer, backend daemon change, or repository-wide research.

1. On the selected local Herdr server, read a fresh snapshot. With an explicit user-selected pane ID, require that exact live pane and its workspace/tab. Otherwise match the current Codex invocation’s `CODEX_THREAD_ID` against exact native Codex session references in live panes. Admit a unique pane only. Use an exact native ID or a typed path uniquely identifying the same session via its canonical Codex rollout filename with the complete thread UUID. Never use a substring, historical state, most-recent session, inherited pane ID, focus, or cwd to break ties. If identification fails, output a request for an explicit pane before mutation. The skill asks the user and resumes with their chosen ID. Keep the Herdr server selection fixed for the invocation.
2. Issue `herdr pane split --pane SOURCE --direction right --cwd DIRECTORY --no-focus` once. Read the new ID from `.result.pane.pane_id`; verify it differs from the source and occupies the selected workspace/tab. Acknowledge any known destination in partial outcomes. Wait boundedly using read-only inspection for a usable shell if necessary.
3. Run `herdr agent start NAME --kind codex --pane DEST` once with a unique Herdr-compatible name. Use stock fresh startup with no resume or positional prompt. Verify the acknowledgement and current destination identify that Codex occupant and a ready state before sending text. If the request times out or the occupant changes, inspect the exact destination and report the evidence. Never repeat a split, startup, or submission after uncertain delivery.
4. If text was supplied, issue `herdr agent prompt DEST -- TEXT` once. An acknowledgement confirms submitted input. Do not wait for the child’s work to complete. Return a concise result giving the known workspace, tab, pane, startup status and message status. Distinguish ready, submitted, omitted, rejected and unknown where applicable. Use a nonzero exit for partial/uncertain results. If a split acknowledgement is lost, do not guess the destination. Read-only recovery may refine status but cannot invent delivery evidence.

## Work and ownership

| Unit | Role and owned paths | Prerequisites and completion |
| --- | --- | --- |
| L1 | Developer, `skills/codex-pane/scripts/codex-pane` and `tests/test_codex_pane_launcher.py` | From the verified base, add executable and public-entry-point tests together. Use a fake Herdr executable with recorded argument vectors, stdin fixtures, structured replies and injected faults. Cover source resolution, split/start/prompt ordering, acknowledgement checks, exact text and partial outcomes. |
| L2 | Developer, tracked predecessor files in `bin/`, `integrations/`, `src/harness_herdr_hooks/` and tracked predecessor `tests/test_*.py` at the pinned base | Disjoint from L1’s new test. Remove the legacy product and its tests on the delivery branch. Use the pinned Git inventory to bound deletion. Never delete untracked files or edit the invoking copy. |
| L3 | Developer, `skills/codex-pane/SKILL.md` | After L1 freezes the interface, create the short action instruction, including no-message, explicit selection, and partial-result handling. Validate from a different project directory. |
| L4 | Documentation writer, `README.md` and the six tracked `docs/*.md` at the pinned base | After final QA, replace legacy operating instructions with one README covering prerequisites, linking/discovery of the skill, invocation, partial failures and evidence. Remove superseded pages. Document retirement **before** removing the old checkout, using its own status/uninstall with the correct profile for Codex and any owned OpenCode installation. Verify preserved unrelated entries in a scratch profile and explain how to retain the old revision if uninstall requires it. Do not change a live profile or disrupt a running conversation. |

The parent prepares the worktree and artifacts, dispatches independent L1/L2, integrates their results, then dispatches L3. Use five-minute bounded specialist assignments, subdividing work on verified handoffs if needed. The parent serializes shared checks, live QA, accepted fixes and Git delivery. L4 owns final documentation, with parent verification of its examples.

## Requirement-to-delivery trace

| SPEC anchor | Delivery and acceptance evidence |
| --- | --- |
| Behavior 1, Acceptance 5 | L1/L3/L4. Run the skill’s invocation from a separate cwd with stock Codex/Herdr, exercise a linked scratch skill directory, and check the active tree for obsolete integrations. No event registration in the test profile. |
| Behavior 2, Acceptance 3 | L1/L3. Exercise a unique exact current session, absent identity, two matching panes even within one tab, stale foreign inherited marker and explicit selection. Inspect fake call logs for zero effects on ambiguity. Exercise the shared-server placement case using isolated panes. |
| Behavior 3, Acceptance 1 | L1. Compare source/destination workspace and tab, focus, pane count and cwd before and after. Cover default and requested cwd. Reject an inconsistent destination response before start. |
| Behavior 4, Acceptance 1–2 | L1/L3. Test leading dashes, quotes, dollar signs, multiline and shell punctuation as literal data. In a dedicated stock Codex conversation compare the actual first user message to the input, count user messages in both child and source, and repeat with omitted input for an idle session. |
| Behavior 5, Acceptance 4 | L1/L3. Inject lost/invalid split, start and prompt replies, rejection and changed occupant. Check exact effect counts, read-only recovery, known pane reporting and explicit uncertainty. |
| Replacement scope, Acceptance 5 | L2/L4. Compare tracked inventory with the pinned base. Keep historical specs and unrelated profile settings. Exercise documented legacy retirement in scratch profiles, then the launcher alone. |

## Validation and assurance

Use full assurance for the cross-component CLI handoff and retirement of public hook/event interfaces. One business capability is involved, opening a Codex conversation in a requested Herdr location. Herdr, Codex and skill discovery are technical participants in that capability. Independent readiness review applies. Architect and security specialist triggers are absent. Contract review applies to removed hook/event contracts and the replacement caller interface.

Run `python3 -m unittest discover -s tests -v`, `skills/codex-pane/scripts/codex-pane --help`, and parent `git diff --check` against the integrated changes, including staged changes before commit. Check the executable bit, skill discovery format, and README invocation. For live QA use a disposable Herdr workspace/server and test-owned conversations, stock Codex with working authentication, and a harmless literal first message requesting a short reply. Read only the exact test conversations to verify transcript contents and counts. Capture source/destination identity, cwd, focus, acceptance and the idle case. Test the wrong inherited marker with two test spaces on one shared server. No mutation of the active user profile, current conversation, or existing user panes. Use isolated test configuration or already-authorized authentication. If authenticated testing cannot run, report the exact missing evidence as DRAFT. Prior operator evidence cannot stand in for it.

An independent code reviewer covers the whole integrated diff alongside an independent contract reviewer. The parent evaluates both reports, assigns one consolidated correction batch, and reruns affected checks. A separate QA agent verifies the final integrated implementation including the live criteria. Follow qualifying correction cycles for confirmed failures before L4 and final reconciliation. Each handoff carries worktree, reviewed SHA or diff, approved artifact hashes, ownership, criteria, results and remaining work. Stage completion continues directly to the next ready unit.

## Git delivery and recovery

Base is pinned to the verified remote `origin/main` commit `5b40ce8c0f1ed214e9faf78536ed4356457a5245`. On 2026-11-24 the remote had no `feat/codex-pane-launcher` ref. The implementation parent refreshes and verifies both refs. For fresh entry create the isolated detached worktree `/tmp/agent-worktrees/harness-herdr-hooks/codex-pane-launcher` at the exact base. Use branch `feat/codex-pane-launcher`; preserve the unrelated dirty invoking checkout and PR #7. A changed base or unexpected existing branch requires reconciliation before edits. For the exact absent-but-registered temporary path, use only guarded non-forced deregistration before recreation.

Capture the invoking checkout identity, HEAD, branch, index and exact bytes/hashes for **only** this approved SPEC and PLAN before copying and verifying both in the delivery worktree. Before the first commit verify branch absence and create it at the verified detached HEAD. Verify both effective approved artifacts in that first local commit; then perform the implement workflow’s guarded two-path origin cleanup before publication. Preserve other paths and uncertain replacements, recording recovery evidence and stopping on ambiguous identity. Verify staged scope and commit. Push without force to `origin/feat/codex-pane-launcher`, verify remote SHA and upstream, and detach the clean retained worktree. No merge, PR #7 modification, or live deployment is part of delivery.

Definition of Done includes the approved pair, all units, successful validation including live transcript evidence, assurance findings disposed, final documentation and verified commit/push. On a concrete blocker complete independent work and publish verified, recoverable DRAFT progress where authorized. If push fails retain the local branch/SHA and cleanup outcome. Resume only after verifying that branch, ancestry, upstream and worktree identity. A DRAFT checkpoint is intermediate and carries its remaining obligations.

## Planning assurance

On 2026-11-24 the independent plan-readiness reviewer checked the full proposed plan body (SHA-256 `32fa656864ca878db3b3a456b209fa6c59df94c322f4da158d0abf6b84b2eb14`) against the approved SPEC digest above, installed Herdr help and pinned Git inventory. The review covered handoff, CLI mechanics, requirement coverage, validation, ownership, assurance and delivery. It returned zero findings. No source or runtime validation was performed during planning.

## Amendment 1 — 2026-11-24 — Use Herdr's positional text argument

- Amendment ID: codex-pane-launcher-PLAN-A1
- Previous version: original approved PLAN, SHA-256 `867ddf03c5fb491f28d80c258b3472e9e0629abebe61bceb88bc0e350417faa2`.
- Approval: Automatically approved 2026-11-24 under the originating standalone implementation request.
- Request and purpose: deliver the approved first-message handoff under the originating standalone `$implement` request.

### Changes against the previous version

| Section / requirement | Before | After | Reason |
| --- | --- | --- | --- |
| Invocation and handoff (both the option-terminator sentence in the stdin paragraph and step 4), L1 tests | Pass an option terminator between DEST and TEXT. | Execute `herdr agent prompt DEST TEXT` once, with the entire decoded text as the single positional argument immediately after DEST in a subprocess argument vector. Check the structured acknowledgement. | Herdr 0.9.5 / protocol 22 returned CLI error 2 for the original form on the disposable server. The documented positional form acknowledged a leading-dash test message with `agent_prompted`. |

### Preserved behavior and impact

The approved SPEC digest is `c7e360566c0066dc469e546fc5f487215a9c7cda7333a2f0d4d0988dad97cd94`. Its behavior and all original acceptance criteria apply. Behavior 4 and Acceptance 1–2 still require L1's exact-argument tests and independent live transcript evidence. L3 and L4 keep literal stdin as the caller interface. Existing selection, bounded effects, no-retry rules, review, QA, ownership and Git delivery apply. The change concerns one business capability, launching a Codex conversation. Herdr argument parsing is a technical dependency of that capability. Independent readiness review applies.

### Approval record

On 2026-11-24 the implementation parent automatically approved the complete original PLAN plus codex-pane-launcher-PLAN-A1 under the originating standalone implementation request. Independent readiness review identified one ambiguity about the earlier stdin paragraph. The corrected table supersedes both original references. The reviewer verified the correction on proposed revision `0c43481f7cb332765ae35da4294037a2de0b4bd60e10a7f35932e90ce7d85afb` with zero remaining findings. The SPEC retains its original approval.

## Amendment 2 — 2026-11-24 — Detect text the stock TUI changes

- Amendment ID: codex-pane-launcher-PLAN-A2
- Previous version: approved original PLAN plus A1, SHA-256 `5fd06f57ad92d0bafff76b538f6fb7ca68ecddb9048769aa74d3c50eb4cd5a60`.
- Approval: Automatically approved 2026-11-24 under the originating standalone implementation request.
- Request and purpose: apply the original unrepresentable-message rule to the authenticated stock client used for the requested first-message handoff.

### Changes against the previous version

| Section / requirement | Before | After | Reason |
| --- | --- | --- | --- |
| Invocation and handoff, stdin validation; L1/L3/L4 | Preserve whitespace and reject unrepresentable text before splitting, without a stock-client representability test. | Reject text that the supported TUI trims, normalizes, or routes as commands before any mutation. This includes boundary whitespace, carriage returns, unsafe terminal controls, leading shell-mode exclamation and slash-command tokens. Keep representable internal spaces, horizontal tabs and LF verbatim. Explain rejection and allow callers to supply different text. | In disposable stock Codex 0.172.0, real transcript entries lost outer whitespace and converted CRLF to LF. Slash commands and shell mode did not produce the requested literal user turn. The positional Herdr acknowledgement does not detect these changes. |

For Herdr 0.9.5 and Codex 0.172.0 use these preflight rules. Reject empty text, initial or final Unicode whitespace, any CR, C0 controls other than horizontal tab and LF, DEL and C1 control characters, and text beginning with `!`. Reject a leading slash-command token when the first whitespace-delimited word starts with `/` and contains no further slash. These are conservative terminal-input boundaries for the supported path. Lexical coverage does not establish observed TUI behavior for every Unicode code point or future client version. The existing invalid UTF-8, embedded NUL and platform argument representability checks also apply.

L1 tests assert zero mutations for each rejected class, including outer spaces and newline, CRLF, ESC/DEL/C1, `!printf QA`, `/status` and an unknown slash command. Positive literal-transport examples include leading dashes, an absolute path with another slash, and internal spaces, LF, horizontal tab, shell punctuation and quotes. Live QA checks an accepted multiline message against the persisted first user turn.

### Preserved behavior and impact

The approved SPEC and its digest remain as recorded in A1. Behavior 4 and Acceptance 1–2 require exact text in the first user turn for accepted input, or an idle child when omitted. L1 tests include pre-split rejection and exact positional transport for representable text. Independent QA compares multiline text containing punctuation and internal whitespace in the actual destination transcript. L3 and L4 describe literal stdin and unsupported inputs. Source identity, destination placement, single dispatch, timeout recovery, approval and Git boundaries continue to apply. The one business domain and required readiness, implementation and contract assurance remain as specified in the original PLAN.

### Approval record

On 2026-11-24 the implementation parent automatically approved the complete original PLAN plus codex-pane-launcher-PLAN-A1 and codex-pane-launcher-PLAN-A2 under the originating standalone implementation request. Readiness review requested deterministic rejection predicates and explicit zero-effect tests, now present above, and evidence for the absolute-path example. The dedicated stock source transcript recorded the exact literal input `/tmp/qa-literal-path Reply only OK.` as a user turn. The reviewer closed both findings on reviewed revision `cee340b2a0cb6f3222cf3a411a2a16b2b30fd1d9fc46069cdd1787e3d8fb6a62`. The original SPEC approval applies.
