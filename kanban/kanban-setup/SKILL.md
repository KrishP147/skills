---
name: kanban-setup
description: Create a GitHub Projects kanban board for a repo and fill it with issues from documented work (planned, already done, or both).
argument-hint: "current | retroactive | both (default: current)"
disable-model-invocation: true
---

Creates a real board and real, public GitHub issues. Steps 1-3 are read-only; show the full preview (step 4) and wait for a yes before creating or changing anything.

## 1. Scope

`gh auth status` must list `project`. Missing → user runs `gh auth refresh -s project -s read:project` (opens a browser); stop until done.

## 2. Board (read-only)

Look for this repo's board per [BOARD.md](../next/BOARD.md); another board on the account doesn't count. Note whether one exists; create nothing yet.

The Status field needs an **In Review** option (`session-handoff` moves cards there; the default field has only Todo / In Progress / Done). If a board exists, check `gh project field-list` and note whether the option is missing (fix: [IN-REVIEW-OPTION.md](IN-REVIEW-OPTION.md)).

**Label mode** (four `status:*` labels instead of a board, colors in BOARD.md) when the user asks for it, the `project` scope isn't granted and the user declines to refresh it, or the owner can't create projects.

## 3. Candidates

Scan whatever exists: README roadmap/TODO sections, `TODO`/`FIXME` comments, `CHANGELOG.md`, `docs/`, plan docs, and (retroactive) `git log`. Skip `skilleddocs/`, `node_modules`, `.venv` and vendored dirs.

- **current**: planned/undone items. Search existing issues first; skip duplicates.
- **retroactive**: finished items, created then immediately closed, for a clean history.
- **both**: both passes, separated in the preview.

## 4. Preview, then create

Preview first the **board actions** that will run: create the board (`gh project create --owner <owner> --title "<repo> Board"`), link it (`gh project link <n> --owner <owner> --repo <owner>/<repo>`), add the In Review option, or in label mode create the four labels. Then every item: title, mode, target column.

On yes, do the board actions first, then per item: `gh issue create`, close it if retroactive, `item-add`, then `item-edit` Status to Todo or Done (BOARD.md).
