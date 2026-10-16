# <skill-name>

*`SKILL.md` is the prompt Claude follows; this file is for you.*

Template for a skill submission's README. Copy this file, fill in every
section, and keep the `## ` headings exactly as they are (name, order, and
wording) — `scripts/lint.py` and the site both parse them. Delete this note
and everything in angle brackets when you're done.

## What it does

One or two sentences: what the skill produces or changes, in plain language.
No jargon a first-time reader wouldn't know.

## When to use

Bullet list of the situations or trigger phrases that should make Claude (or
you) reach for this skill. Include what it's *not* for if that's likely to be
confused.

## How to invoke

The exact command or trigger phrase, with any flags/arguments:

```
/<skill-name> <args>
```

Note whether it's user-invoked only or also model-invocable.

## How it works

Numbered steps of what actually happens when the skill runs — inputs it
reads, decisions it makes, what it writes and where.

## Design principles

The 1-3 principles that shaped how this skill is built (why it's structured
this way, what trade-off it makes and why).

## Use cases

A short list of concrete situations where this skill earns its keep.

## Tips

Anything a user should know to get good results — gotchas, defaults worth
overriding, things that trip people up.

## Example

One realistic, worked example: the invocation, then what happened.

Start with a code fence holding the invocation (`/name args`); the site draws it as the
`> /name args` prompt and the rest as the reply. For a full session use a `transcript`
fence instead (grammar in [`site/README.md`](../../site/README.md#detail-pages)).

## Related

Other skills or agents this one calls, is called by, or is commonly paired
with, with links.

## Prereqs

Anything that must be installed or configured first (CLI tools, auth scopes,
other skills/agents). Write "none" if there aren't any.
