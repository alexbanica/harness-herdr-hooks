# PLAN: One named subagent tab per main session

Status: Approved

- ID: HHH-005-PLAN
- Date: 2026-11-19
- Approved specification: [HHH-005](SPEC-session-subagent-tabs.md), approved
  2026-11-19 by the user's explicit `approve` response.
- Approved SPEC SHA-256:
  `379efe75181c91d8a8349c31986223fb55519a4c54464ebc45214bdb3b14a8b4`.
- Research checkout: `/home/alexbanica/workspace/harness-herdr-hooks`, `main`,
  `dabbc6eb20fde4528238b490b9f424e929e0e477`.
- Authority: standalone planning only. PLAN approval must precede a fresh-session
  `implement` invocation; this session performs no implementation or delivery.

## Final behavior, scope and dependencies

Deliver SPEC requirements 1–13: a lazy unfocused subagent tab per verified main
session for both Codex and OpenCode, nested sharing, one-way root-title naming,
safe recovery and removal only when empty. Preserve main panes, independent
session placement, existing pane lifetime and ownership checks, and legacy
same-tab bindings. Do not move historical panes or change native inference.

The exact predecessor delta is defined by the SPEC's “Predecessors and exact
delta” section: HHH-001/002 subagent placement and tab naming change; HHH-002's
independent launch and completion rules and HHH-003/004 standalone discovery,
classification, retention and placement are preserved. All predecessor SPECs
and PLANs, including amendments and untracked pairs, are excluded from edits.
This work depends on delivered core identity/attachment behavior on main, not
on implementing the untracked standalone plans or merging their branches.
If a refreshed base already contains standalone discovery, preserve it without
reimplementing or broadening it; its independent kind must bypass subagent
tab routing. Untracked origins remain read-only references in the invoking
checkout and are not swept into this delivery.

Implementation uses the approved pair and the named source patterns below.
No renewed repository-wide research, unrelated maintenance, external repository
mapping, new discovery feed, unsupported protocol fallback or dependency upgrade.
Narrow version-matched Herdr transport qualification is a direct prerequisite,
not authority to patch Herdr or relax the SPEC.

## Workspace, base and branch delivery

- Exact delivery branch: `feat/session-subagent-tabs`, remote `origin` at
  `git@github.com:alexbanica/harness-herdr-hooks.git`.
- Isolated execution worktree:
  `/tmp/agent-worktrees/harness-herdr-hooks/session-subagent-tabs`.
  Leave the invoking checkout on its current branch; preserve all unrelated
  files, index entries and installed-source references. Planning stays here.
- At implement entry, verify artifacts, checkout/common Git identity, worktrees
  and remote. Refresh `origin/feat/session-subagent-tabs` if it exists; otherwise
  refresh/use `origin/main`, falling back to `origin/master` only if main is
  unavailable. Record the selected ref and resolved commit before source edits.
  Research SHA above is evidence, not an exact-base pin. Fetch failure, unsafe
  state or incompatible new baseline is a DRAFT blocker, not reset authority.
- Capture approved pair content/index/HEAD preimages. Transfer only this pair
  with hash verification and retained recovery state; verify predecessors from
  their existing tracked/source origins without altering or committing the
  unrelated untracked pairs. New work starts detached from the verified base.
  A registered-but-absent exact temporary path may be deregistered only with
  non-forced `git worktree remove`, followed by verification before recreation.
  Other conflicting, dirty or unsafe path states stop; never prune other work.
- Immediately before the first accepted commit, require the exact new branch
  absent locally and unattached, and create it at verified detached HEAD. A
  genuinely existing remote delivery branch uses verified checkpoint-resume
  ancestry, clean registered workspace and fast-forward-only recovery; do not
  reset to main or treat unrelated existing branch work as this checkpoint.
- Parent alone stages accepted source/tests/docs and this approved pair, checks
  actual staging and predecessor exclusion, commits and pushes non-force to
  `origin/feat/session-subagent-tabs`. Verify local commit, upstream destination,
  remote SHA and accepted artifact inclusion. No main merge, release, deployment,
  tag or PR mutation is part of this delivery.
- Checkpoints with remaining obligations are DRAFT. After verified push detach
  safely and restore only unchanged transferred content/index in the invoking
  checkout. Retain the worktree while selected-profile installed-source links
  reference it; do not delete code still used by a live helper. Any restoration
  or delivery verification failure remains explicit DRAFT.

## Deterministic design and source boundary

Production paths in this section are relative to `src/harness_herdr_hooks/`;
test, documentation and artifact paths are repository-root relative.

1. **Authority distinct from destination.** Keep the original `ParentBinding`
   as proof of the main/requesting pane and backend, never overwrite its tab ID
   merely to satisfy old same-tab guards. Add an explicit optional serialized
   destination association for integration-created subagent bindings: full
   main context key, server/workspace/tab identity, ownership/create generation,
   and recorded initial/child pane identity. Missing association in legacy
   records retains their existing same-tab checks; malformed associations fail
   closed. Independent bindings never acquire a subagent-tab destination.
2. **Shared tab manager.** New `tabs.py` owns root association, destination
   selection, naming, create/recover/remove transitions. Use existing private
   `StateStore` infrastructure in a root-scoped namespace derived from the full
   main context, Herdr server identity and workspace. A workspace-scoped
   namespace in the same private state infrastructure owns label reservations
   keyed by exact full root context and creation generation. No separate daemon,
   external registry or persisted agent-coordination lifecycle. Add optional
   bounded schema-2 fields; preserve unknown fields and existing baseline,
   suppression and generation history. Private modes, no-follow opens and
   atomic writes remain mandatory.
3. **Concurrency and unknown outcomes.** Use workspace-label and root-tab
   operation locks, distinct from observer/helper/state locks, for label,
   create/attach-claim/cleanup arbitration. Workspace lock identity includes
   the Herdr server incarnation and workspace, spanning all managed roots and
   both harnesses. Always acquire workspace operation lock, then root operation
   lock, then one short state lock at a time; never acquire an operation lock
   while holding a state lock or nest workspace/root state locks. Do not retain
   state locks across external calls. Operation acquisition is nonblocking:
   contention defers the candidate to the observer tick, not another tab.
   All mutations of tab associations/reservations use this order. Persist generation and
   intent before external creation; commit acknowledgement only to the same
   generation. A lost acknowledgement becomes an unresolved creation claim;
   recover only from exact server-returned/owned association evidence, never
   title/cwd matching or blindly repeating creation. Unknown outcomes remain
   bounded diagnostics until safely resolved.
4. **Root and title metadata.** Add bounded provider operations in both
   adapters to resolve the verified main association and its display title.
   Use exact-session metadata on the existing selected backend, validated
   native ancestry and already owned bindings for nested display clients.
   Stop at independently classified conversations: an independent session's
   subagents form a separate tree. Bound parent traversal to the existing
   32-hop Codex pattern and reject cycles, missing links, foreign contexts or
   ambiguous roots. No unrelated-history scans, title-based ancestry, or
   promotion of every backend root. Codex root `name` and OpenCode root `title`
   feed labels; missing/empty initial title uses the harness name, while later
   missing metadata preserves the last valid label. Poll title metadata on
   the existing observer tick; no new public interval option.
5. **Labels.** Keep existing child-pane sanitation. Add a separate tab formatter
   using `Subagents: <title> [<ID>]`, initially eight ID characters, extended
   on managed-label collision. Reserve the prefix/suffix inside the supported
   label length (current pane helper uses 64), truncating only sanitized title.
   Under the workspace operation lock, reserve the shortest resulting label
   not already reserved by another live or unresolved managed root generation.
   Compare complete sanitized/truncated labels, not titles or suffixes alone.
   Grow only the current root's displayed ID prefix one character at a time;
   never rename another root to resolve a collision. Thus even two contexts
   with identical full session IDs can use different prefix lengths (eight
   and nine, for example). Persist the chosen label/reservation before the
   create/rename request, and retain it across unknown outcomes. On confirmed
   rename reserve the new label before releasing the old one; on failure retain
   all possibly visible reservations until reconciled. Release a reservation
   only after exact owned tab removal or confirmed rename, not a title lookup.
   If no distinct label fits before reaching the full ID/display limit,
   fail closed with a bounded label-exhaustion diagnostic rather than create
   or rename to a duplicate label. This is the existing safe-failure boundary,
   not a new naming pattern or identity inference. Tests cover two concurrent
   roots sharing the first eight characters, identical full IDs in different
   full contexts, rename collisions, interrupted reservations and exhaustion.
   Store full identity regardless of display. Rename only the exact still-owned
   tab, never the main tab/workspace or native title.
6. **Herdr operations and safe emptiness.** Extend `herdr.py` with the qualified
   protocol operations and strict acknowledgement checks for unfocused tab
   creation, its returned initial pane, targeted split and tab rename. Verify
   workspace, tab/pane IDs, focus, server incarnation and initial cwd. Reuse the
   initial pane through the existing wrapper path; do not create a spare shell.
   Qualify actual protocol shapes and last-pane semantics before enabling the
   path. Prefer Herdr's automatic removal when closing the final verified owned
   pane. Explicit tab deletion is permitted only if the qualified operation
   atomically refuses occupied tabs; snapshot-then-unconditional `tab.close`
   is forbidden. Root locks coordinate this integration but do not protect
   against user/foreign pane creation. If neither safe mechanism is available,
   retain the tab and report the exact required evidence/capability gap as
   DRAFT; do not weaken acceptance or patch another repository.
7. **Attachment and closure integration.** Update `attach.py` wrapper validation,
   split/initial-pane selection and failed-before-exec cleanup, plus
   `coordinator.py` existing-display adoption, owned-state checks, title path,
   generation completion cleanup and observer reconciliation. Every destination
   check must require the exact persisted tab association as well as unchanged
   original parent/backend proof. No blanket removal of same-tab checks.
   `cli.py` must resolve nested hook/display associations to the same main tab
   and extend bounded existing status evidence with tab state/identity and
   failures; do not change public commands or native hook/event schemas.
8. **Lifetime, recovery and legacy.** A manually removed tab suppresses its
   removed child displays through existing session/generation state; title
   changes/restart cannot recreate them. A genuinely new eligible child may
   create the next tab generation. Existing legacy panes stay where they are
   and keep their lifecycle rules. Occupied/foreign/manually moved tabs/panes,
   changed server identities and invalid root associations cannot be moved,
   adopted or closed. Parent exit revokes attachment authority; cleanup may
   only recognize auto-removal or use independently proven owned-empty state.
   Never kill clients or backends to empty a tab.
9. **Bounded reversible defaults.** Retain existing observer tick and retry
   budgets; keep only IDs, sanitized bounded labels, generation/ownership and
   bounded failure reasons. No prompt, transcript or raw environment retention.
   Optional fields default to legacy behavior and unsupported operations fail
   closed. No installer/plugin changes are required for new event registration;
   existing handlers may need selected-profile relinking/reload as documented.

## Units, ownership and execution order

Tests accompany their production behavior using standard-library unittest;
write meaningful identity/race regression tests first. Parent serializes shared
source and repository-wide checks. A single worker owns a unit's paths at a time.

| Unit | Role and immutable owned paths | Prerequisites and completion |
| --- | --- | --- |
| U00 | Parent: approved pair, workspace/Git integration; bounded explorer for installed protocol evidence only | Verify approved digests/base and actual tab/empty semantics. Source work may proceed with controlled fixtures, but unavailable safe native capability blocks acceptance. |
| U10 | Developer: `herdr.py`, `model.py`, `state.py`, new `tabs.py`; new `tests/test_subagent_tabs.py`, new `tests/test_tab_state.py`, `tests/test_lifecycle_state.py` | U00 handoff. Strict operations, optional destination records, root locks/claims, naming and cleanup manager with private legacy-compatible state; focused tests pass. |
| U20 | Developer: `adapters/codex.py`, `adapters/opencode.py`; new `tests/test_tab_roots.py`, `tests/test_codex_events.py` | U10 verified interfaces. Bounded main/title/ancestry operations for both providers, independent-tree boundary and missing/cyclic/foreign cases; focused tests pass. |
| U30 | Developer: `attach.py`, `coordinator.py`, `cli.py`; `tests/test_pane_ownership.py`, `tests/test_subagent_completion.py`, `tests/test_codex_integration.py`, `tests/test_interactive_launch.py`, `tests/test_runtime_status.py`; new `tests/test_tab_routing.py` | U10/U20 verified. Initial-pane reuse, nested events, cross-tab wrapper verification/adoption/cleanup/status and legacy/independent preservation; integrated tests pass. |
| U40 | Independent code-reviewer and contract-reviewer, read-only whole integrated change | U10–U30 frozen with digests/diff/test evidence. Cover all SPEC invariants, protocol/state producer-consumer compatibility, lock order and failure ownership; advisory findings only. |
| U50 | Fresh bounded developer, accepted corrections only within U10–U30 ownership | Entire U40 wave returned and parent dispositions recorded. One consolidated correction batch, affected checks, parent assessment. |
| U60 | Independent QA, no source edits; only bounded qualification effects below | Corrected integration accepted. Final full QA and both-harness runtime evidence or exact blocked DRAFT gaps. |
| U70 | Documentation-writer: README.md, docs/install-codex.md, docs/install-opencode.md, docs/contracts.md, docs/isolation.md, docs/troubleshooting.md, docs/validation.md | QA disposition with no qualifying repeat cycle. Match actual behavior, exclusions, lifecycle and observed evidence; stop on semantic mismatch. |
| U80 | Parent only: final acceptance, pair and Git delivery | Full Definition of Done assessment, inspected staging, verified commit/push or safe blocked DRAFT delivery, guarded transfer restoration. |

Sequence U00 → U10 → U20 → U30 → U40 → U50 → U60 → U70 → U80.
Root protocol evidence and safe independent parent preparation may overlap;
developers are serial because interfaces and ownership guards are coupled.
No child creates worktrees, branches, commits, pushes, installs, deploys or
approves. Each assignment has a stable unit ID, fresh-context manifest,
effective artifact hashes, source/check navigation, immutable ownership,
prerequisites, allowed effects and JSON-only result contract. Aim three minutes;
interrupt at five, reconcile verified partial outcomes and split remaining
disjoint work without extending deadlines or overlapping uncertain ownership.
Queue at native capacity; temporary saturation is scheduling, not a blocker.

## Assurance and correction rules

Select **Full** assurance: cross-component native attachment and private shared
binding/state producer-consumer semantics change. Require independent integrated
code review, contract review, consolidated corrections, final independent QA
and final documentation writer. Contract review is triggered by optional
persisted destination associations consumed by the wrapper/observer and by
new external Herdr operations/acknowledgements. Native harness event types and
payloads remain unchanged. Security specialist review is not triggered: no
explicit user security-review request covers this work. Ownership/privacy/
permission checks still remain code/contract/QA responsibilities.

Planning domain assessment: one technical capability, grouping verified
delegation displays in Herdr. Codex/OpenCode adapters, state, protocol and
cleanup are technical layers of that capability, not interacting business
domains. Architect planning assurance is not triggered. Independent full
plan-readiness review is mandatory before approval presentation.

Parent supplies pinned baseline/current source, full integrated diff, pair
hashes, requirement trace, checks/results and unresolved findings to each
reviewer. Validate JSON identity/status and semantic coverage. Wait for the
whole U40 wave, dispose supported findings, then one accepted correction batch
and affected validation, without an extra review inside that cycle.
Record QA concerns with evidence, severity, benefit/impact, recommendation and
amendment class. Repeat a full cycle only for confirmed acceptance/check
failure, regression, incompatibility, high/critical security defect or blocked
requested behavior whose correction benefit exceeds impact. No speculative
cycles or repeated unchanged passing checks. During valid implement, required
amendments use its automatic amendment procedure; missing external authority
or unsafe effects remain blockers.

## Validation commands and evidence

Use the isolated worktree and private temporary caches/test roots:

- Focused tests: `PYTHONPATH=src python3 -m unittest discover -s tests -p
  'test_subagent_tabs.py' -v`, likewise each owned test module. Exercise real
  subprocess locks with watchdog timeouts for create/create, create/close,
  nested observers and interrupted claims; never rely only on stub method calls.
- Integrated suite: `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
- Syntax: `PYTHONPYCACHEPREFIX=<private-tmp>/pycache python3 -m compileall -q
  src tests`; `sh -n bin/harness-herdr-hooks`;
  `node --check integrations/opencode/plugin.js`;
  `python3 -m json.tool integrations/codex/hooks.json`.
- Isolated HOME/CODEX_HOME/XDG install/status/uninstall regression through the
  existing public entrypoint for both harnesses, preserving unrelated config
  preimages and fixture credentials absent. Do not mutate real profiles here.
- Run existing configured quality checks if present on the refreshed base.
  Research base has no `.github` workflow or configured Ruff file; do not add
  a new CI framework or claim hosted CI passed. Report any actually existing
  branch checks after delivery, separating infrastructure failures from tests.
- Parent runs `git diff --check`, inspects the entire staged diff, verifies no
  predecessor changes, no unrelated untracked additions and no private content.

### Bounded native qualification and effects

PLAN approval followed by fresh implement invocation authorizes harmless
qualification in isolated named Herdr test workspace(s), for both supported
harnesses, preserving all existing conversations/panes. Qualify actual CLI,
backend, protocol and selected profiles first. Use at most two test main
sessions and four native subagent tasks per harness to demonstrate separate
root grouping, siblings and a nested child. Each prompt requests only a bounded
wait (up to 30 seconds) and a fixed short reply; no product task, file change,
network action, model/permission change or copied credentials. Use an available
supported native subagent creation path, not a transcript or replacement task
to simulate attachment. Record only exact session/turn/backend/pane/tab IDs and
focus/title metadata to prove attachment added no prompt or inference turn.

Parent coordinates mutations and explains exact installer/owned profile effects
before any required relink through the public installer. Only selected Codex
and OpenCode test profiles may be updated; preserve unrelated entries and check
for another active installed-source owner before relinking. No shared daemon
restart, trust bypass, socket-mode change or automatic restart of active work.
A user-owned reload/trust step, unavailable native spawn capability, missing
credentials or unresolved profile ownership blocks that evidence while safe
source/review/docs and DRAFT delivery continue.

Observe automatic unfocused tab/first-pane attachment, main placement, two-root
separation, nested sharing, main rename, pane rename, completion distinction
and empty-tab removal. Test manual closure and new-work recreation only on
these exact test-owned displays after confirmed task completion; preserve
OpenCode/independent retention until explicitly closing those test panes.
Never close unrelated/occupied tabs or kill backends to force emptiness. Use
controlled fixtures for hostile identities, foreign panes and destructive race
conditions; a snapshot/close race must also be excluded by qualified transport
semantics, not only passing tests. Remove only proven test-owned resources when
safe, retaining running/unknown work and installed-source references.

Native gaps remain explicit DRAFT criteria. Neither old predecessor runtime
gaps nor macOS qualification are silently certified by these new checks;
unrelated predecessor remediation is excluded. Any newly broken preserved
behavior is an HHH-005 regression to correct.

## Requirement-to-delivery trace

AC1–AC6 below refer in order to the six deterministic acceptance bullets in
the approved SPEC. Native qualification and documentation/evidence clauses
are separately mapped; all numbered requirements retain their SPEC numbers.

| SPEC requirement / criterion | Units and paths | Required evidence |
| --- | --- | --- |
| 1–2; AC1–AC2: lazy correct unfocused tab/first and later panes | U10/U30, herdr/tabs/attach/coordinator | Strict response fixtures, initial pane reuse, cwd/focus checks, real both-harness attachment and unchanged native turn metadata. |
| 3–4; AC1/AC5: main/nested identity, isolation, single tab | U10/U20/U30, model/state/tabs/adapters/cli | Full-context keys, bounded roots/cycles, independent-tree boundary, multiprocess races, two roots per harness, nested live grouping. |
| 5–6; AC3: safe dynamic names and collisions | U10/U20/U30, tabs/herdr/adapters/coordinator | Missing/empty/late/renamed root metadata, child rename isolation, control/length fixtures; cross-root concurrent prefixes, identical full IDs across contexts, reservation recovery/exhaustion and native title updates. |
| 7; AC4: owned-only empty cleanup | U10/U30, tabs/state/attach/coordinator | Qualified last-pane removal or atomic occupied refusal; bootstrap failure, user/retained panes, concurrent child/cleanup and auto-removal checks. |
| 8–9; AC5: suppression, stale/unknown claims and recovery | U10/U30, state/tabs/coordinator/cli | Interrupted creation, persisted claims, duplicate/manual closure/new generation, server/ID replacement and no title-only recreation. |
| 10; AC6: legacy and manual work preserved | U10/U30, model/state/attach/coordinator | Legacy record fixtures and existing ownership suite; moved/foreign panes never migrated or adopted. |
| 11; AC5/AC6: parent exit/outside Herdr | U10/U20/U30, tabs/adapters/coordinator/cli | Parent proof revoked, occupied work retained, independent empty proof or bounded failure; no outside-Herdr state/tab mutation. |
| 12; AC4/AC6: harness/independent lifetime preserved | U20/U30/U60, adapters/coordinator, existing lifecycle/launch tests | Codex owned completion, retained OpenCode and independent sessions, future own subagent trees; static and native evidence distinguished. |
| 13; exclusions and predecessor preservation | U00/U40/U60/U80, full integrated boundary | No repeated inference, trust/config/private-state/operator regressions, no unrelated artifact/source/Git/runtime effects. |
| Native qualification section | U00/U60 | Actual Linux/WSL protocol/CLI/backend versions, selected profiles, both-harness evidence above or named DRAFT blockers; no source-only runtime claims. |
| Documentation and evidence limits | U70/U80, seven named docs plus approved pair | Accurate new/preserved behavior, fallback/lifetime/recovery and source-vs-native results; final diff and artifact verification. |

## Checkpoints, Definition of Done and stops

Parent reports each reached checkpoint as sequential `Checkpoint XX`, completed
work, next ready obligation, and verified commit/branch/push or explicit not
committed/not pushed. Unit/review handoffs, corrections and partial commits are
intermediate progress, never continuation gates. Continue through the remaining
authorized lifecycle unless explicitly paused or concretely blocked.

Definition of Done: all SPEC requirements and acceptance/native/documentation
criteria evidenced, reviews/findings/corrections complete, final QA accepted,
documentation accurate, approved pair and accepted source delivered with verified
commit/upstream/remote SHA, unchanged unrelated work/predecessors, and safe transfer
restoration/installed-source retention. Otherwise terminal disposition is blocked
DRAFT with exact unmet criteria and verified safe branch delivery where possible.

Genuine stops: changed/unverified approvals; unsafe worktree/base/ownership;
unresolved protocol acknowledgement/atomic-empty capability; incompatible native
backend; unsafe/ambiguous main identity; missing safe native spawn/title/attach
capability or required qualification; missing trust/reload/credentials; denied
authorized effect; changed delivery destination; required check failure.
Complete independent safe work first. A blocker never permits silently dropping
criteria, moving unrelated sessions, installing dependencies or changing Herdr.

## Planning assurance

- Independent reviewer unit `HHH005-readiness` reviewed the complete draft
  SHA-256 `60fd8267b4421702be26708d02ff930d11bc7561ad5e07c4d1c97548656989a1`
  against the approved SPEC digest above. Coverage included R1–R13, AC1–AC6,
  native and documentation criteria, root/destination authority, grouping,
  recovery/cleanup, ownership, sequencing, delivery, assurance and live effects.
- Findings: high, root-only naming arbitration could race across main sessions;
  medium, equal full session IDs in different contexts needed a deterministic
  display-collision rule. Design items 2/3/5 and the naming trace now require
  workspace-scoped private reservations, ordered operation locks, current-root
  prefix allocation, uncertain-outcome retention and bounded exhaustion failure.
  Neither correction changes the approved SPEC naming pattern or full-context
  identity, and no predecessor artifact was edited.
- Unit `HHH005-readiness-correction` verified PLAN SHA-256
  `060d1d3f003efd171d54a38d72d3e0579c47145e0e8a8bc907d37af1145533fe` with the
  unchanged approved SPEC digest, found both issues disposed, and returned no
  remaining findings. Parent verified JSON identities/status, hashes, coverage
  and corrected sections. This section records advisory evidence, not approval
  or native runtime results. Architect assurance remains inapplicable for the
  single technical capability as assessed above.

## Approval

Approved on 2026-11-19 by the user's explicit response "approve" to the complete
HHH-005 PLAN approval question following independent readiness review.
Reviewed Proposed file SHA-256:
`a3b35ca19fc69cab38ee19612c12638344bb64f964aceb727a9ade5ef3789f17`.
Final reviewer unit `HHH005-readiness-final` directly reviewed that complete
revision against the approved SPEC, confirmed R1–R13, AC1–AC6, native,
documentation, assurance and delivery coverage, and returned no findings.
Approval covers the complete PLAN, including isolated execution, bounded
qualification, assurance and branch commit/push. Implementation requires a new
assistant conversation/session invoking implement with this approved pair;
no implementation or delivery has occurred in this planning conversation.

## Amendment HHH-005-PLAN-A1 — 2026-11-19

### Preceding effective revision and reason

The preceding effective revision is the complete originally approved PLAN,
SHA-256 `b48bf095982a0adfdfb4900ee2ddff074f08575860029553051e142c62eff0ec`.
The SPEC remains unchanged at its originally approved SHA-256
`379efe75181c91d8a8349c31986223fb55519a4c54464ebc45214bdb3b14a8b4`;
no SPEC amendment is needed because cross-profile and cross-harness workspace
coordination is already required behavior.

A deterministic implementation check constructed Codex and OpenCode managers
with different integration state roots but the same server/workspace and main
display identity. Both reserved `Subagents: Same title [abcdefgh]`: the
workspace operation locks and label registries were physically separate.
This contradicts design items 2/3/5 and SPEC requirements 3–5.

### Effective implementation delta

| Reference | Before | After | Reason |
| --- | --- | --- | --- |
| Design 2/3, workspace coordination location | Workspace namespace beneath each invoking integration state root. | Use one canonical private workspace StateStore beneath the current OS account's home directory, `.local/state`, selected through the OS UID account database rather than inherited HOME/XDG/profile variables. Continue using the existing `harness-herdr-hooks/tabs-workspace-<server/workspace digest>` namespace and private StateStore safeguards. Root-specific tab claims, bindings and lifecycle state stay in their selected integration state roots. | Different profile state roots must contend on the same workspace operation lock and complete-label registry. |
| Design 2/3, failure boundary | No explicit canonical-anchor admission rule. | Reject an unavailable, symlinked or unsafe canonical state anchor under existing StateStore checks. Never fall back to a per-profile workspace lock or registry. Initialize it only on the already verified Herdr runtime path. | A fallback would silently restore the reproduced race. |
| U10 completion / validation | Tests primarily share an integration state root. | Add bounded U10e correction before remaining U30 integration and assurance. Test different integration roots for both harnesses, identical titles/full IDs, distinct full contexts, and real subprocess contention on the same workspace operation lock. Test fixtures inject a private coordination anchor through a private test seam; no public CLI/environment override or real-profile test writes. Update existing manager fixtures to use that seam. | Prove the actual cross-profile boundary while keeping tests isolated. |
| U70 documentation | Private state described without a workspace-wide anchor choice. | Document the canonical workspace registry versus profile-specific root/binding state, fail-closed anchor diagnostics, and the distinction between source tests and native evidence. | Make the delivered state locations and recovery boundary explicit. |

No public commands, event schemas, configuration/trust settings, dependencies,
native backend selection, delivery branch/base/worktree, Git authority, or
native qualification criteria change. No global configuration is edited.
The canonical files are integration-owned private application state, not an
agent-coordination lifecycle registry. Existing root claims and binding formats
remain private and rooted at their selected integration state locations.

### Requirement-to-delivery trace

| SPEC criteria | Delivery and paths | Evidence |
| --- | --- | --- |
| R3–R5, R9, R13; AC1/AC3/AC5 | U10e, `tabs.py` and directly affected manager/runtime/hook fixtures; U40 contract/code review; U60 QA; U70 isolation/validation/troubleshooting documentation. | Cross-root both-harness reservation and subprocess lock tests; unchanged root/binding locations and private-mode checks; unsafe-anchor fail-closed test; no real-profile writes. |

All other original trace rows, remaining implementation units, independent
reviews, correction rules, final QA, documentation and branch-only commit/push
remain required. This remains one technical capability with no interacting
business domains; architect planning assurance is not triggered. Independent
plan-readiness review of this complete effective PLAN is required before U10e.

### Authorization and assurance

Origin: the user's 2026-11-19 fresh-session `implement` request for HHH-005.
The implement skill's active-implementation amendment procedure automatically
authorizes this necessary PLAN-only correction; it does not invoke iterate or
create a user continuation gate. The unchanged approved SPEC remains effective.
Complete effective PLAN authorization is subject to recording the required
independent readiness findings and dispositions below before implementation.

## Amendment HHH-005-PLAN-A2 — 2026-11-19

### Preceding revision and readiness findings

A1 above is a pending assurance candidate, not an approved predecessor delta.
Its complete candidate digest was
`9c79c52a1ad47f0d8f03c07d4742fe4f141c8b816b7726e5e0b5639fc89ebd6a`.
A2 retains A1's complete intended correction and supersedes only its anchor
admission and test details below. The original approved PLAN and unchanged
approved SPEC remain the authorization baseline until this complete effective
revision finishes assurance and its automatic authorization is recorded.

Independent reviewer `HHH005-A1-readiness` inspected that complete candidate
and the unchanged SPEC. It identified two supported findings: high, existing
StateStore checks alone do not reject unsafe intermediate anchor components
or writable anchor parents; medium, an injected test anchor alone does not
prove production account-home resolution ignores inherited HOME/XDG values.
Both findings are addressed by the following explicit replacements.

### Effective delta against A1

| Reference | Before | After | Reason |
| --- | --- | --- | --- |
| A1 anchor admission | Rely on existing StateStore anchor checks. | Resolve an absolute home path from the OS account record for the current UID, rejecting unavailable/invalid account data. Admit the home and `.local/state` path through bounded directory traversal with no-follow directory opens. Reject symlinks and non-directories. The account home, `.local`, and `state` must be owned by the current UID and must not be group/world writable. Existing safe modes need not be 0700 and must not be changed. Missing `.local`/`state` may be created with 0700 only beneath an already admitted owner-controlled parent and then re-opened without following links. Ancestors above the account home must be root- or current-UID-owned and not group/world writable; root-owned sticky temporary ancestors are allowed for isolated account-home fixtures. Reject any other unsafe ancestor or unsupported no-follow capability. Continue existing private StateStore namespace/file safeguards. Never chmod account-home/shared parent directories or fall back to a profile-specific registry. | Make admission safe before creation, without changing unrelated directory metadata. |
| A1 test seam and production resolution | Inject a private coordination anchor in fixtures. | Retain that private test seam and also test the real production resolver with OS account lookup stubbed to a temporary owner-controlled home. Vary inherited HOME/XDG and integration roots and verify the same canonical anchor; reject missing account data, home/`.local`/`state` symlinks, wrong ownership/non-directories and unsafe permission fixtures before writes. Assert all created paths remain within the temporary home. Subprocess contention fixtures share the same private anchor. | Test both the production selection rule and isolated cross-profile coordination, with no real-home writes. |

### Preserved scope, trace and authorization

All remaining A1 mechanics, original approved requirements, delivery topology,
source/native distinction and Definition of Done are preserved. U10e owns this
bounded correction in `tabs.py`, directly affected private test fixtures and a
new anchor-admission test module. The A1 requirement trace remains applicable,
with the additional unsafe-ancestor and production-resolver fixtures above.
Root/binding state remains at each selected integration state root. There is
still no public override, dependency, install, configuration, daemon or native
qualification change. This is one technical capability; architect assurance
is not triggered. Readiness review of the complete effective PLAN remains
mandatory before U10e.

Origin and automatic authorization basis remain the user's 2026-11-19 valid
HHH-005 `implement` invocation and the implement skill's required amendment
procedure. A1 is included in this complete effective candidate, not separately
approved by its earlier header or by the advisory reviewer. The unchanged
SPEC needs no amendment. Parent will record the independent A2 assurance and
complete effective PLAN automatic authorization before source implementation.

### Completed assurance and effective-revision authorization

On 2026-11-19, independent unit `HHH005-A2-readiness` reviewed the complete
effective candidate SHA-256
`ade811a1c1205ad0a2a37a025d19ce977fd7b980f0d838ddf9e1de1e39b47151`
against the unchanged approved SPEC digest. It covered R1–R13, the deterministic
and native criteria, both A1 findings, canonical anchor admission and production
resolver tests, lock/state boundaries, sequencing, documentation and unchanged
delivery authority; it returned no remaining findings. Parent verified the JSON
unit identity, complete status, reviewed digests and semantic coverage. The A1
high/medium findings are disposed by A2's explicit replacements above.

The complete effective PLAN (original plus A1 as refined by A2) is automatically
approved on 2026-11-19 under the originating valid HHH-005 implement request and
the implement skill's required amendment procedure. This approval covers the
complete effective revision, not merely an unapproved delta. Original document
status and historical approval records remain unchanged; the SPEC's original
approval/digest remain unchanged. U10e and the remaining lifecycle now proceed in
this implementation session without an additional user approval or continuation
gate. Code/contract review, QA and final delivery evidence remain outstanding.
