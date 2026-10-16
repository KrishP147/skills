"""Keep deploy-portfolio.yml `paths:` covering everything build_site.py reads."""
import ast
import glob
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "deploy-portfolio.yml")


def local_imports(name):
    with open(os.path.join(SCRIPTS, name + ".py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module]
        else:
            continue
        for n in names:
            top = n.split(".")[0]
            if os.path.isfile(os.path.join(SCRIPTS, top + ".py")):
                found.add(top)
    return found


def closure(start):
    seen, todo = set(), [start]
    while todo:
        cur = todo.pop()
        for m in local_imports(cur):
            if m not in seen:
                seen.add(m)
                todo.append(m)
    return seen


def glob_to_re(pat):
    out, i = [], 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
        i += 1
    return re.compile("".join(out))


def workflow_paths():
    with open(WORKFLOW, encoding="utf-8") as f:
        text = f.read()
    block = re.search(r"^\s*paths:\s*\n((?:\s*-\s*\"[^\"]*\"\s*\n)+)", text, re.M)
    return re.findall(r'-\s*"([^"]*)"', block.group(1))


def covered(path, pats):
    return any(glob_to_re(p).fullmatch(path) for p in pats)


class DeployPaths(unittest.TestCase):
    def test_build_site_and_imports_covered(self):
        pats = workflow_paths()
        mods = {"build_site"} | closure("build_site")
        for m in sorted(mods):
            self.assertTrue(covered("scripts/%s.py" % m, pats), m)

    def test_hooks_covered(self):
        pats = workflow_paths()
        files = glob.glob(os.path.join(ROOT, "hooks", "*.py"))
        self.assertTrue(files)
        for f in files:
            rel = os.path.relpath(f, ROOT).replace(os.sep, "/")
            self.assertTrue(covered(rel, pats), rel)

    def test_closure_sanity(self):
        want = {"site_map", "site_workflows", "flow_svg", "md_render", "lint", "site_detail"}
        self.assertTrue(want <= closure("build_site"), want - closure("build_site"))

    def test_glob_translator(self):
        self.assertTrue(glob_to_re("scripts/site_*.py").fullmatch("scripts/site_map.py"))
        self.assertFalse(glob_to_re("*/SKILL.md").fullmatch("a/b/SKILL.md"))


if __name__ == "__main__":
    unittest.main()
