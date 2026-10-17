# spend-gate

*`SKILL.md` is the prompt Claude follows; this file is for you.*

Needs: `handoff-auto` (installed with it).

## What it does

Stops Claude from running a billable action (spinning up a GPU pod, calling a paid API, buying a paid tier, spending cloud credits) without first:

- Estimating the cost.
- Checking a live balance where possible.
- Getting your explicit yes for that one action.

## When to use

- Anything that provisions cloud compute: `runpodctl create`, `vultr-cli
  instance create`, `aws ec2 run-instances`, `gcloud compute instances
  create`, `az vm create`, and equivalent MCP create/deploy/run/start/update tools.
- Paid deploys (`modal deploy`) and per-token/per-request paid API calls.
- Not for read-only checks (listing pods, checking a balance, viewing
  pricing) - those are how the skill informs its own estimate, not what it
  gates.

## How to invoke

Claude runs it on its own before a billable action.
You can also run it directly:

```
/spend-gate
```

## How it works

1. **Classify** - decide if the action about to run is billable; when
   ambiguous, treat it as billable.
2. **Estimate** - unit price x hours/tokens = total, citing a price source
   (URL or tool output, dated).
3. **Check live balance/credit** - read-only calls only, never a call that provisions or spends.
   - No free balance read → say so and ask you for the balance.
   - The step is never skipped.
4. **Gate** - show the number, wait for an explicit yes to *this* action.
   - A budget cap or an earlier "go ahead" doesn't count.
5. **Log** - append the approved amount, purpose, price source, and
   resource id to `skilleddocs/spend.md`.
6. **Run + remind** - run the approved action, then remind about teardown
   or an auto-stop/idle-timeout for anything left running.
7. **Approval token** - if `hooks/spend-guard.py` blocks the action, write
   the approval it expects (see [HOOK.md](HOOK.md)) only after step 4's yes.

## Design principles

- **A cap is not a yes.** Nothing here treats a standing budget as blanket
  approval - every billable action gets its own ask, even a repeat of one
  already approved.
- **Estimate before you act, not after.** The gate has to show a number
  before the user says yes, not a bill after the fact.
- **Prefer a hard stop over a guess.** If a price or balance can't be
  verified live, the skill says so and asks rather than estimating from a
  remembered figure.

## Use cases

- About to provision a GPU pod for a training/eval run.
- About to call a paid API in a loop (batch scoring, embeddings) where the
  per-call cost adds up.
- Reviewing whether a repo's existing spend approvals in
  `skilleddocs/spend.md` still look right before continuing a paused job.

## Tips

- Cite the price source every time, even for a provider you've priced
  before - prices drift, and the log should show what you actually checked.
- If the provider's balance endpoint is unreadable or rate-limited, say so
  in the gate prompt instead of skipping step 3 silently.
- Pair with `hooks/spend-guard.py` (see [`hooks/README.md`](../hooks/README.md))
  if you want a hard stop at the tool-call level, not just a reminder in the
  prompt.

## Example

```
/spend-gate
```

Claude is about to run `runpodctl create pod --gpuType RTX4090`.

- It reads the live rate (illustrative: on one day a 4090 listed $0.89/h secure cloud, $0.34/h community; prices drift, so never reuse these).
- It estimates a 2-hour secure job at ~$1.78.
- It checks the balance via a read-only billing call (or says none is readable and asks you).
- It shows both numbers, and waits.
- You reply "yes, go ahead."
- Claude logs the row to `skilleddocs/spend.md`, creates the pod, and reminds you to stop it (or that it will auto-stop) once the job finishes.

## Related

[`hooks/spend-guard.py`](../hooks/spend-guard.py) - optional `PreToolUse` hook that enforces the same gate at the tool-call level.

- It blocks a matching command/MCP call unless an approval file exists.
- The approval file is written after the explicit yes at step 4, Gate; see [HOOK.md](HOOK.md).

## Prereqs

None.

- Reads whatever pricing/balance tools the billable provider already exposes (its CLI, MCP server, or pricing page).
- Nothing extra to install for the skill itself.
