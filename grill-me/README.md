# grill-me

*By Matt Pocock (MIT), included verbatim. `SKILL.md` is the prompt Claude follows; this file is for you.*

## What it does

Short alias for [`grilling`](../grilling/): a relentless interview to sharpen a plan or design.

## When to use

When you want to type something short to start a grilling session.

## How to invoke

`/grill-me <plan or idea>`. User-invoked only (`disable-model-invocation: true`): Claude never picks it on its own; it auto-invokes `grilling` instead.

## How it works

1. Calls the Skill tool with `grilling`.
2. Everything else is `grilling` — see its [README](../grilling/README.md).

## Design principles

- **One source of truth.** The alias holds a single line, so any change to `grilling` reaches `/grill-me` too.
- **User-only on purpose.** Claude auto-invokes `grilling`; the alias exists only so you can type something short.

## Use cases

- Starting a grilling session by hand with a short command.
- Any case listed under [`grilling`](../grilling/README.md#use-cases).

## Tips

- Claude never picks `grill-me` itself, so other skills and agents call `grilling` instead.
- Want a written record? Use [`grill-docs`](../grill-docs/) rather than this alias.
- The alias's `SKILL.md` (verbatim upstream) doesn't say to forward your argument to `grilling`. If Claude asks what to grill after `/grill-me <plan>`, repeat the plan.

## Example

```
/grill-me my plan to split the monolith into three services
```

The Skill tool loads `grilling` and the interview runs exactly as `/grilling …` would. Round 1 asks the whole frontier at once, numbered, each with a recommendation:

```
❓ **Q1** - **Service boundaries**: split by domain (orders, billing, accounts) rather than by layer?
➡️ Yes, by domain.

---

❓ **Q2** - **Shared database**: keep one shared database during the split, and give each service its own later?
➡️ Yes.
```

You answer "1 yes, 2 yes"; round 2 asks the questions that depended on those (how billing reads orders data while the database is shared). It ends when nothing is left open and you confirm.

## Related

[`grilling`](../grilling/).

## Prereqs

None beyond [`grilling`](../grilling/) installed alongside it.
