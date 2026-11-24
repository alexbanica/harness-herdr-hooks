# SPEC — Bind Codex conversations to their Herdr client panes

Status: Approved

Approved by the user on 2026-11-24 with the response `approve`.
Reviewed proposed revision SHA-256 `db03b3ac66d0dd9f9410b78bea6570f69799d66b73852a82f38945131e9411dc`.

## Problem

When Codex clients in different Herdr spaces share an app-server, a
server-side session report can carry the pane coordinates inherited when the
server started. In the observed test, Codex clients in the harness-herdr-hooks
space had local pane IDs in workspace wF, but the shared server carried
workspace wE and pane wE:p4. The standalone observer verified the resulting
session report in wE and split that tab. Moving the focus or changing the
working directory does not establish a conversation's display location.

## Behavior

- Use a verified association between the exact foreground Codex
  conversation, its displaying client, and that client's current Herdr
  server, workspace, tab and pane. Establish the association on interactive
  startup and refresh it when an in-place resume changes the displayed
  conversation. A previously valid association stops authorizing placement
  when the client switches, disconnects, or the pane moves or closes.
- A shared app-server's inherited pane coordinates, working directory,
  the focused space and the latest session ID are insufficient to establish
  this association. Where a current exact client association cannot be
  verified, record a bounded diagnostic and perform no pane effect.
- A newly created standalone session has no display claim until an existing
  verified display is found or attachment to the exact claimed pane is
  confirmed. Background startup and native subagent events cannot replace
  the parent display association.
- Route standalone creation from a verified originating display to one
  unfocused pane in the same space and tab. If more than one display matches
  and the initiating location cannot be uniquely verified, skip placement.
  Leave all existing panes and tabs intact.

## Prior scope and exclusions

This extends the display-association boundary deliberately excluded by
[SPEC-standalone-session-panes-only.md](SPEC-standalone-session-panes-only.md)
and its [approved PLAN](PLAN-standalone-session-panes-only.md).
Preserve exact child verification, no-added-turn attachment, durable effect
claims and replay handling, unrelated hook registrations, ordinary fresh
interactive routing, and the retirement of native subagent and automatic tab
handling. The change does not introduce a process requirement into standalone
placement. The mechanism for establishing client identity must be supported
and verified before choosing implementation scope or promising compatibility.

## Acceptance

1. Two Codex clients in distinct Herdr spaces share one app-server. A
   creation from the second client attaches the exact child in one new
   unfocused pane in the second client's existing tab, while the primary
   pane keeps the originating conversation. Repeat from the first client.
2. Switch to a different conversation with in-place resume. The old client
   association no longer permits placement. After the new association has
   been verified, a creation follows the resumed conversation's client pane.
   Test the interval before the new association is available.
3. Verify startup of a background standalone child, stale server
   coordinates, multiple displays across tabs, moved or closed panes, and
   duplicate event delivery. Unverified cases create no pane or tab and
   do not replace a verified display association.
4. Verify the supported local Codex and Herdr interfaces, run focused and
   full regressions, and exercise live cross-space startup and resume.
   Document the binding prerequisites, diagnostic outcomes, and any
   unsupported client routes. Installation and live effects stay within
   separately authorized profiles and panes.
