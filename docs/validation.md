# Validation and support status

**Delivery status: DRAFT / experimental; Definition of Done is not met.** This
table separates isolated source/operator and native-API evidence from unmet
native acceptance. Passing the former does not establish full support.

| Area | Evidence obtained | Qualification limit |
| --- | --- | --- |
| Source/static | Python compilation, CLI help, JavaScript syntax, and JSON parsing passed. Bounded input, conflict, path, title-sanitization, context, observer, attachment-cleanup, and state behavior were checked with controlled fixtures. | Static/controlled checks do not prove a native harness-created child can be attached end to end. |
| Operator install | Both actual public CLI installers passed isolated install/status/reinstall/relink/moved-checkout/uninstall checks. Foreign hooks, group metadata, plugins, second profiles, and native hook modes were preserved. Unmanaged identical conflicts were rejected. Quoted checkout paths (including spaces, quotes, `$`, and backticks) ran safely. Missing status roots caused no creation; outside-Herdr execution returned before input/state access. | Isolated synthetic profiles are not user installation or native trust evidence. |
| Herdr API and controlled lifecycle fixtures | The isolated Herdr 0.9.5 server returned protocol-22 snapshots and process metadata; a sole foreground Bash PID passed the shell-readiness check. Separate controlled fixtures covered parent/title/fallback handling, sanitization, revocation, startup baselines, pending creation, and pane retention/cleanup. | The lifecycle fixtures used controlled Herdr metadata. They do not establish native child placement, concurrency, manual-close, profile/server races, or platform acceptance. |
| OpenCode native API | Isolated OpenCode 1.19.5 loopback API check created a synthetic parent/child metadata relation without prompts. Provider ancestor normalization and idle-skip behavior passed against a controlled Herdr stub. | No authorized real native child, added-turn comparison, complete profile/backend matrix, or full concurrency evidence. Fixture API evidence is not native child-attachment acceptance. |
| Codex native API | Isolated Codex CLI 0.169.0 app-server WebSocket upgrade, selected home/incarnation, loaded thread list, and ancestor/source-kind checks passed with zero threads/model turns created. An initial WebSocket upgrade defect was corrected and rechecked. | No authorized native child was attached and no additional-turn acceptance was demonstrated. This is not end-to-end support evidence. |
| Credentials/accounts | The OpenCode fixture had no model configured. The isolated Codex account query, without token refresh, returned no account and required OpenAI authentication. | No real credentials were copied or used. User-authorized native child creation/attachment and provider acceptance remain outstanding. |

The final documented `install`, `status`, and `uninstall` commands were also
rerun with private configuration/home/XDG roots after documentation
synchronization. Explicit profile selection and uninstall from a trusted
checkout after the old checkout was removed passed. Relative documentation
links were checked.

## Required acceptance still unmet

- Qualify native Codex hook and OpenCode plugin feature/trust procedures and
  user-owned reload behavior. Do not bypass native trust controls; no automatic
  server restart is part of the flow.
- Demonstrate authorized native children for both harnesses attaching to the
  original backend/session, with no added prompt/model turn, no replacement
  runtime, and exact same-tab/unfocused placement. Codex requires an explicitly
  selected native socket; OpenCode requires its actual bound local API. The
  documented attach command forms are source-qualified references only, not
  live-child results.
- Complete real profile/backend isolation, cross-harness and same-harness
  collision cases, full concurrency/restart/manual-close and attachment race
  coverage.
- Run equivalent runtime evidence on macOS. No macOS host was available.

No user instruction excluded these criteria. They remain required before
acceptance. Source implementation and the passed isolated checks do not change
this DRAFT status. To resume qualification, provide authorized native child
creation/attachment contexts for each harness, allow their ordinary trust and
reload procedure to be exercised, and provide a supported macOS host or
explicitly revise the platform acceptance scope through the approved workflow.
