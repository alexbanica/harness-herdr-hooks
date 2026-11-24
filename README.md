# Codex pane launcher for Herdr

Ask Codex to open another session in Herdr. The `codex-pane` skill splits the selected pane once and starts fresh stock Codex in an unfocused sibling in the same workspace and tab. Supply an instruction to send it as the child's first user message, or omit it to open an idle session.

## Prerequisites

Use Python 3, local Herdr 0.9.5 (protocol 22), and authenticated stock `codex` on the Herdr pane shell's `PATH`. The launcher runs only on an explicit request. It requires no event hooks.

## Retire an older installation

Keep the old checkout at its current path until you have uninstalled its registrations. If you need to switch revisions, retain a checkout of the previously installed revision so its `bin/harness-herdr-hooks` remains available. Run status and uninstall with the same profile used for installation. For the default Codex profile, run these commands from the old checkout.

```sh
profile="${CODEX_HOME:-$HOME/.codex}"
bin/harness-herdr-hooks status codex --config-dir "$profile"
bin/harness-herdr-hooks uninstall codex --config-dir "$profile"
```

If that installation also owns an OpenCode plugin, run its retirement commands from the old checkout. Substitute the original profile path in either example if the installation used a custom directory.

```sh
profile="${OPENCODE_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode}"
bin/harness-herdr-hooks status opencode --config-dir "$profile"
bin/harness-herdr-hooks uninstall opencode --config-dir "$profile"
```

The old tool checks manifest ownership and preserves unrelated entries. If it reports a conflict, keep the checkout and inspect the changed entry. Existing panes and conversations can continue running.

## Link the skill

From the root of the launcher checkout, link the skill directory into the selected Codex profile. Keep that checkout available for the lifetime of the link.

```sh
profile="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$profile/skills"
target="$profile/skills/codex-pane"
if [ ! -e "$target" ] && [ ! -L "$target" ]; then
    ln -s "$PWD/skills/codex-pane" "$target"
fi
```

If the destination already exists, inspect it before using it. Open a fresh Codex session and check that `codex-pane` appears in the available skills.

## Open a session

For example, ask “Open a new Codex session here and send it `$implement specs/SPEC-example.md`.” The launcher matches the caller's thread to a unique live Codex session reference. If the reference is missing or ambiguous, the skill asks you to select a live Herdr pane before it creates anything.

You can also invoke the launcher from your project directory. The command below sends the literal dollar sign and adds no final newline.

```sh
launcher="${CODEX_HOME:-$HOME/.codex}/skills/codex-pane/scripts/codex-pane"
printf '%s' '$implement specs/SPEC-example.md' | "$launcher" --message-stdin
```

Omit `--message-stdin` for an idle session. The default working directory is the caller's current directory. To select both the source pane and a different destination directory, use `"$launcher" --pane PANE_ID --cwd DIRECTORY`.

Literal UTF-8 input can contain internal spaces, tabs, line feeds, quotes and shell punctuation. The launcher rejects invalid UTF-8, empty or oversized messages, outer whitespace, carriage returns, other terminal controls, a leading `!`, and slash-command words such as `/status` before splitting. The skill includes a copyable multiline example. [Agent instructions](skills/codex-pane/SKILL.md)

A successful result identifies the workspace, tab and pane and says whether the first message was submitted or omitted. On a partial result, inspect the reported pane. A timeout can occur after Herdr has acted, so repeating the request can duplicate a pane or message. Herdr checks the occupant and submits to the pane in separate operations. A replacement between them can leave delivery uncertain. The launcher reports an acknowledgement mismatch and does not resend.

## Verification

Run `python3 -m unittest discover -s tests -v` for the 16 public CLI tests. Authenticated checks with stock Codex 0.172.0 and Herdr 0.9.5 verified one exact multiline first message, an idle child with zero user turns, requested and default working directories, preserved focus and source history, and explicit selection after a stale inherited pane marker. A fresh child discovered the linked skill. A real subprocess timeout produced one split, one start, one submission attempt and read-only recovery.

Scratch migration checks exercised Codex install, status and uninstall, plus OpenCode status and uninstall against an existing managed-plugin fixture. Unrelated Codex settings and hooks and an unrelated OpenCode plugin survived.
