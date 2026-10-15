# site

Static site for this repo's skills and agents: a Claude Code style terminal
home with a locked slash input, a plain list of every skill and agent, and a
`/<name>` detail page for each. No framework, no npm install, no runtime deps.

## Layout

| Path | What |
|---|---|
| `src/index.html` | home template (`{{COUNT}}`, `{{LIST}}`, `{{DATA}}` filled at build): welcome + catalog scroll in `.feed`, slash prompt pinned to the viewport bottom in `.dock` (menu opens upward), fixed GitHub link top right. Intro animation (≤1.5s, any key/click skips) runs only when the inline head script adds `html.intro`, never under `prefers-reduced-motion` |
| `src/detail.html` | `/<name>` detail page template (sticky slash prompt, header card + chips, sections, prev/next, `#comments` giscus block) |
| `data/meta.json` | per-name author + battle-tested level (`levels_source` says where levels come from); names not listed get level `new`, author defaults to Krish |
| `src/404.html`, `src/style.css` | not-found page (`noindex`), all styles |
| `src/favicon.svg` | favicon: an orange ✻ drawn as plain SVG strokes (own drawing, not a brand asset) |
| `src/filter.js` | pure slash-input logic (browser global `SkillFilter`, CommonJS in node) |
| `src/app.js` | DOM wiring: events, dropdown, navigation, intro skip (shared by home and detail pages; `data-autofocus="false"` on the input skips autofocus and the home-only click-to-refocus) |
| `test/filter.test.mjs` | node:test suite for `filter.js` |
| `dist/` | build output, git-ignored |

Build script: [`../scripts/build_site.py`](../scripts/build_site.py) (stdlib
only), with [`site_detail.py`](../scripts/site_detail.py) for detail pages and
[`md_render.py`](../scripts/md_render.py), a small Markdown renderer that
escapes all raw HTML and drops non-http(s)/mailto link URLs. It reuses `scripts/lint.py`'s discovery, so the site lists exactly what
lint counts. Groups: top-level skill dirs = core, `kanban/*` = kanban,
`agents/*.md` (minus README) = agents.

## Comments (giscus)

Each detail page embeds [giscus](https://giscus.app) in `#comments` (plain
script tag in `src/detail.html`). Setup for a repo:

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
  pages that link to them).
- **Sections**, in order: What it does, When to use, How to invoke, How it
  works, Design principles, Use cases, Tips, Example, Related, Prereqs, then
  any README sections that don't map (original heading kept), then Source.
  Heading matching is tolerant (`Invoke`, `Examples`, `Prerequisite: …` all
  map). Empty or missing sections are not rendered. A skill with no Prereqs
  section inherits its parent group README's (e.g. `kanban/README.md`).
- **Links.** Relative links become
  `https://github.com/KrishP147/skills/blob/master/<path>` (anchors kept);
  links to another skill's dir or README become `/<name>`, and
  `agents/README.md#<agent>` becomes `/<agent>`.
- **Chips:** author (cross-checked in tests against
  `THIRD_PARTY_LICENSES.md`), invocation (`user only` when the SKILL.md
  frontmatter has `disable-model-invocation: true`), model / tools / preloads
  (agents), prereqs, tested level.

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
source, readme), `<name>/index.html` detail page per skill/agent (so `/pair` resolves
statically), `404.html`, `style.css`, `filter.js`, `app.js`, `favicon.svg`. The build is
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
