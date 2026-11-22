# SPEC — Codex adapter compatibility

Status: Approved

Approved by the user's explicit response `approve` on 2026-11-22.
Reviewed proposed revision SHA-256 `2376b7c26bb0e9e342b8272e9f1e1b99e4ca17aafe71eb1cef0c699dbbc389f6`.

## Purpose

Keep the Herdr adapter working across Codex updates when the local app server
provides the protocol and identity evidence required by the operation. On the
installed revision `09a31ca`, a live handshake with Codex `0.171.0` failed
because the adapter accepts only `0.170.0`. A diagnostic client reached the same
daemon and read the affected thread's enabled and trusted hooks. That read
establishes connectivity and hook registration.

## Scope and decision

- Accept any Codex release identifier for an otherwise compatible local app
  server. The running daemon's version is diagnostic metadata and does not
  determine permission to launch, attach, observe, or clean up a pane. A
  missing or unparseable release identifier yields an unknown version when
  the rest of the handshake and identity evidence are valid.
- Compatibility means the verified endpoint completes the required transport
  and initialization exchange, identifies the expected Codex profile, and
  returns the methods and response fields required by the requested operation.
  A release with an incompatible or incomplete interface yields a bounded
  failure at the affected operation.
- Keep the existing checks for socket and process identity, profile isolation,
  thread identity and ancestry, ownership, event parsing, and effect ordering.
  Preserve existing timeout and retry boundaries. Additional response fields
  are allowed where the required fields remain valid.
- Surface a concise reason when a required transport, method or response
  contract fails. Include the observed daemon release when available. Avoid
  credentials, transcript content, and unbounded response dumps.
- This change covers the Codex version gate. Shared-daemon pane markers and
  missing native pane session references are separate attachment failures seen
  in the live investigation. OpenCode and Herdr protocol qualification remain
  under their existing contracts.

## Delta and authoritative predecessors

This specification replaces the exact Codex release requirement in
[SPEC-codex-herdr-session-lifecycle.md](SPEC-codex-herdr-session-lifecycle.md)
and the inherited Codex qualification in
[SPEC-codex-standalone-creation-events.md](SPEC-codex-standalone-creation-events.md).
Their companion plans remain references for lifecycle and creation-event
behavior. The earlier version observations remain historical evidence. The
installed session-subagent-tabs revision includes
`specs/SPEC-session-subagent-tabs.md` and `specs/PLAN-session-subagent-tabs.md`.
That revision's tab placement and ownership behavior are preserved wherever the
new compatibility policy is integrated. Approved predecessors retain their
original content and approval records.

## Acceptance and validation

1. Exercise the adapter with Codex `0.170.0` and `0.171.0` initialize fixtures,
   an arbitrary future release string, and absent or unfamiliar version
   metadata. Each proceeds when the required interface and identity are valid.
2. Verify that incompatible transport, profile mismatch, missing required
   methods, and invalid required replies cannot cause a new Herdr effect.
   Verify that a version-string change adds no path around the existing
   endpoint, thread, ancestry, or ownership checks.
3. Verify successful read-only initialization and thread metadata retrieval
   through the updated adapter on the running `0.171.0` daemon. Run the
   relevant adapter regressions and the full test suite. Record any live
   limitation separately from unit or fixture coverage.
4. Update operator installation, troubleshooting, and compatibility guidance
   to describe the required interface, distinguish tested releases from
   runtime eligibility, and explain diagnostics for incompatible backends.
   Native pane attachment still requires its own identity checks and live
   evidence.
