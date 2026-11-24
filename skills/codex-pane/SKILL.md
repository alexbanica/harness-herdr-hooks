---
name: codex-pane
description: Open a fresh Codex session in a sibling Herdr pane when explicitly asked to create or start another Codex session in Herdr. Use only for that handoff request.
---

# Open a Codex session in Herdr

Use this action only when the user explicitly asks for a new Codex session in a Herdr pane. Do not launch it for ordinary Codex work. It creates one sibling pane and one fresh stock Codex session; it does not wait for the new session's task to finish.

Resolve this skill's installed directory from this `SKILL.md`, then invoke its `scripts/codex-pane` executable by that path. Do not resolve the script from the current project directory: the skill may be linked from another project. Run it from the caller's project directory so the default destination working directory is preserved. Make one launcher invocation for the handoff. If the user supplied a different working directory, pass it with `--cwd`.

If the current Codex pane is uniquely identified, invoke without `--pane`. If it is not uniquely identified, ask the user which live Herdr pane to use before splitting, then pass the user's selected ID as `--pane ID`. Do not choose by focus, inherited pane markers, or working directory. The launcher may report that identification failed; treat that as a request for an explicit pane and invoke only after the user selects one.

If the user asks only for a session, omit `--message-stdin`; Codex will be left ready for input. To send the user's requested first instruction, pass it as literal UTF-8 stdin, not as shell code. For a skill linked at the standard location, run this from the caller's project directory (set `launcher` to the actual skill path if installed elsewhere):

```sh
launcher="${CODEX_HOME:-$HOME/.codex}/skills/codex-pane/scripts/codex-pane"
printf '%s' '$implement specs/SPEC-example.md' | "$launcher" --message-stdin
```

`printf '%s'` treats the quoted text as data and adds no newline. For exact multiline input, keep the whole text in a single-quoted shell string, put real line breaks where wanted, and close the quote immediately after the final character. In a single-quoted shell string, represent an apostrophe by ending the quote, writing `\'`, and opening it again. For example:

```sh
launcher="${CODEX_HOME:-$HOME/.codex}/skills/codex-pane/scripts/codex-pane"
printf '%s' '$implement specs/SPEC-example.md
Please preserve "this text" and it'\''s punctuation.' | "$launcher" --message-stdin
```

The line break between the two lines is part of the message; no final newline is added. The launcher submits the complete decoded text as one Herdr argument. It rejects empty input, boundary whitespace, carriage returns, terminal control characters, a leading `!` shell-mode token, and a leading slash-command token because the supported Codex TUI may alter or route them. Internal spaces, tabs, line feeds, quotes, dollar signs, and shell punctuation are passed literally. If input is rejected, explain the unsupported text boundary and ask for revised wording before making a new handoff attempt.

Report the destination workspace, tab, and pane, and whether Codex is ready and the first message was submitted or omitted. If the launcher reports an uncertain or partial result, report its known pane and exact uncertainty; do not repeat the split, startup, or message submission. A message submission acknowledgement means the handoff was submitted, not that the new session completed the requested work.
