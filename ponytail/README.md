# ponytail

*By DietrichGebert (MIT), included verbatim from [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail/blob/84740e3d344b69b4a133201fa519eb37a62a2b2a/skills/ponytail/SKILL.md) (v5.2.0). `SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Puts Claude in "lazy senior developer" mode for the whole session: it solves the task with the smallest change that fully works, and ends its reply with one or two lines saying what it skipped or did not check, plus any risk you must know.

## When to use

- Any coding task: writing, fixing, refactoring, reviewing, choosing dependencies.
- You say "ponytail", "be lazy", "simplest solution" or "yagni", or you complain about over-engineering or bloat.
- Not for switching off: say "stop ponytail" or "normal mode" to end it.

## How to invoke

```
/ponytail [lite|full|ultra]
```

Also model-invocable, so Claude can pick it up from the trigger phrases above. It stays active until you say "stop ponytail" or "normal mode". Switch level any time with `/ponytail lite|full|ultra`. Default is `full`.

## How it works

1. Reads the task and the code it touches, and lists every place the change must reach: callers, tests, fixtures, config, exports. Checks what it could break for users. That is the scope; extra features are not.
2. Takes the first option that fully works: skip it if not needed (and name what was skipped), reuse what the codebase has, use the standard library or a platform feature, use an installed dependency, write one readable line, otherwise the minimum code.
3. Finishes every part the task needs, including the callers, tests and fixtures the change breaks. For a bug fix it greps every caller first and fixes the root cause once in the shared code.
4. Leaves one small test or assert-based self-check for new non-trivial logic. A shortcut with a known limit gets a comment: `shortcut: <the limit>, <when to upgrade>`.
5. Ends the reply with what it skipped or did not check, and any risk.

| Level | Behavior |
|-------|----------|
| **lite** | Builds what was asked; names the smaller option in one line and lets you pick. |
| **full** | The rules above. Default. |
| **ultra** | Also questions the request: before building, pushes back on any part the need does not justify. |

## Design principles

- **Lazy about the solution, never about the change.** Fewer abstractions, options and dependencies, but every caller, test and fixture the change breaks still gets fixed.
- **Some things are never cut.** Validation at trust boundaries, error handling that prevents data loss, security, accessibility, hardware calibration, and anything you asked for.
- **Say what was left out.** The closing lines make skipped work and risks visible instead of silent.

## Use cases

- Keeping a small fix small instead of getting a refactor with new config.
- Asking for "build me X" and getting the smallest version that does the core job.
- Reviewing a change for bloat (`ultra` also questions the request itself).

## Tips

- Use `lite` when you want to choose between the full and the smaller option yourself.
- Use `ultra` when you suspect the request itself is bigger than the need.
- It reads its own rules as session-wide, so say "normal mode" before a task where you do want the extras.

## Example

```
/ponytail ultra
```

Claude questions any part of your next request the stated need does not justify before building, builds the smallest complete version, and closes with what it skipped and any risk.

## Related

- Upstream also ships sibling skills (`ponytail-review`, `ponytail-audit`, `ponytail-debt`, `ponytail-gain`, `ponytail-help`), hooks and a statusline. They are not included here; only the core `ponytail` skill is.
- [`grilling`](../grilling/README.md) is another third-party verbatim skill; see [Third-party skills](../README.md#third-party-skills) in the root README.

## Prereqs

None.
