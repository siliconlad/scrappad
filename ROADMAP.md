# Scrappad roadmap

This note records the next features agreed on 2026-08-08. The goal is to make
Scrappad a smooth handoff point between LLM-generated Python experiments and
hands-on human exploration, while keeping ordinary Python files as the shared
artifact.

## Completed

### Python syntax highlighting

- The editor, live REPL input, and submitted REPL commands use the same
  Tree-sitter Python query and Monokai token palette.
- REPL output remains unhighlighted so input and output are visually distinct.

## Next features

### 1. Add a configuration menu

- Add a `:config` command that opens an in-app configuration menu; consider a
  keyboard shortcut once terminal compatibility has been checked.
- Apply syntax-theme changes immediately to the editor, live REPL input, and
  submitted commands, with a preview before saving. Keep REPL output plain.
- Initially offer the themes supported natively by both renderers: Monokai as
  the default and Dracula as the primary alternative.
- Add curated shared mappings for One Dark, Nord, and GitHub Light rather than
  exposing mismatched editor and REPL theme catalogs.
- Include a small first set of useful editor options: line numbers, soft wrap,
  tab width, and whether Tab inserts spaces or tabs.
- Persist preferences in the platform-standard user configuration directory,
  while keeping sensible defaults when no configuration file exists.

### 2. Add a `:shortcuts` REPL command

- Add `:shortcuts` to display the available keyboard shortcuts in the REPL.
- Include it in the output of `:help` so the command is discoverable.
- Keep the displayed shortcuts synchronized with the application's key
  bindings.

### 3. Reload files changed outside Scrappad

- Add an explicit `:reload` command as the minimum useful workflow.
- Detect changes made to the open file by an editor, script, or coding agent.
- Never silently replace a dirty editor buffer. Offer a clear choice to reload,
  keep the buffer, or inspect the conflict.
- When the buffer is clean, external changes may be reloaded automatically or
  surfaced as a lightweight notification.
- Reloading should update the editor and mark its contents as pending; execution
  should remain deliberate through the existing pane switch or `F5` behavior.

### 4. Export the REPL transcript

- Add a command that exports REPL commands and their displayed output/errors to
  a file.
- Report the resulting path and, where clipboard support is available, copy the
  path to the clipboard automatically.
- Degrade cleanly when clipboard integration is unavailable: the export itself
  must still succeed and the path must remain easy to copy.
- Decide whether exports should default to a temporary location or live beside
  the open Python file.

### 5. Use the project's Python environment

- Discover likely project environments, especially an active `VIRTUAL_ENV` and
  a project-local `.venv` (including environments created by `uv`).
- Run the Python kernel with the selected project interpreter while allowing the
  Scrappad UI itself to remain installed independently.
- Show the selected interpreter in the UI and provide an explicit CLI override,
  such as `--python /path/to/python`, when discovery is ambiguous.
- Define deterministic selection rules and ask before switching when multiple
  plausible environments exist.
- Aim for a smoother default than requiring
  `uvx --with-editable . scrappad` for every project session.

## Suggested implementation order

1. Configuration menu, persisted options, and shared syntax themes.
2. The `:shortcuts` REPL command.
3. Explicit file reload, followed by safe external-change detection.
4. REPL transcript export and optional clipboard integration.
5. Interpreter discovery, selection, and kernel launch support.
