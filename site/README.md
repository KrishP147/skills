# site

Static site for this repo's skills, agents and hooks: a Claude Code style
terminal home with a free-typing slash search, a plain list of every entry,
and a `/<name>` detail page for each. No framework, no npm install, no runtime deps.

## Layout

| Path | What |
|---|---|
| `src/index.html` | home template (`{{COUNT}}`, `{{LIST}}`, `{{DATA}}` filled at build): welcome + catalog scroll in `.feed`, slash prompt pinned to the viewport bottom in `.dock` (menu opens upward), fixed GitHub link top right, fixed Rocky image link to krishpunjabi.com top left (also on 404; inline in the detail topbar). Under 600px an opaque 66px band sits behind the corner links on non-detail pages so feed text scrolls under it. Intro animation (≤1.5s, any key/click skips) runs only when the inline head script adds `html.intro`, never under `prefers-reduced-motion` |
| `src/detail.html` | `/<name>` detail page template (sticky slash prompt, `← all commands` link, header card + chips, sections, prev/next, `#comments` giscus block) |
| `data/meta.json` | per-name author + battle-tested level (`levels_source` says where levels come from); names not listed get level `new`, author defaults to Krish. `aliases` (`{name: [word, ...]}`) adds search words for the slash prompt: lowercase `a-z0-9-`, never an existing name; the build fails on unknown names or bad words. Aliases come only from here, never SKILL.md frontmatter |
| `src/404.html`, `src/style.css` | not-found page (`noindex`), all styles. Two palettes as `:root` tokens: dark by default, light under `prefers-color-scheme: light` (Claude Code's dark and light themes); rules use only tokens. `--accent` is the text accent (light: darkened to pass 4.5:1), `--accent-line` the brand orange for borders, `--sel-bg` / `--accent-sel` the selected menu row and the home list's hover row (name and dim text >= 4.5:1 over `--panel` and `--bg`, checked by `PaletteContrastTest`), `--band` the mobile corner band. Every page has `<meta name="color-scheme" content="light dark">` |
| `src/rocky.webp` | 128px Rocky for the krishpunjabi.com corner link (owner's asset, cropped to the carapace, no metadata); copied byte for byte |
| `src/favicon-32.png`, `src/apple-touch-icon.png` | favicon (32px) and iOS icon (180px, solid dark bg), same Rocky crop; copied byte for byte |
| `src/filter.js` | pure slash-search logic (browser global `SkillFilter`, CommonJS in node), see [Slash search](#slash-search) |
| `src/app.js` | DOM wiring: events, dropdown, navigation, intro skip (shared by home and detail pages; `data-autofocus="false"` on the input skips autofocus and the home-only click-to-refocus) |
| `test/filter.test.mjs` | node:test suite for `filter.js`; loads the real nav data through `scripts/build_site.py` (needs `python3` or `python` on PATH) and checks every name surfaces from a prefix, a mid-word fragment and 1-2 char typos |
| `dist/` | build output, git-ignored |

Build script: [`../scripts/build_site.py`](../scripts/build_site.py) (stdlib
only), with [`site_detail.py`](../scripts/site_detail.py) for detail pages and
[`md_render.py`](../scripts/md_render.py), a small Markdown renderer that
escapes all raw HTML and drops non-http(s)/mailto link URLs. It reuses `scripts/lint.py`'s discovery, so the site lists exactly what
lint counts. Groups: top-level skill dirs = core, `kanban/*` = kanban,
`agents/*.md` (minus README) = agents, `hooks/*.py` = hooks (lint doesn't
count hooks; `agents/hooks/guard-git.py` is not listed). The home count line
reads `N skills · M agents · K hooks`. The build fails on a name shared by
two entries of any kind.

## Slash search

The prompt (home dock and detail topbar) starts as `/`, which can't be deleted;
everything after it is typed freely. Each page embeds the nav data
(`name`, `kind` = `skill` | `agent` | `hook` from the group, `group`, `summary`,
optional `aliases` from `meta.json`) in `#skill-data`.

- **Ranking:** exact name > name prefix > word-boundary prefix (`handoff` finds
  `session-handoff`) > substring > alias; ties A-Z. A bare `/` lists everything
  A-Z. About 8 rows show, the rest scroll.
- **No match:** `No command matches "/x". Did you mean /y?` with up to 3
  suggestions: OSA (Damerau-Levenshtein) distance over names, name parts and
  aliases, normalized by length, then summary words (`/review` finds `/pr-watch`).
  Nothing close: `No matches. Type / to see all.`
- **Keys:** the first row is highlighted every time the menu opens (prompt
  click, `/`, Enter or Up/Down on a closed menu, bare `/` included) and every
  time the text changes. Up/Down move the highlight, Tab fills the highlighted
  name (when that changes nothing, Tab moves focus), Enter or click opens it, Esc clears to `/` (again: closes the menu; detail
  pages, once more: home), `/` anywhere on
  the page focuses the prompt. An exact name shows a dim `↵ to open`; typing
  never navigates by itself.
- **ARIA:** input `role=combobox` with `aria-expanded` / `aria-activedescendant`,
  `role=listbox` of `role=option`s, polite `#status` live region for the count
  or the did-you-mean line.

## Comments (giscus)

Each detail page embeds [giscus](https://giscus.app) in `#comments`: an
inline script in `src/detail.html` creates the `client.js` tag with
`data-theme` picked from `prefers-color-scheme` (`light` or
`transparent_dark`) before giscus loads, and on a scheme change posts
`{giscus: {setConfig: {theme}}}` to the giscus iframe. Built-in themes only,
no external CSS URL. Setup for a repo:

1. Install the giscus GitHub app on the repo and enable Discussions.
2. Fetch the ids:
   `gh api graphql -f query='query { repository(owner:"<owner>", name:"<repo>") { id discussionCategories(first:20) { nodes { id name } } } }'`
   and put them in `data-repo-id` / `data-category-id`.
3. Mapping is `specific` with `data-term` = the page name (not pathname, since
   the base differs between previews and prod), `data-strict="1"`.

Optional: create a "Skill tips" category and swap `data-category` /
`data-category-id`. No `giscus.json` on purpose: its origins list would block
preview deploys.

## Detail pages

- **Sources.** Skill: its `README.md`. Agent: its `## <name>` section of
  `agents/README.md` (the `- **Label:**` bullets become sections, e.g.
  Role → What it does, You pass → How to invoke) plus `agents/<name>.md`
  frontmatter (model, tools / disallowedTools, preloads, guard hook). Agents
  also get the shared `## Example` and a generated Related list (preloads +
  pages that link to them). Hook: its ``## `<file>.py` `` section of
  `hooks/README.md`; paragraphs led by a label that maps (`How it works:`,
  `Install into a repo:`, `Example output ...:`, `Related:`) start a
  section, other paragraphs stay with the one above, the text before the
  first label is What it does. Its summary is the heading's tagline (text
  after the em dash), first letter capitalized and a period added like skill
  summaries; its description is that summary plus the section's first paragraph.
- **Sections**, in order: What it does, When to use, How to invoke, How it
  works, Design principles, Use cases, Tips, Example, Related, Prereqs, then
  any README sections that don't map (original heading kept), then Source.
  Heading matching is tolerant (`Invoke`, `Examples`, `Prerequisite: …` all
  map). Empty or missing sections are not rendered. A skill with no Prereqs
  section inherits its parent group README's (e.g. `kanban/README.md`).
- **Links.** Relative links become
  `https://github.com/KrishP147/skills/blob/master/<path>` (anchors kept);
  links to another skill's dir or README become `/<name>`,
  `agents/README.md#<agent>` becomes `/<agent>`, and `hooks/<hook>.py` or
  `hooks/README.md#<hook heading anchor>` becomes `/<hook>`.
- **Chips:** author (cross-checked in tests against
  `THIRD_PARTY_LICENSES.md`), invocation (`user only` when the SKILL.md
  frontmatter has `disable-model-invocation: true`; hooks: the hook event),
  model / tools / preloads (agents), source (hooks: the `.py` on GitHub),
  prereqs, tested level.

- **Example = transcript.** The Example section is drawn as a Claude Code
  session in the terminal chrome (`.tx`), from the README's own `## Example`
  (no extra files). Default: a leading code fence (`/cmd args`) becomes the
  `> /cmd args` prompt line and everything after it one `⏺` reply block
  (rendered Markdown). No leading fence (hook output examples): the reply
  block only.
- **`transcript` fence** (opt-in, for a full session). Line grammar:
  `> text` user prompt; `⏺ Tool(args)` a tool call, collapsed in a
  `<details>`, with the indented `⎿ ...` line (and further indented lines)
  under it as its result; `⏺ text` a reply (inline Markdown; indented lines
  continue it); any other line plain dim text. Prompts and tool output stay
  literal; all markup comes from the build (`md_render.parse_transcript`),
  raw HTML is escaped. Prose around the fence stays prose. On GitHub it is
  just a readable code block. Every step must trace to the SKILL.md or agent
  `.md` (D29). Full transcripts: `meta-orchestrator`, `pair`, `pr-watch`,
  the agents' shared example, `spend-guard`.
- **Warning.** An entry with no Example prints
  `WARN: <name>: no Example section ...` on stderr (the build still
  succeeds); a test keeps all 28 entries at zero warnings.
- **Back home.** A visible `← all commands` link above the echoed command;
  on the prompt, Esc clears the text, then closes the menu, then (bare `/`,
  menu closed) goes home. On the home page Esc never navigates.

Never add a file named `SKILL.md` under `site/`: lint globs `*/SKILL.md` and
`*/*/SKILL.md` and would treat it as a skill.

## Build, test, preview

```sh
python scripts/lint.py
python scripts/build_site.py              # wipes + writes site/dist/
python scripts/build_site.py --base /skills --out /tmp/skills-site   # served under a prefix
python -m unittest discover -s scripts -p "test_*.py"
node --test site/test/filter.test.mjs   # list files; Node 22 on Windows rejects a dir arg
python -m http.server -d site/dist 8000   # http://localhost:8000
```

Options: `--base <prefix>` (default env `SITE_BASE`, else `/`) is the URL
prefix the site is served under; `/skills`, `/skills/` and `skills` all mean
`/skills`. Every root-relative link, asset URL and the home link get it; the
canonical / `og:url` are absolute (`https://www.krishpunjabi.com/skills/<name>`)
and are not prefixed again. `--out <dir>` (default `<repo>/site/dist`) is
resolved against the current directory and may be outside the repo; skill
sources are always read from this repo, not the cwd.

Output: `index.html`, `skills.json` (name, description, summary, group,
source, readme), `<name>/index.html` detail page per skill/agent/hook (so `/pair` resolves
statically), `404.html`, `style.css`, `filter.js`, `app.js`, `rocky.webp`, `favicon-32.png`, `apple-touch-icon.png`. Every
`site/src/*.css|js|svg` is copied as text and every `*.webp|png|jpg` byte for byte. The build is
deterministic.

## Deploy

The site is built inside the portfolio site's Vercel build into `public/skills`
and served at <https://krishpunjabi.com/skills>. From the portfolio root:

```sh
git clone --depth 1 https://github.com/KrishP147/skills /tmp/skills && \
  python3 /tmp/skills/scripts/build_site.py --base /skills --out public/skills
```

No install step (stdlib Python only). Set `SITE_BASE=/skills` instead of
`--base` if that is easier in the build config.

Pushes to master touching site inputs (`site/**`, the build scripts, `agents/**`,
SKILL.md and README.md files, `CONTRIBUTING.md`, `THIRD_PARTY_LICENSES.md`) trigger
`.github/workflows/deploy-portfolio.yml`, which POSTs the portfolio's Vercel deploy hook
stored in repo secret `PORTFOLIO_DEPLOY_HOOK`. It can also be run manually
(`workflow_dispatch`). Without the secret the job skips and changes go live on the
portfolio's next deploy.
