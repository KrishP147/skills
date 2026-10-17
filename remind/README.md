# remind

*`SKILL.md` is the prompt Claude follows; this file is for you.*

Works on its own.

## What it does

Sets reminders tied to your Claude accounts or to a time. A due reminder shows once at your next prompt, and timed ones also pop up on your desktop at the exact time.

- When an account's session (5-hour) or weekly limit resets.
- When an account's usage drops under a percentage.
- At or in a time: "at 3pm", "in 2h".
- `/remind list` and `/remind cancel <id>` manage them.

## When to use

Reach for it when you want a nudge about your usage limits or a plain timer while you work.

- You ran out on one account and want to know when it's usable again.
- You want to hear when a busy account drops under 50% before a big task on it.
- A timed nudge: "in 45m stretch", "at 5pm send the report".
- Not a task scheduler: it reminds you, it never runs anything.

## How to invoke

User-invoked only (`disable-model-invocation: true`): a reminder is something you ask for, so Claude never sets one on its own.

```
/remind when alex's session limit resets
/remind when work's weekly limit resets
/remind when personal is under 40%
/remind in 2h check the deploy
/remind at 3pm review the PR
/remind list
/remind cancel 3
```

## How it works

The skill turns your words into one `remind.py` command; the script does the rest.

1. **Parse.** One `remind.py add` command: `reset`, `weekly`, `under`, `in` or `at`. No account named means the one this session runs on.
2. **Account data.** Reset times come from the [`switch`](../switch/README.md) usage cache (`~/.claude-switch/usage/<account>.json`, written by its statusline).
   - Unknown account, no cached usage, a window that already reset, or an account already under the percentage: an error, never a guess.
   - Without switch only `in` and `at` work.
3. **Store.** `reminders.json` next to the switch registry, else `~/.claude-remind/`.
   - Atomic writes under a small lock, so parallel sessions never drop or double a reminder.
   - A corrupt file is moved aside, never overwritten.
   - The script copies itself there too, so the hook survives skill updates.
4. **Desktop notification** for timed reminders.
   - Windows: a one-shot scheduled task (`schtasks /Create /XML` with an ISO start time, so locale date formats don't matter). It shows a toast via PowerShell 5.1, with `msg` as fallback. If the PC slept, it runs late (up to a day), then deletes itself.
   - macOS/Linux: an `at` job running `osascript` or `notify-send`. No `at` (or no `notify-send`): in-session only, and `add` says so.
   - "Under N%" has no fixed time: always in-session only.
5. **In-session.** switch's `UserPromptSubmit` hook prints each due reminder once (next to its usage warning) and marks it done.
   - One more than two minutes late says when it was due.
   - Without switch, add the hook yourself (see Tips).
6. **Cancel.** `cancel <id>` removes the reminder and its scheduled task or `at` job.

## Design principles

Two rules shape it: never invent a time, and never get in the way of a prompt.

- **Never guess a time.** Reset times come only from what Claude Code reported for that account; a missing or stale value is said out loud.
- **The hook can't hurt a prompt.** Nothing due means one file read and no write; any error goes to stderr and the prompt carries on.
- **One store, every account.** A reminder set on one account shows in a session on another.

## Use cases

Most runs pair it with `switch` around a usage limit.

- `/remind when alex's session limit resets` after switching away from `alex`; switch back when the toast says so.
- `/remind when work is under 30%` before a long refactor.
- `/remind in 25m take a break` during a long session.

## Tips

A few setups need one extra step.

- **Without switch**, `add` prints the exact hook command for your machine (absolute Python path, forward slashes). Add it to `~/.claude/settings.json` only after your first `/remind`, which puts `remind.py` in place. If the script is missing, Python exits 2, and that blocks the prompt.

  ```json
  {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 ~/.claude-remind/remind.py hook", "timeout": 10}]}]}}
  ```
- **After updating the skills**, `add` may say switch's hook predates remind: rerun switch `setup` once.
- **Idle accounts.** Usage caches only update while an account is in use, so "under N%" for an idle account fires when its window resets (it then counts as 0%).
- **Set up switch later?** Reminders made before stay in `~/.claude-remind/`, which switch's hook doesn't read.
- **Notifications.** Windows needs notifications on for Windows PowerShell (Focus assist hides toasts; the in-session message still shows). macOS has the `at` daemon off by default: `sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.atrun.plist`.
- **Times are local.** `tomorrow 9am` works; other days need `YYYY-MM-DD HH:MM`.

## Example

A reminder for when another account's session window resets.

```
/remind when alex's session limit resets
```

```
reminder 4 at 17:20: alex's session limit reset
  toast at 17:20 (scheduled task claude-remind-4)
  in-session: next prompt after it's due, any account (switch's hook)
```

- At 17:20 a toast says "Claude reminder: alex's session limit reset".
- The next prompt in any session shows `Reminder 4: alex's session limit reset` once.
- `/remind when nobody's session limit resets` prints `remind: no account 'nobody' (have: alex, work)` and sets nothing.

## Related

It reads and delivers through one other skill.

- [`switch`](../switch/README.md): the accounts, usage cache and prompt hook.

## Prereqs

Python 3.8+ (stdlib only).

- Account reminders need [`switch`](../switch/README.md) set up.
- Notifications need Windows (PowerShell 5.1), or `at` (plus `notify-send` on Linux).
