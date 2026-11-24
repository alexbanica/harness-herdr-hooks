# Explicit Codex session launcher for Herdr

Status: Approved

The user approved this specification on 2026-11-24 with “approve”. The reviewed proposed revision had SHA-256 `2d7ccc83b9145f833e368097766cb7ddcea15b4784ad8e3c946180a259f58171`.

## Purpose

When a user asks an agent to open another Codex session in a Herdr pane, one script performs the handoff. For example, “Open a new Codex session here and run `$implement SPEC.md`” opens a sibling pane and submits `$implement SPEC.md` as the new agent’s first user message. The user confirmed first-message delivery on 2026-11-24.

## User-visible behavior

1. Ship one launcher and one short agent instruction mapping explicit requests for a new Codex session in Herdr to a single launcher invocation. Ordinary Codex activity never triggers it.
2. Use the caller’s actual Herdr pane, or a pane the user explicitly selects, as the source. When the caller has one verifiable source, the agent can invoke the launcher without asking for an ID. If the source cannot be established or several panes qualify, ask for the intended source before creating anything. A shared server’s inherited environment, global focus, or matching directory alone cannot identify the caller.
3. Split the source pane once. Open an unfocused sibling in the same Herdr workspace and tab. Start in the requested working directory, defaulting to the caller’s working directory. Use the new pane ID returned by Herdr for every subsequent action.
4. Start one fresh, interactive stock Codex session in that pane. When the user supplies an instruction, submit it verbatim as the first user message, once. Preserve dollar signs, quotes, spaces, line breaks and shell syntax as text. When the user asks only for a new session, leave Codex ready for input. Keep the original conversation and focus intact.
5. Report the destination pane and whether the session started and the message was submitted. Submission completes the handoff. The child’s eventual task result is separate. If startup or submission returns an uncertain result, inspect the acknowledged pane where possible, report what is known, and avoid creating a second pane or resending the message. Report the pane ID even on partial failure when it is known.

## Replacement scope

The shipped product consists of the launcher, its invocation instruction, and the documentation and tests needed for that workflow. Remove the OpenCode integration and the old Codex hook product, including their adapters, installers, PATH shims, observers, automatic placement, lifecycle tracking, and obsolete tests and operator documentation. The launcher uses stock Codex and Herdr. It has no dependency on the client-binding patch from draft PR #7. Existing panes, conversations, user files, and unrelated profile entries must survive the transition. Document how to retire an existing project-managed installation before switching to the launcher.

This supersedes the automatic behavior in the [original hook SPEC](SPEC-harness-herdr-hooks.md) and [PLAN](PLAN-harness-herdr-hooks.md), the [standalone pane SPEC](SPEC-standalone-session-panes-only.md) and [PLAN](PLAN-standalone-session-panes-only.md), and the draft delivery of the [client-binding SPEC](https://github.com/alexbanica/harness-herdr-hooks/blob/babf077/specs/SPEC-codex-client-pane-binding.md) and [PLAN](https://github.com/alexbanica/harness-herdr-hooks/blob/babf077/specs/PLAN-codex-client-pane-binding.md). Preserve those planning records. The existing destination rule carries forward for explicit launches. The earlier operator run demonstrated a same-tab split and stock Codex start. First-message delivery requires separate verification.

## Acceptance

- From a known source, request a new session with a distinctive, multiline instruction containing a literal dollar sign and shell metacharacters. Verify one new pane in the source workspace and tab, preserved focus, the requested working directory, and exactly one first user message with the supplied text in the new conversation. Verify no message arrived in the original conversation.
- Request a session without an instruction. Verify it opens ready for input with no initial user message.
- Exercise the shared-server case with an inherited pane marker from a different workspace. Verify the launcher uses the established source or requests an explicit selection before splitting. With an explicit selection, verify placement in that pane’s tab.
- Exercise a startup or submission timeout after the split. Verify the response identifies the known pane, distinguishes confirmed actions from uncertain ones, and produces no duplicate pane, session, or message.
- Verify the documented agent invocation works with stock Codex and Herdr without installing event hooks. Active code, instructions, tests, and setup documentation should describe only this launcher.
