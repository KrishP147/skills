---
name: kanban-setup
description: Create a GitHub Projects kanban board for a repo and fill it with issues from documented work (planned, already done, or both).
argument-hint: "current | retroactive | both (default: current)"
disable-model-invocation: true
---

Creates real, public GitHub issues. Show the full preview and wait for a yes before creating anything.

## 1. Scope

`gh auth status` must list `project`. Missing → user runs `gh auth refresh -s project -s read:project` (opens a browser); stop until done.

## 2. Board (idempotent)

Look for this repo's board per [BOARD.md](../next/BOARD.md); another board on the account doesn't count. None → `gh project create --owner <owner> --title "<repo> Board"`.

The Status field needs an **In Review** option (`session-handoff` moves cards there; the default field has only Todo / In Progress / Done). Check `gh project field-list`. Missing → [IN-REVIEW-OPTION.md](IN-REVIEW-OPTION.md).

Label mode instead: create all four status labels now (colors in BOARD.md).

## 3. Candidates

Scan whatever exists: README roadmap/TODO sections, `TODO`/`FIXME` comments, `CHANGELOG.md`, `docs/`, plan docs, and (retroactive) `git log`.

- **current**: planned/undone items. Search existing issues first; skip duplicates.
- **retroactive**: finished items, created then immediately closed, for a clean history.
- **both**: both passes, separated in the preview.

## 4. Preview, then create

Preview every item: title, mode, target column. On yes, per item: `gh issue create`, close it if retroactive, `item-add`, then `item-edit` Status to Todo or Done (BOARD.md).
