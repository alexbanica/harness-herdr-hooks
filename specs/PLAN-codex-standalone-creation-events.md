# PLAN: Discover standalone Codex tasks from typed creation events

Status: Approved

- ID: HHH-004-PLAN
- Date: 2026-11-19
- Approved specification: [HHH-004 SPEC](SPEC-codex-standalone-creation-events.md),
  approved by the user on 2026-11-19; current SHA-256
  `a506853924126c74aca1d73b9b36d2c379db3bd0e52b46238bb5440dc2e53423`.
- Authority: planning only. Approval of this PLAN authorizes a clean-context
  implement handoff, not implementation in this conversation.
- Predecessors: preserve HHH-001/002 artifacts, the approved HHH-003 SPEC,
  and its unapproved PLAN draft. HHH-004 replaces the HHH-003 parser mechanism
  and cwd assumption, as explicitly approved in the replacement SPEC.

## Final implementation and boundary

Add a bounded reader of the verified parent's newly appended local rollout
records. Recognize the observed typed successful codex_tui/create_thread
completion event, store a minimum creation association, verify its returned task on the
same backend, and attach that existing task once in an unfocused same-tab pane.
Use an explicit standalone association type; do not manufacture native ancestry
or apply subagent completion cleanup. Retain the standalone pane after completion.

Use the existing automatically bootstrapped observer and native attachment path.
Do not depend on unverified PostToolUse delivery, add a separate daemon, execute
transcript JavaScript, scan arbitrary conversations, replay prompts, modify the
Codex app, or broaden supported task origins. Implementation uses the approved
SPEC, this PLAN, and named source patterns below; no reopened product research.
An unsupported actual format or unprovable parent-file binding is a qualification
failure, not permission to guess another association mechanism.

## Baseline, dependencies, workspace, and delivery

- Repository: `/home/alexbanica/workspace/harness-herdr-hooks`;
  origin `git@github.com:alexbanica/harness-herdr-hooks.git`.
- Invoking checkout stays on `main`, research HEAD
  `e4ee497cb1c8d2273d2487c4e932b27ea398a580`. Preserve all unrelated untracked
  lifecycle artifacts and the retained installed-source worktree.
- Source dependency: delivered HHH-002 checkpoint
  `274b54c0d813b79774b1d7b88e3d5abb5dcfec82` on
  `origin/feat/codex-herdr-session-lifecycle`. Its available source contains the
  default-backend, standalone retention, and cleanup-lock fix required here.
  This is branch delivery, not verified main integration or native acceptance.
- Pin the checkpoint's HHH-002 SPEC SHA-256
  `6c4934c18c6b9578972ec27b2308bff9ce738fc7607b575ca66c428aeb23a08c`
  and PLAN SHA-256
  `4bd5ed1517fcf9f6f2640dee5438000deab7fab4199bc360d535dc724ace575a`
  as source references. The invoking PLAN additionally contains pending A1;
  do not transfer it over the delivered predecessor, approve it, or implement
  its unrelated remainder. HHH-004 adds its own complete delivery obligations.
- New delivery branch: `feat/codex-standalone-task-discovery`.
- Worktree: `/tmp/agent-worktrees/harness-herdr-hooks/codex-standalone-task-discovery`.
- Parent refreshes the delivery branch if it exists and verifies checkpoint
  ancestry for continuation. Otherwise refresh origin's HHH-002 branch, require
  the exact pinned source commit remains available and reachable there, and
  prepare a detached worktree at that exact commit. Do not silently substitute
  invoking main or a newer predecessor head. A changed required baseline needs
  the implement amendment procedure before assignments.
- Follow implement's ordinary guarded new-branch lifecycle: capture recovery
  preimages, transfer this approved SPEC/PLAN and the byte-identical HHH-003
  SPEC referenced by HHH-004, with byte/hash verification. HHH-003 reference
  SHA-256 is `7abd3269991ef873af42f9c1d060d3bff402dfc64aeadd9a239c34705a7249d0`.
  Do not transfer the unapproved HHH-003 PLAN or overwrite predecessor files;
  verify source baseline and clean permitted path states, keep detached during
  source work, and create the exact new branch at accepted HEAD immediately
  before its first authorized commit after verifying absence and no attachment.
  For a registered-but-absent exact temporary path, use only non-forced removal
  of that registration and verify before recreating; conflicting/dirty/present
  unsafe paths stop. Never prune unrelated registrations.
- Parent alone commits accepted source, tests, documentation, this pair, and
  the unchanged HHH-003 SPEC reference,
  and pushes non-force to `origin/feat/codex-standalone-task-discovery`, verifying
  local commit, configured upstream, remote SHA, and artifact inclusion. Open a
  DRAFT PR targeting `feat/codex-herdr-session-lifecycle` to keep this diff separate
  from the unmerged predecessor; no automatic merge, release, tag, or deployment.
  Verify its actual head/base. Changing the integration base requires amendment.
- After verified delivery, detach and restore only unchanged transferred content
  and index state in the invoking checkout. Preserve the clean worktree if owned
  installed-source references point to it; otherwise follow guarded cleanup.
  Checkpoint resume fetches the same branch, verifies recorded checkpoint ancestry,
  and fast-forwards only. Do not reset work or reuse another task's branch.

## Deterministic implementation choices

1. **Parent-file selection.** Obtain the exact parent path from verified native
   `thread/read` metadata (`path`) and cross-check hook/Herdr path information
   when supplied. Open without following symlinks; verify canonical containment
   under the selected profile's local sessions directory, owner, regular file,
   and `session_meta` identity against the bound parent. Do not locate a parent
   by cwd/time/title. Missing/contradictory metadata fails closed. Validate on
   reopen and track device/inode/size with cursor identity. No entire-turn or
   transcript-item API reads are introduced into lifecycle metadata checks.
2. **Qualified parser.** New `codex_task_records.py` owns streaming JSONL and
   the exact grammar in the approved SPEC's “Exact qualified event grammar and
   provenance” section. Build its positive sanitized fixture from that included
   JSON example, not from more private conversation research. After one outer
   JSONL decode require `type=event_msg`, `payload.type=item_completed`, bound
   `payload.thread_id`, nonempty `payload.turn_id`, and `payload.item` with
   `type=McpToolCall`, `server=codex_tui`, `tool=create_thread`, nonempty `id`,
   `status=completed`, and `result.isError` exactly false. `result.content` is
   a list of content objects; decode the JSON string in its text block to obtain
   `threadId`. Require one unambiguous nonempty child ID different from parent;
   reject conflicting result IDs, duplicate JSON keys in identity-bearing objects,
   error/incomplete results, or unsupported shapes. Unknown harmless extra fields
   are ignored, never saved or logged. Event identity is parent/turn/item IDs;
   do not correlate outer exec call IDs, parse JavaScript, or require later
   read_thread/codexDelegation output. An event nominates a candidate, never native
   ancestry. Messages and other tools' outputs that quote this JSON are ineligible.
   The original item contains arguments/title/prompt: ignore and discard them.
3. **Bounded defaults.** Per observer tick read at most 1 MiB and 256 complete
   records; maximum line/partial record 1 MiB, nesting depth 12, and at most
   128 pending validated event associations. Exceeding a limit records a bounded diagnostic and
   skips unsafe capture rather than unbounded scanning. Reuse the existing
   observer interval. Metadata retries: at most three attempts within 30 seconds
   per candidate, persisted to survive restart. Choose monotonic elapsed timing
   in-process and validated timestamps for restart deadlines. These are internal
   conservative limits, not new public configuration or weakened acceptance.
4. **Atomic association state.** In the existing private schema-2 namespace,
   add optional bounded fields for file/cursor identity, parent/turn/item/child
   IDs, backend/context pins, and retry/attachment outcomes. Missing fields in
   legacy state initialize safely; malformed known fields fail closed. Preserve
   unrelated fields and use existing private lock/atomic-write rules, without
   changing the predecessor schema version. Atomically commit a consumed cursor
   with its validated candidate so a crash cannot lose or replay the association.
   Never persist raw lines, arguments, tool input/output, prompt/preview, or bodies.
   An incomplete line's persisted offset stays before that line so restart rereads
   it. The first binding starts at existing EOF; if EOF is mid-record skip its
   eventual remainder. Fresh starts do not backfill. Truncation/replacement
   establishes a new safe boundary and diagnoses the gap; never replay history.
   Retain pending verified associations and attachment state across reader resets,
   revalidating native context before use; a changed parent/backend revokes them.
   For the observed ID-only result, native task metadata supplies cwd; an absent
   creation-result cwd is valid. Missing/nonabsolute native cwd rejects attachment.
   If a qualified result includes cwd, keep only its normalized absolute cwd
   SHA-256 as a context pin (raw value transient), compare with identically
   normalized native cwd, and reject mismatch. Normalize lexically, without
   filesystem probes/link resolution. Persist whether that optional pin exists.
   Tests cover ID-only/native-cwd success, optional-cwd match/mismatch, absent or
   invalid native cwd, and every comparison across deferred verification/restart.
5. **Association versus ancestry.** Add an optional explicit minimum creation
   proof record to the internal session model/serialization, with a distinct
   standalone kind. Coordinator accepts that kind only through validated state
   and exact parent/context proof. Native subagents continue to require native
   ancestry. Missing legacy fields deserialize safely; malformed/new unsupported
   proofs fail closed. Keep separate-session retention and existing display reuse.
6. **Native verification.** For exact candidate IDs only, read metadata on the
   parent's pinned backend; compare cwd, profile and incarnation, loaded/running
   status, parent proof and current destination before attach. Use the existing
   native `resume --remote ... <id>` display path, without a prompt. Claim under
   the state/observer lock, release state locks for external calls, and reconcile
   only the unchanged association generation. No lock reentry or blanket removal
   of existing ancestry checks. Existing finished tasks are never newly displayed.
7. **Status.** Extend existing runtime evidence with bounded recognition,
   association-validation, and attachment outcomes; avoid a second status store
   or persistent runtime registry. Preserve unknown fields in unrelated records
   and only uninstall owned integration state/configuration.

## Work units and ownership

Production module paths below are relative to `src/harness_herdr_hooks/`;
`tests/...`, documentation, and artifact paths are relative to the repository root.
Test modules use standard-library unittest. Tests stay with their production behavior and
are written first for new parser/state/routing failure cases. Parent serializes
units sharing integration state; at most one active developer owns shared paths.

| Unit | Owner and immutable paths | Prerequisites | Completion and checks |
| --- | --- | --- | --- |
| U10 | Developer: new `codex_task_records.py`, new `tests/test_codex_task_records.py` | Parent verifies base/artifacts | Strict sanitized observed-envelope parser, file identity, incremental bounds, partial-write and malformed/lookalike cases; targeted tests pass. |
| U20 | Developer: `model.py`, `state.py`, new `tests/test_standalone_task_state.py`, existing `tests/test_lifecycle_state.py` | U10 interface verified | Minimum explicit proof, atomic cursor/candidate state, private serialization, pending-event recovery and dedup; no retained content, regression tests pass. |
| U30 | Developer: `adapters/codex.py`, `cli.py`, `coordinator.py`, `tests/test_codex_events.py`, `tests/test_codex_integration.py`, `tests/test_runtime_status.py`, `tests/test_pane_ownership.py`, `tests/test_subagent_completion.py`, new `tests/test_standalone_task_discovery.py` | U10/U20 verified | Automatic observer integration, exact parent-file/backend proof, distinct routing and retention, runtime diagnostics, race/restart/manual-close scenarios; full suite passes. |
| U40 | Independent code-reviewer and contract-reviewer, read-only whole integrated boundary | U10–U30 complete/frozen | Review complete integrated diff and SPEC/PLAN trace, minimal state/event schemas, producer/consumer compatibility, failure behavior and preserved native/OpenCode paths. Parent disposes all findings. |
| U50 | Fresh bounded developer, correction ownership limited to accepted U10–U30 findings | Entire U40 wave returned | One consolidated correction batch, affected checks; parent reassesses and performs required diff check. No extra review within this cycle. |
| U60 | QA agent read-only except explicitly bounded live qualification effects below; no source edits | Accepted corrected integration | Independent final QA against A1–A5, exact commands/evidence and gaps. Parent coordinates mutations and verifies results. |
| U70 | Documentation-writer: README.md, docs/install-codex.md, docs/contracts.md, docs/isolation.md, docs/troubleshooting.md, docs/validation.md | QA disposition, no qualifying repeat cycle | Synchronize final behavior, exclusions, format/limits, privacy, setup and actual static/native evidence; stop on semantic mismatch. |
| U80 | Parent only: integration, this SPEC/PLAN pair, Git/PR and final acceptance | All applicable units complete | Verify Definition of Done, staging, commit/push/remote/PR evidence, or deliver explicitly blocked DRAFT with exact gaps. |

Every specialist gets a fresh-context bounded assignment with unit ID, exact
artifact digests, source/check navigation, criteria, immutable ownership,
prerequisites, allowed effects and JSON-only handoff. Children never branch,
commit, push, install, deploy or create worktrees. Aim three minutes per launch;
parent interrupts at five minutes, preserves verified partial evidence, and
splits remaining disjoint work without reassigning uncertain active ownership.
Use ephemeral navigation bundles with effective artifacts, hashes, full integrated
diff, trace/check evidence, and unresolved findings; handoffs are one JSON object
with matching unit_id/status and assignment-specific evidence, validated by parent.
Queue to available native capacity; capacity saturation never ends execution.

## Assurance and validation

**Full assurance.** This changes provenance checks, cross-component attachment,
and internal persisted/event consumer semantics. One independent integrated
code-review wave, consolidated corrections, final independent QA and final
documentation writer are required. Contract review is required for the new
creation association and persisted producer/consumer record semantics. Security
review is not selected: no explicit user security-review request covers this
work; code/contract review and QA still cover trust and data-minimization concerns.

Planning domain assessment: a single technical capability, displaying verified
agent-created Codex tasks in Herdr; parser, state, native backend and pane API are
technical layers, not interacting business domains. Architect plan assurance is
not triggered. Independent plan-readiness review remains mandatory.

Development and QA run from the isolated worktree, with private temporary caches:

- `PYTHONPATH=src python3 -m unittest discover -s tests -v` for all existing and
  added tests; targeted `unittest discover -s tests -p '<module>.py' -v` during
  development. Test new capture fixtures with fake backend/Herdr transports,
  actual bounded file append/reopen behavior, and real-process lock watchdogs.
- `PYTHONPYCACHEPREFIX=<private-tmp>/pycache python3 -m compileall -q src tests`;
  `sh -n bin/harness-herdr-hooks`; `node --check integrations/opencode/plugin.js`;
  `python3 -m json.tool integrations/codex/hooks.json`.
- Isolated HOME/CODEX_HOME/XDG directories for operator install/status/uninstall
  regression checks through the public entrypoint; retain unrelated hook/config
  preimages and compare afterward. No real credentials copied. Do not alter hook
  registration solely to add unverified PostToolUse support.
- Run configured existing lint/quality checks if present on the pinned baseline;
  no new CI framework or unrelated lint cleanup. Inspect any existing hosted PR
  checks after push and report their actual result; no platform success invented.
- Parent runs `git diff --check`, inspects the complete accepted diff and staged
  paths, confirms privacy of fixtures/evidence and no predecessor artifact edits.

### Bounded live qualification and effects

PLAN approval followed by a fresh implement invocation explicitly requests one
new harmless standalone Codex smoke task for A5, not another product work task.
Use the actual app create_thread tool from a verified Herdr-bound parent. Its
prompt requests only a bounded wait (up to 30 seconds) and a fixed short reply;
no file changes, shell mutations, network actions or product work. Inherit model
and permissions. Parent records the original/new thread IDs and turn IDs using
metadata only to verify attachment added no inference turn or prompt.

Before mutation, verify the actual running backend/app/Herdr qualification and
the parent-file binding. Reconcile any active predecessor implementation owner
and its selected-profile/install authority; this independent branch must not
replace another active worker's handler or installed-source reference. Conflicting
ownership blocks live mutation, while source/review/DRAFT delivery can continue. Explain the exact owned hook installation/update and
effect to the user in a checkpoint, then use the existing public installer for
only the selected parent Codex profile if needed. Preserve unrelated config and
trust settings; never restart active work or the shared daemon, lower socket
permissions, bypass trust, or install into another profile. Missing native trust
or a required user-owned reload is a concrete blocker, not automatic authority
to restart. Retain the installed-source checkout while references point to it.

The smoke task is expected to create one unfocused same-tab owned display pane.
Observe exact native session/backend association, focus, single display, no
added turn and completion retention. After confirmed smoke-task completion, use
only its verified integration-owned display client's native exit UI to test the
retained usable shell; do not stop its backend or other clients. Missing safe
display-only exit control leaves that evidence pending, never a process kill.
Do not close the retained standalone pane automatically as test cleanup. Use
controlled tests for destructive/foreign-profile/failure race cases; do not
tamper with unrelated live panes, backend state or credentials to exercise them.
If unavailable, record the precise missing A5 evidence and continue safe source,
review, documentation and authorized DRAFT delivery. Manual attachment is not
automatic-capture acceptance. Existing predecessor runtime/macOS/OpenCode gaps
remain disclosed independently; HHH-004 does not certify them or require unrelated
remediation. Newly broken preserved behavior is an HHH-004 regression to fix.

## Requirement-to-delivery trace

| Requirement / acceptance | Units and paths | Required evidence |
| --- | --- | --- |
| R1, A1, A5: exact verified parent and file | U10/U30, parser, adapter, cli | Parent metadata/path/header/file identity fixtures and live binding. |
| R2, A1: qualified successful creation | U10/U20, parser/state | Approved typed-event fixture; parent/tool/item/result validation, duplicate/error/lookalike tests; no body retention. |
| R3, A1/A2/A5: independent backend proof | U20/U30, state/adapter/coordinator | Same-backend active/loaded exact child; ID-only result/native-cwd authority, optional returned-cwd match/mismatch and native-cwd absence/invalidity, recovered optional digest across restart; delayed/finished/foreign metadata cases; native smoke. |
| R4, A2/A3/A5: one existing-task attachment | U20/U30, state/coordinator | Idempotent claim/recovery, manual close/reuse, focus/destination checks, unchanged task turn metadata. |
| R5, A3/A4/A5: standalone lifecycle | U20/U30, model/coordinator | Retention through terminal/client exit, recursion and native-subagent cleanup regression; live retained shell. |
| R6, A1/A3: privacy/bounds/recovery | U10/U20/U30 | Bounded append/truncation/replacement/restart/concurrency and log/state redaction checks. |
| R7, A4/A6: preserved behavior/status/docs | U30/U60/U70 | Existing launch/subagent/ownership/OpenCode/static and isolated operator checks; accurate docs and bounded status. |
| All scope exclusions and predecessor preservation | Parent/U40/U60/U80 | Full diff, artifact hashes, no API-root broad discovery or extra task prompts, source/runtime evidence separation. |

## Findings, checkpoints, and terminal delivery

Parent reconciles every code/contract finding after the whole wave, applies one
accepted correction batch, and reruns affected checks. QA concerns record evidence,
severity, benefit/impact, recommendation and amendment class. Repeat the full cycle
only for a confirmed required-check/acceptance failure, regression, incompatibility,
high/critical security defect or blocked requested behavior whose correction
benefit exceeds impact. Speculation and unchanged passing checks do not add cycles.
Required behavior/plan amendments during valid implement use its recorded automatic
amendment procedure; missing external authority and unsafe effects still block.

At each reached checkpoint parent reports sequential Checkpoint XX, completed
work, next ready obligation and verified commit/branch/push evidence or explicit
not committed/not pushed. Handoffs, review completion and checkpoint commits are
intermediate, not continuation gates. Continue through the approved lifecycle.

Definition of Done: R1–R7 and A1–A6 satisfied with actual evidence, full applicable
assurance/corrections/QA/docs complete, approved pair and accepted source delivered,
verified commit/upstream/remote/PR head and base, no unrelated changes, safe transfer
restoration and installed-source retention. Otherwise explicitly blocked DRAFT
with exact unmet criteria and safe accepted branch delivery where possible.

Genuine stops: changed/unverified artifacts or base; conflicting worktree/ownership;
unavailable safe native attachment or trustworthy parent-file binding; unsupported
record format; unsafe/foreign identity; missing trust/reload or capability; denied
authorized effect; changed delivery destination; required check/qualification gap.
Finish safe independent work first. No deployment/main merge is authorized.

## Planning assurance

- Independent plan-readiness-reviewer unit `HHH004-readiness` reviewed the
  complete PLAN SHA-256
  `980f5bd3aae5cc61b3f968e81e635272aeb0a1c6d87d2516d48d878e5a027671`
  against approved SPEC SHA-256
  `a506853924126c74aca1d73b9b36d2c379db3bd0e52b46238bb5440dc2e53423`.
  Coverage: R1–R7/A1–A6, exact typed-event/ID-only-cwd handoff, distinct
  association/native ancestry, state/privacy/recovery, specialist ownership,
  validation/live effects, pinned baseline and worktree/PR delivery.
- One low finding: the ownership introduction could make root-relative test
  paths appear relative to the production package. It now explicitly identifies
  production paths separately from repository-root tests/docs/artifacts.
- Parent validated the JSON object, identity, reviewed hashes, baseline and
  semantic coverage. This was a fresh complete review; HHH-003 review was not
  carried forward as passed. Review is advisory, not approval or native evidence.
- The same reviewer verified the correction against PLAN SHA-256
  `ca6bcd646d2d4da4af5eafb1f56db99e570ed72eeb883e03e518264bd37e192b`:
  no remaining findings. Independent in-memory reversal of the ownership and
  assurance-record edits reconstructed the initial reviewed digest, verifying
  unchanged full-review coverage. This final record adds review evidence only;
  implementation choices and the approved SPEC remain unchanged.

## Approval

Approved on 2026-11-19 by the user's explicit response "approve" to the complete
HHH-004 PLAN approval question after independent planning assurance.
Reviewed Proposed file SHA-256:
`56f7e91404b57e95cc9275d95b048d90add62cee616299af35261e57fa1d77b9`.
Approval covers the complete PLAN, including its pinned baseline, isolated
worktree, bounded live qualification, assurance and branch/PR delivery.
Implementation requires invoking implement with this pair in a new assistant
conversation/session. No implementation, commit, push, hook installation, smoke
task, or pane mutation has been performed in this planning session.
