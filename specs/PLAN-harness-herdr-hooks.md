# PLAN: Harness Herdr Hooks

Status: Approved

- ID: HHH-001-PLAN
- Date: 2026-11-13
- Approved SPEC: `specs/SPEC-harness-herdr-hooks.md`, complete effective revision
  HHH-001 + HHH-001-A1 + HHH-001-A2, explicitly approved on 2026-11-13.
- Approved SPEC file SHA-256:
  `f53516e28046423ef93d9ef5ba681c204dd89e58ce2dadcc2722475ec9145a05`.
- PLAN approval: Approved on 2026-11-13 by the user's explicit response "approve" to the complete PLAN approval question, after independent readiness review.
- Execution entry: A new assistant conversation invoking `implement` with this
  PLAN and the approved effective SPEC. This planning session does not implement.

## Outcome and boundaries

Deliver `alexbanica/harness-herdr-hooks` as a separate public GitHub repository:
Codex hooks, an OpenCode plugin, an automatically started helper, per-harness
installation/uninstallation, and user documentation. Only newly observed,
running, verifiably parent-linked and attachable children get unfocused panes in
the parent's existing Herdr tab. Names synchronize one way. Finished children and
parents outside Herdr are skipped as specified. Existing successfully attached
panes remain after completion. Do not repeat inference or substitute a history
viewer when attachment is unavailable.

No RpiInfrastructure edits, runtime migration, worktree allocation for child
agents, registry publication, release tags, main merge, or installation into the
user's active harness configuration is authorized by this plan. Isolated QA
installation is included below. Preserve all prior SPEC content and approval
history. Implementation-required amendments follow the active implement rules.

## Evidence, compatibility, and no-research boundary

The planning directory contains the approved SPEC and this PLAN only, with no Git
repository yet. RpiInfrastructure remains clean on its own `main` branch. The
authenticated GitHub connector returned Not Found for the intended new repository;
this is evidence from planning, not permission to reuse any repository later found
under that name. Current host: Linux, Python 3.12.3, Node 24.21.0, Codex CLI
0.169.0, and Herdr 0.9.5/protocol 22. OpenCode and Bun are not installed locally.

Freeze these source/interface patterns:

- Codex release `rust-v0.169.0`: the generated SessionStart/SubagentStart command
  input schemas and app-server `thread_processor.rs` named in the SPEC/workstream.
  A child-start hook supplies child identity, not parent ID. Use the running
  backend's `thread/list` parent/ancestor filters for ancestry and
  `thread/loaded/list` plus native status for running/attachable state.
- Codex `app-server proxy --sock PATH` proxies an existing control socket through
  stdio; it does not justify starting a server. `codex resume --remote
  unix://PATH CHILD_ID`, with no prompt or permission/model flags, targets that
  same running server. Version-qualified runtime proof is still required.
- OpenCode `v1.19.5`, commit
  `810c0eba1a7348036f8bdf61e6632d0c36c6876c`: released `plugins.mdx`, plugin
  input/event types, and `cli/cmd/attach.ts`/`tui.ts`. Use its released
  `event: async ({ event }) => { ... }` callback and existing-session command
  `opencode attach URL --session ID --mini`, never an assumed newer CLI/API.
- Herdr 0.9.5 bundled `herdr api schema --json`: protocol 22 request/response
  envelopes, `session.snapshot`, pane/session metadata and process information,
  `pane.split`, `pane.send_text`, `pane.send_keys`, `pane.rename`, and `pane.close`.
  `pane.split` can target a pane with `focus: false`; native session metadata
  includes harness/source, session ID, optional session path, and resume argv.

Implementation may inspect these named patterns and regenerate installed API
schemas to verify the qualified interfaces; it must not reopen product research,
choose a different release, or silently substitute a different attachment model.
If a required interface or identity cannot be established, preserve completed
independent work and use the amendment/blocker rules rather than inventing fields.

## Architecture and deterministic choices

Use Python 3.11+ standard library for the executable, adapters, private state,
Codex stdio proxy, and local Herdr socket client. Use a small JavaScript ES-module
OpenCode plugin using the qualified native plugin callback and client. No Python
runtime package installation or standalone Node service is required. The OpenCode
runtime loads its plugin using its own supported loader.

Public commands, all under `bin/harness-herdr-hooks`:

```text
install codex|opencode [--config-dir PATH]
status codex|opencode [--config-dir PATH]
uninstall codex|opencode [--config-dir PATH]
```

Installation means link a managed entrypoint/plugin to this clone. A moved clone
is diagnosed by `status`; upgrading means update the clone and rerun installation.
There is no implicit both-harness operation, global package install, or active
server restart. Resolve omitted config directories through the selected harness's
native settings; an explicit path overrides only that harness's configuration
destination, not its backend or database. Report any native enable/trust/restart
steps; do not bypass trust or silently modify unrelated TOML/configuration.

Internal commands `codex-hook`, `opencode-event`, `observe`, and `attach` are only
integration entrypoints. They accept bounded versioned JSON or an opaque binding
ID; they do not accept prompts. The plugin-to-helper envelope contains schema
version, fixed harness discriminator, effective config/state and backend identity,
minimal session/ancestry/status/title/cwd metadata, and event kind. The native
Codex payload is parsed by its own adapter, not treated as this common envelope.
Do not carry transcript text, credentials, or arbitrary environment maps.

### Identity, lifecycle, and containment

1. An identity contains harness, effective profile/config and data/state roots,
   actual backend instance, and session ID. A separate verified Herdr binding
   contains server identity, workspace/tab/pane IDs, and original parent chain.
   Never use title, cwd, or session ID alone as global authority.
2. Native session metadata and the live backend must agree with the parent pane
   before acting. Match canonical session paths and backend/resume identity where
   available; stale environment variables are only hints. If cross-instance
   identity is ambiguous, fail closed. Do not scan foreign conversation stores.
3. A parent-start hook registers a proven parent and starts one scoped observer.
   A child-start event may wake it but is not ancestry proof. The Codex observer
   obtains descendants from the already running backend; OpenCode's native
   plugin forwards qualified events/metadata from its existing backend.
4. Initial observation records a baseline, so old sessions are not backfilled.
   New not-yet-running children may wait within the bounded startup window;
   running children become candidates, terminal children are skipped. Revalidate
   liveness and exact parent binding immediately before creating a pane.
5. Own state lives under the effective user-local state directory in a dedicated
   `harness-herdr-hooks` subtree, with harness/context namespaces, directory mode
   0700 and file mode 0600. Use `fcntl` locks and atomic replacement. Refuse
   unsafe ownership/symlink state. Store association/suppression metadata only.
6. Choose right-hand splits and preserve focus. If the terminal cannot accept a
   split, leave the parent untouched and report a bounded diagnostic; do not
   create a new tab/workspace or move other panes.
7. Start the attachment wrapper only in the newly created, verified shell-ready
   pane, using a shell-quoted absolute entrypoint and opaque binding ID through
   the native pane text/key API. Require a supported POSIX-compatible shell and
   do not type into an agent prompt. The wrapper revalidates its own new pane and
   backend and then `exec`s the selected native attachment argv with a sanitized
   environment. Titles never enter commands; no `agent.prompt` operation is used.
8. Build the child client environment from required OS/terminal values and the
   selected harness's verified profile/backend context. Remove foreign harness
   overrides, stale session IDs, and unrelated provider credentials. Use the new
   pane's Herdr markers, not copied parent markers. Preserve HOME and native
   sandbox/auth choices; do not create a second server for isolation.
9. Serialize candidate claim, split, attach confirmation, and ownership recording.
   A successfully displayed child is attached, not newly started. On an attach
   failure/completion race, close only the integration's unclaimed new pane if it
   still contains its own failed launch and no unrelated process/user activity.
   If cleanup cannot be proven safe, retain the pane and report the unmet race
   criterion as a gap; never kill unrelated work to satisfy appearance.
10. Reconcile owned panes on restart, suppress manually closed children, avoid
    recursion from display-client hook events, and retain completed attached panes.
    Update owned pane titles while their parent binding remains valid. Stop a
    scoped helper when that parent context disappears, without stopping agents.

Reversible defaults: one-second observation/coalescing interval, five-second
backend/API operation timeout, and at most three bounded startup retry attempts.
Hooks queue work and return promptly rather than wait for pane readiness. Retry
does not create multiple panes; transport failure does not mark a child finished.
Unrelated harnesses/profiles have separate locks, failures, and cleanup authority.

## Workspace, base, branch, and publication

This is a new-repository bootstrap, not a branch off RpiInfrastructure. Approval
of this PLAN selects the following explicit bootstrap/location policy:

1. Parent verifies the origin checkout (the parent of this PLAN's `specs/`
   directory) contains only the accepted planning artifacts, has no unexpected
   Git state, and verifies
   the public repository name is still absent/available. Preserve any unexpected
   work and stop on a collision; do not adopt/reset an existing repository.
2. In that directory, parent initializes local `main` and commits only the
   byte-verified approved SPEC/PLAN as `docs: record approved harness hook design`.
   This is the genesis base, not implemented source or a pushed release. Record
   its actual commit SHA and artifact digests before source edits. There is no
   preceding upstream to fetch; this explicit new-repository bootstrap is the
   only initial-base exception. Do not invent a remote SHA.
3. Parent creates a clean detached worktree at
   `/tmp/agent-worktrees/harness-herdr-hooks/initial-hooks` from that exact local
   genesis commit and verifies HEAD equality. Source ownership is under this
   worktree. Keep the original planning checkout's `main` at the genesis base.
   Before the first source/checkpoint commit, require local/remote branch
   `feat/initial-hooks` absent and unattached, then create it at detached HEAD.
4. Once source/assurance are reviewable, parent creates the public repository
   `alexbanica/harness-herdr-hooks` without a generated README/license commit,
   using a capable authenticated GitHub tool or `gh repo create`. Do not extract
   connector credentials to make another client work. Set only this new
   repository's origin to `git@github.com:alexbanica/harness-herdr-hooks.git`.
5. Push the approved-artifact genesis `main` and exact accepted delivery branch
   `feat/initial-hooks`, without force. Create and verify a PR with base `main`,
   head `feat/initial-hooks`, and exact published head SHA. Do not merge the PR.
   Set a concise public description and topics specified by the SPEC. No registry
   publication, tags, license grant, or live installation is included.
6. Verify both remote SHAs, delivery upstream, accepted artifacts, PR base/head,
   and clean source worktree. Detach the worktree at the verified delivery commit;
   retain its path for inspection. Original approved artifacts remain at their
   source location; they were not temporary transferred changes to discard.

On continuation after a verified bootstrap/publication, fetch the same delivery
branch and verify checkpoint ancestry; do not rerun genesis initialization or
replace it with a newly created base. If `origin/main` or the remote delivery
branch now exists unexpectedly before the initial bootstrap, stop and reconcile
through amendment rather than overwrite it. Parent alone owns Git, repository
creation, PR mutation, and final acceptance. Children never commit, push, create
worktrees, merge, or deploy.

## Delivery units and exclusive ownership

All assignments carry effective artifact hashes, prerequisites, exact exclusive
paths, bounded commands/effects, and a stable `unit_id`. Specialists return the
required single-JSON handoff, not approval. Each launched assignment has a
five-minute hard limit and a three-minute target. Split large units into disjoint
bounded assignments; reconcile an active/uncertain assignment before reassignment.
Use no more than three children simultaneously, and at most one explorer or
readiness reviewer. Parent serializes shared integration, environments, and checks.

| Unit | Ownership and role | Prerequisites | Completion and validation |
| --- | --- | --- | --- |
| U00 | Parent: approved artifacts, repository/bootstrap/worktree, runtime preflight | Approved complete SPEC and PLAN; fresh implement session | Verify hashes, clean topology, genesis base, versions/protocols, authentication capability, and isolated QA prerequisites. No source or live-user installation. |
| U10 | Developer: `src/harness_herdr_hooks/__init__.py`, `model.py`, `state.py`, `coordinator.py` | U00 | Typed normalized context/session outcomes, scoped private state/locks, baseline, lifecycle, claims, suppression, retries, and no-op path. Static Python syntax/import checks; controlled temporary-state/operator inspections for ownership and collisions. |
| U11 | Developer: `src/harness_herdr_hooks/herdr.py`, `environment.py`, `attach.py` | U10 interface handoff | Protocol-22 transport, verified parent/pane routing, unfocused splits, shell-ready wrapper launch, safe argv/environment, attach acknowledgement, exact owned-pane cleanup. Static checks and isolated Herdr smoke. |
| U20 | Developer: `src/harness_herdr_hooks/adapters/__init__.py`, `adapters/codex.py`, `integrations/codex/hooks.json` | U10; integrate after U11 | Exact 0.169 hook input, existing-socket observer, parent/ancestor queries and liveness, native same-runtime attachment argv, one-way naming, display-client recursion guard. JSON parse/static checks and isolated native Codex smoke. |
| U30 | Developer: `src/harness_herdr_hooks/adapters/opencode.py`, `integrations/opencode/plugin.js`, `integrations/opencode/package.json` | U10; integrate after U11 | 1.19.5 native plugin events, exact server/session/parent metadata, bounded bridge handoff, same-server attach argv, lifecycle/naming and independent failure scope. ES-module syntax check and isolated OpenCode smoke. |
| U40 | Developer: `bin/harness-herdr-hooks`, `src/harness_herdr_hooks/__main__.py`, `cli.py`, `install.py`, `.gitignore`; initial `README.md` and `docs/` files listed in U60 | U11, U20, U30 integrated | Public/internal command dispatch; per-harness/profile managed links and manifest, JSON hook merge, owned-only removal, conflict/idempotence/status checks; draft actual install/usage instructions. Help/static checks and disposable-profile install/reinstall/move/uninstall operator checks. Release documentation ownership before U60. |
| U50 | Parent integration; independent code-reviewer, contract-reviewer, then qa-agent | U10–U40 complete and development checks recorded | Freeze whole integrated diff and criteria; full independent review wave; consolidate accepted corrections through bounded developers; rerun affected checks, final QA, and disposition all criteria/gaps. No source ownership for reviewers/QA. |
| U60 | Documentation-writer: `README.md`, `docs/install-codex.md`, `docs/install-opencode.md`, `docs/isolation.md`, `docs/contracts.md`, `docs/troubleshooting.md`, `docs/validation.md` | U50 final QA and released U40 documentation ownership | Synchronize the final behavior, executable installation instructions, trust steps, support matrix, isolation, recovery, and evidence/limitations. Stop on semantic mismatch. Parent checks commands/links and final source diff; record exercised commands as byte-equivalent or run scoped isolated operator checks of changed final commands before delivery. |
| U70 | Parent: accepted staging, commit/push/public repo/PR and verification | U60, required checks and Definition of Done assessment | Deliver verified source branch and PR or truthfully marked blocked DRAFT. Report actual SHAs, remote refs, PR, source/worktree state, missing criteria, and remaining obligations. |

U20 and U30 can run concurrently once U10 interfaces are frozen; U11 can proceed
alongside their source work within capacity. Do not let either provider change
the other's adapter or identity state. U40 and all mutating integration/QA work
are serialized. No workers edit the approved SPEC or main-owned PLAN.

## Validation and isolated execution

There is no deterministic business/domain logic in this operational integration.
Test-first and maintained unit/integration/configuration/workflow test suites are
not applicable. Do not add a test suite or test-specific CI. Use these applicable
static, structural, smoke, and operator checks instead, recording exact results:

- Python syntax/import checks, e.g. `python3 -m compileall -q src`; direct syntax
  compilation of the executable; CLI `--help`/`status` without unintended state
  writes. Keep generated bytecode out of source control.
- `node --input-type=module --check < integrations/opencode/plugin.js` and JSON
  parsing of shipped hook/plugin metadata; native loader validation separately.
- `git diff --check`, accepted-file/credential/runtime-state inspection, and
  shell-safe argument/title/control-character review. Native hook trust must be
  explicitly exercised, never bypassed by dangerous flags.
- Installer operator checks use fresh directories under `/tmp/hhh-qa/`, with
  all native config/data/state roots independently scoped and explicit selected
  harnesses. Seed only synthetic nonsecret fragments to verify preservation and
  conflict handling. Never point disposable checks at real default destinations.
- Use a separately named Herdr QA context and disposable source directory; do
  not take over the user's current tab or change active integrations. Native
  child sessions created for the smoke must themselves create children in their
  original backend, not simulate success by writing final pane state.
- OpenCode 1.19.5 may be downloaded explicitly into a private `/tmp/hhh-qa/`
  tool directory from its official release for this isolated QA only, verifying
  the published artifact identity/checksum. No system package installation or
  auto-install in normal hooks is allowed. An unavailable or unverifiable artifact
  is an external prerequisite gap, not permission to substitute another release.
- Use only native, already authorized authentication/provider configuration in
  its owning context, or an explicitly nonsecret local fixture backend. Do not
  copy real auth between profiles, print tokens, bypass trust, or change approval
  policies to make a smoke pass. If native authentication/trust or a suitable
  isolated backend is unavailable, record the affected native checks as blocked
  and continue safe independent work. Fixture-only evidence does not establish
  real native attachment without exercising the actual harness.

Final QA executes the SPEC's original eight acceptance bullets and A1's five
additional bullets. Particular required outcomes:

1. Both native helper and separate-task/fork creation paths: running eligible
   children attach once, ID/backend preserved, same tab/no focus, nested ancestry
   correct. Baseline excludes old sessions; hook startup does not backfill.
2. Before/after native turn and session metadata demonstrate that attaching adds
   no prompt, model turn, replacement session, or backend. Verify exact native
   session and server identities in the pane and coordinator record.
3. Title generation/rename, duplicate titles, control characters, two harnesses,
   two same-harness profiles/backends, repeated events, restart adoption, and
   manual close suppression remain isolated. Controlled metadata cases exercise
   collisions without modifying real IDs or conversation stores.
4. Parent outside Herdr is a silent no-op, including stale Herdr markers and a
   different active Herdr context. Ambiguous identity, server replacement, and
   foreign harness variables cause no unrelated pane changes.
5. Already finished children open no pane; delayed creation and completion races
   are observed. Successful panes survive later completion and retain correct
   naming. Failed-new-pane cleanup never touches unrelated user activity.
6. Both installers follow the draft documentation in a clean clone/profile;
   single-harness install works with the other absent. Reinstall, update/relink,
   moved-clone status, conflict rejection and uninstall preserve foreign entries,
   native trust/settings, alternate profiles, and the other observer.
7. Root/pane exit and one-provider failure/uninstall stop only owned helpers;
   correct state permissions/locks prevent cross-context cleanup. No credentials,
   transcripts, or real-user runtime paths appear in published artifacts.

Perform Linux native validation in the available environment. macOS support needs
equivalent operator evidence on a separately authorized macOS host; no such host
is assumed here. Static POSIX/path/environment review is useful but is not macOS
runtime proof. Missing required per-harness/platform/isolation evidence remains an
explicit DRAFT acceptance gap unless the user later excludes that named criterion.
No hosted CI or deployment evidence is asserted by this plan.

## Requirement-to-delivery trace

R1–R32 refer to numbered effective SPEC requirements. A1–A8 refer, in order, to
the original Acceptance and validation bullets. X1–X5 refer to A1 amendment's
Additional acceptance and validation bullets. Other anchors name SPEC sections.

| SPEC IDs / exact anchor | Units and owned delivery | Validation / terminal evidence |
| --- | --- | --- |
| Purpose/authority; public separate repository; exclusions | U00/U70, `specs/`, new origin and PR | Correct owner/name/visibility, genesis and source refs, PR base/head; RpiInfrastructure unchanged; no merge/deploy/registry/tag. |
| Scope/definitions; HHH-001-A2 release/interface delta | U20/U30/U40, provider adapters/plugin and installers | Exact version/schema checks and native same-ID/server attachment; support matrix reflects actual qualified paths. |
| R1, R4, R18; HHH-001-A2 hook/plugin callback | U10/U20/U30/U40 | Automatic observer registration, new-session baseline, native creation/fork paths, recursion suppression and helper exit; QA1/7. |
| R2, R3, R5, R27; A1, A4 | U10/U11/U20/U30 | Verified parent/backend binding, no-focus same-tab placement, stale/foreign markers and outside-Herdr no-op; QA1/4. |
| R6, R26; A2, A7 | U10/U11 state/coordinator and provider adapters | Concurrent/repeated events, existing pane adoption, nested ancestry, restart and manual-close suppression; QA1/3. |
| R7, R9; A5 | U10/U11/U20/U30 | Liveness gate, finished-child no-op, pre-attach race cleanup versus post-attach retention; QA5. |
| R8, R10, R29, R32; A6 | U11/U20/U30 environment/attach/adapters | Original backend/session, no submitted prompt/turn, unchanged native permissions/cwd/context; fail-closed unsupported attachment; QA2/4. |
| R11, R12, R13, R14; A3 | U10/U11/U20/U30 | One-way initial/generated/renamed labels, duplicate titles and controls, correct completed-pane updates; QA3/5. |
| R15, R19, R20, R21, R22, R23; A8; X1, X2 | U40/U60 executable/install and per-harness docs | Clean-clone/profile walkthrough, native trust guidance, selective/idempotent registration, conflict/move/update/uninstall ownership checks; QA6. |
| R16, R25, R28, R31; X3, X4 | U10/U11/U20/U30/U40 state/environment/provider boundaries | Composite namespace and roots/backend verification, permissions, foreign environment/state isolation and publication inspection; QA3/4/7. |
| R17, R30; A8; X5 | U10/U11/U20/U30/U40 | Bounded retry/no agent interruption, one-provider failure/uninstall isolation and scoped cleanup; QA4/7. |
| R24; Documentation; HHH-001-A1 documentation acceptance; regression boundaries | U40/U60 README and all listed docs | Verified install commands, exact capability matrix, troubleshooting/isolation/lifecycle; evidence-separated final validation document and final diff. |
| Evidence/compatibility and acceptance evidence boundary | U00/U50/U60/U70 | Record static versus native Linux/macOS results independently; no unsupported full-support claim; explicit unmet-criterion DRAFT report. |

## Assurance, corrections, and documentation

Select **full assurance**: this adds executable hook/plugin configuration and
cross-component event/attachment behavior with profile, credentials, and runtime
isolation effects. Routine eligibility does not apply.

- Code-reviewer: required independent integrated review of all accepted source,
  installers, initial docs, contract surfaces, and requirement/check coverage.
- Contract-reviewer: required for the new executable hook input/exit contract,
  OpenCode plugin-to-helper event envelope and exposed command operations. Check
  producer/consumer agreement, native schema handling, identity semantics, and
  backward/fail-closed behavior against the qualified external interfaces.
- Security-reviewer: not selected. The user requested isolation behavior, not an
  explicit independent security review; full profile alone does not trigger it.
  Code review and QA still cover the specified isolation and safe-execution
  requirements and any supported security findings.
- Final qa-agent and post-QA documentation-writer: required by full assurance.
- Independent plan-readiness-reviewer: mandatory before this PLAN is presented.
- Architect plan review: not triggered. This is one technical integration
  capability, not multiple interacting business domains. Two harness adapters,
  Herdr presentation, installation, and Git delivery are technical components and
  stages, not distinct business domains.

Freeze actual integrated baseline/diff, artifact hashes, dependency/interface
versions, owned paths, check inputs/results and unresolved criteria in each
handoff. Wait for the entire code/contract wave; parent disposes supported
findings, delegates one consolidated correction batch within approved behavior,
and runs affected checks. Then run final QA. Repeat a whole correction/review/QA
cycle only for a confirmed qualifying acceptance/check failure, regression,
contract incompatibility, high/critical security defect, or blocked requested
behavior whose benefit exceeds impact. Speculation does not add cycles. After
the final QA assessment, transfer documentation ownership to U60 once for final
synchronization and inspect resulting semantics/links/commands. For each final
setup or verification command, retain the actual earlier execution inputs/results
and show the final command and environment/path assumptions are byte-equivalent.
If U60 changed a command or its required inputs/paths, parent assigns a bounded
qa-agent operator check of that final command in the isolated selected profile;
documentation inspection alone is insufficient. This is scoped affected
validation, not an automatic repeat of unchanged successful QA. Reconcile delivery
only after the final documented commands have this evidence. An observed failure
uses the existing qualifying-correction rules.

## Definition of Done, stop conditions, and DRAFT recovery

Complete delivery requires all effective SPEC criteria, completed integrated
development/reviews/corrections/QA/docs, qualified attachment and isolation
evidence for both harnesses/platforms in scope, safe topology, no accepted dirty
paths, exact commit/push verification, public repository metadata, verified PR,
and worktree disposition. Do not call a branch push or partial specialist result
completion. No routine continuation approval occurs between these stages.

Stop affected work for missing authority, invalid artifacts, unexpected existing
repository/branch/worktree state, secret exposure risk, a failed identity or
native-attachment contract, unavailable required credentials/trust/tool/platform,
or unavailable publication capability. Complete safe independent work first.
Required SPEC/PLAN amendments during valid implementation use automatic effective
approval and mandatory readiness assurance under implement; new external
authority or missing user information remains a genuine blocker.

On a genuine standstill, retain all work and evidence, reconcile accepted paths,
and where safe publish a Conventional Commit marked DRAFT to the same new
delivery branch and a DRAFT PR, with exact unmet criteria and remaining work.
If public repo creation/push is unavailable, retain the local genesis/main and
source worktree, do not claim publication, and report the exact missing capability.
Resume the same delivery branch/base after reconciliation; never reset/recreate
someone else's work. Ordinary completed delivery uses a Conventional Commit such
as `feat: open agent child sessions in herdr panes`.

Every reached checkpoint reports completed work, next obligations, and verified
commit/push status with exact branch/SHA when available. Final reporting separates
source/static evidence, real runtime acceptance, public Git/PR delivery, and any
omitted/blocked criteria. No real-user hook installation or runtime deployment
is implied by GitHub publication.

## Planning assurance record

- First independent review: `hhh-plan-readiness-v1`, complete read-only review
  against approved effective SPEC SHA-256
  `f53516e28046423ef93d9ef5ba681c204dd89e58ce2dadcc2722475ec9145a05`
  and PLAN draft SHA-256
  `072304a74215a1dffdc2cbe69534c79efedf197fad07ea207d0679c9d97ddfc9`.
- Supported finding 1 (medium): original acceptance count was nine rather than
  eight, creating nonexistent A9. Corrected to A1–A8; scoped helper cleanup maps
  to R17/R30 and actual A8/X5. Also disambiguated acceptance IDs from SPEC
  amendment IDs in the trace.
- Supported finding 2 (medium): final command edits after U60 could escape the
  setup walkthrough evidence. U60/assurance now require byte-equivalent evidence
  reuse or isolated operator checks of the changed final commands and assumptions.
- Corrected-draft confirmation: `hhh-plan-readiness-v2`, status complete,
  no remaining findings, against unchanged approved effective SPEC and corrected
  PLAN draft SHA-256
  `67598bfaf9a28ed614356aca392fa2e7ce0877d3661686243298c6c6969f8cdf`.
  The reviewer verified both dispositions, retained the earlier whole-PLAN
  coverage, and checked the changed trace/documentation verification requirements.
  No runtime, Git, network, session, or pane actions were performed.
- Final post-review change is this factual assurance record only; execution
  semantics are unchanged from the corrected reviewed draft. Both supported
  findings are resolved. Review outcomes are advisory, not user approval or
  implementation evidence.

## Approval record

- Decision: Approved on 2026-11-13 by the user's explicit response "approve"
  to the PLAN approval presentation.
- Reviewed pre-approval PLAN SHA-256:
  `3e2834b701d0f32206071f0ec307d3c4eb685604f6da9a32f95f3978a2ac4546`.
- Approved scope: The complete HHH-001-PLAN, including its bootstrap/worktree/base
  policy, isolated provider adapters and installation, full assurance and
  validation/documentation lifecycle, public repository and source-branch/PR
  delivery, and explicit DRAFT recovery boundaries.
- Paired approved effective SPEC: HHH-001 + HHH-001-A1 + HHH-001-A2, file SHA-256
  `f53516e28046423ef93d9ef5ba681c204dd89e58ce2dadcc2722475ec9145a05`.
- Readiness: hhh-plan-readiness-v1 followed by hhh-plan-readiness-v2; both
  supported findings corrected and no remaining findings at final confirmation.
- Only approval metadata was changed after user review; implementation scope
  and execution semantics are unchanged.
- Execution has not started. Under spec-plan, implementation requires a new
  assistant conversation invoking implement with the exact approved artifact
  paths. No same-session implementation, commit, push, publication, or active
  harness installation was performed by recording this approval.
