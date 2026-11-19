"""Build the documentation site.

    uv run --group docs python tools/build_docs.py          # build into site/
    uv run --group docs python tools/build_docs.py serve    # preview at http://127.0.0.1:8000

The guides live in docs/. This script puts them, together with what lives elsewhere or has to be
generated, into build/docs/, then runs Zensical (zensical.toml) on that folder. Nothing generated
is checked in, so none of it can drift from the repository:

- the root CHANGELOG, SECURITY and NOTICE files, and each example plugin's README;
- an examples overview, built from each plugin.yaml;
- the test catalogue, built from the test docstrings (docs/testing.md, "Describe every test");
- the audit trail, built from `git log`.

Links are written for GitHub, relative to the file they are in. They are rewritten to the page
that carries the target on the site, or else to the file on GitHub. A link to a file or heading
that does not exist fails the build.

`serve` assembles once: after editing docs/, stop it and run it again.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = ROOT / "build" / "docs"  # zensical.toml: docs_dir
EXAMPLES = ROOT / "examples" / "plugins"
REPO_URL = "https://github.com/zmnatz/open-webui-plugin-protocol"
# Link to the commit being built on CI (a pull request's own files), else to main.
REF = os.environ.get("GITHUB_SHA") or "main"

# Taken on a real Open-WebUI by tools/screenshots/run.py; see docs/screenshots.md.
SHOTS = DOCS / "screenshots" / "screenshots.json"

# Repository path -> the page that carries it on the site.
COPIED = {
    "CHANGELOG.md": "project/changelog.md",
    "SECURITY.md": "project/security.md",
    "NOTICE.md": "project/notice.md",
}


def _plugins() -> list[Path]:
    return sorted(p.parent for p in EXAMPLES.glob("*/plugin.yaml"))


def _blob(path: str, line: int | None = None) -> str:
    kind = "tree" if (ROOT / path).is_dir() else "blob"
    return f"{REPO_URL}/{kind}/{REF}/{path}" + (f"#L{line}" if line else "")


# ---- assembling the pages ------------------------------------------------------------------


def assemble(out: Path = OUT) -> list[str]:
    """Write every page into `out`. Returns the broken links found, if any."""
    shutil.rmtree(out, ignore_errors=True)
    pages: dict[str, tuple[str, str]] = {}  # page -> (the repository file it came from, text)
    for path in sorted(DOCS.rglob("*")):
        if not path.is_file():
            continue
        uri = path.relative_to(DOCS).as_posix()
        if path.suffix == ".md":
            pages[uri] = (f"docs/{uri}", path.read_text())
        else:
            (out / uri).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out / uri)
    copied = dict(COPIED)
    for path, uri in COPIED.items():
        pages[uri] = (path, (ROOT / path).read_text())
    for plugin in _plugins():
        rel = plugin.relative_to(ROOT).as_posix()
        copied[f"{rel}/README.md"] = copied[rel] = f"examples/{plugin.name}.md"
        pages[f"examples/{plugin.name}.md"] = (
            f"{rel}/README.md",
            (plugin / "README.md").read_text() + _gallery(plugin.name, f"{rel}/README.md"),
        )
    # Generated pages write their links relative to the repository root.
    pages["examples/index.md"] = ("generated.md", _examples_index())
    pages["reference/test-catalogue.md"] = ("generated.md", _test_catalogue())
    pages["project/audit-trail.md"] = ("generated.md", _audit_trail())
    pages["reference/screenshots.md"] = ("generated.md", _screenshots_page())

    anchors = {uri: _anchors(text) for uri, (_, text) in pages.items()}
    problems: list[str] = []
    for uri, (origin, text) in pages.items():

        def relink(m: re.Match, origin=origin, uri=uri) -> str:
            target = _relink(m.group(2), origin, uri, pages, copied, anchors)
            if target is None:
                problems.append(f"{origin}: broken link {m.group(2)}")
                target = m.group(2)
            return m.group(1) + target + m.group(3)

        # Links in fenced code blocks are examples, not links: leave them alone.
        parts = re.split(r"(^```.*?^```)", text, flags=re.M | re.S)
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(r"(\]\()([^)\s]+)(\))", relink, parts[i])
        (out / uri).parent.mkdir(parents=True, exist_ok=True)
        (out / uri).write_text("".join(parts))
    return problems


def _relink(target, origin, page_uri, pages, copied, anchors) -> str | None:
    """A link written for the repository, made to work on the site. None: it is broken."""
    if re.match(r"[a-z]+:|/", target):
        return target  # a URL, or a site path
    path, _, fragment = target.partition("#")
    if not path:  # an anchor on this page
        return target if fragment in anchors[page_uri] else None
    repo_path = posixpath.normpath(posixpath.join(posixpath.dirname(origin), path))
    if repo_path.startswith("docs/") and repo_path[len("docs/") :] in pages:
        site = repo_path[len("docs/") :]
    elif repo_path.startswith("docs/") and (ROOT / repo_path).is_file():
        # An image or other file in docs/: copied beside the pages, so linked as it is.
        return posixpath.relpath(repo_path[len("docs/") :], posixpath.dirname(page_uri) or ".")
    elif repo_path in copied:
        site = copied[repo_path]
    elif (ROOT / repo_path).exists():
        return _blob(repo_path) + (f"#{fragment}" if fragment else "")
    else:
        return None
    if fragment and fragment not in anchors[site]:
        return None
    rel = posixpath.relpath(site, posixpath.dirname(page_uri) or ".")
    return rel + (f"#{fragment}" if fragment else "")


def _anchors(markdown: str) -> set[str]:
    """The ids of a page's headings, as the toc extension makes them."""
    text = re.sub(r"^```.*?^```", "", markdown, flags=re.M | re.S)
    found = set()
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*$", text, flags=re.M):
        plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading).replace("`", "")
        slug = re.sub(r"[^\w\s-]", "", plain).strip().lower()
        found.add(re.sub(r"[-\s]+", "-", slug))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", nargs="?", default="build", choices=["build", "serve", "pages"])
    args = parser.parse_args(argv)
    problems = assemble()
    for problem in problems:
        print(f"error  {problem}", file=sys.stderr)
    if problems:
        return 1
    if args.command == "pages":  # only assemble build/docs/
        return 0
    extra = ["--clean", "--strict"] if args.command == "build" else []
    return subprocess.call([sys.executable, "-m", "zensical", args.command, *extra], cwd=ROOT)


# ---- examples overview -----------------------------------------------------------------


def _examples_index() -> str:
    rows = []
    for plugin in _plugins():
        manifest = yaml.safe_load((plugin / "plugin.yaml").read_text()) or {}
        function = manifest.get("function", {})
        tests = sum(_count_tests(f) for f in (plugin / "tests").glob("test_*.py"))
        rows.append(
            f"| [{function.get('title', plugin.name)}](examples/plugins/{plugin.name}) | "
            f"{function.get('description', '')} | {tests} |"
        )
    return "\n".join(
        [
            "# Example plugins",
            "",
            "Working plugins in [`examples/plugins/`](examples/plugins), each with a README "
            "(what it is, how to test it, how to deploy it) and its own unit tests. Their tests, "
            "with the steps to repeat each one by hand, are in the "
            "[test catalogue](docs/reference/test-catalogue.md).",
            "",
            "| Plugin | What it does | Tests |",
            "| --- | --- | --- |",
            *rows,
            "",
        ]
    )


# ---- screenshots ---------------------------------------------------------------------------


def _shots() -> dict:
    return json.loads(SHOTS.read_text()) if SHOTS.exists() else {"shots": []}


def _figure(shot: dict, origin: str) -> list[str]:
    """One screenshot, linked relative to the file the text is written for."""
    path = posixpath.relpath(f"docs/screenshots/{shot['file']}", posixpath.dirname(origin) or ".")
    caption = _text(shot["caption"])
    return [f"![{caption}]({path})", "", f"*{caption}*", ""]


def _gallery(plugin: str, origin: str) -> str:
    shots = [s for s in _shots()["shots"] if s["plugin"] == plugin]
    if not shots:
        return ""
    meta = _shots()
    out = [
        "",
        "## Screenshots",
        "",
        f"Taken on Open-WebUI {meta.get('open_webui', '?')} on {meta.get('taken', '?')} by "
        f"`tools/screenshots/run.py` ([how](../../../docs/screenshots.md)).",
        "",
    ]
    for shot in shots:
        out += _figure(shot, origin)
    return "\n".join(out)


def _screenshots_page() -> str:
    meta = _shots()
    out = [
        "# Screenshots",
        "",
        "The plugins on a real Open-WebUI, taken by `tools/screenshots/run.py`: it starts "
        "Open-WebUI in Docker, deploys `examples/plugins` with `owpp deploy`, and follows the "
        "plugins' By hand steps in a browser ([how it works](docs/screenshots.md)). The "
        "[test catalogue](docs/reference/test-catalogue.md) shows each one beside the tests it "
        "illustrates.",
        "",
    ]
    if not meta["shots"]:
        return "\n".join(out + ["No screenshots have been taken yet.", ""])
    commit = meta.get("commit", "")
    out += [
        f"**Open-WebUI {meta.get('open_webui', '?')}** · taken {meta.get('taken', '?')} · from "
        + (f"[`{commit}`]({REPO_URL}/commit/{commit})" if commit else "an unknown commit"),
        "",
    ]
    plugin = None
    for shot in meta["shots"]:
        if shot["plugin"] != plugin:
            plugin = shot["plugin"]
            out += [f"## {plugin}", ""]
        out += _figure(shot, "generated.md")
        if shot["illustrates"]:
            names = ", ".join(f"`{name}`" for name in shot["illustrates"])
            out += [f"Illustrates {names}. Script: `{shot['script']}`.", ""]
        else:
            out += [f"Script: `{shot['script']}`.", ""]
    return "\n".join(out)


# ---- test catalogue --------------------------------------------------------------------


def _count_tests(path: Path) -> int:
    return len(_tests(path)[1])


def _tests(path: Path) -> tuple[str, list[dict]]:
    """The module docstring and every top-level test function of a test file."""
    tree = ast.parse(path.read_text())
    nodes = [(None, n) for n in tree.body]
    nodes += [(c.name, n) for c in tree.body if isinstance(c, ast.ClassDef) for n in c.body]
    found = []
    for cls, node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_"
        ):
            cases = 0
            for deco in node.decorator_list:
                if (
                    isinstance(deco, ast.Call)
                    and getattr(deco.func, "attr", "") == "parametrize"
                    and len(deco.args) > 1
                    and isinstance(deco.args[1], (ast.List, ast.Tuple))
                ):
                    cases = len(deco.args[1].elts)
            found.append(
                {
                    "name": f"{cls}.{node.name}" if cls else node.name,
                    "line": node.lineno,
                    "doc": ast.get_docstring(node) or "",
                    "cases": cases,
                }
            )
    return ast.get_docstring(tree) or "", found


def _split(doc: str) -> tuple[str, str]:
    what, _, hand = doc.partition("By hand:")
    what, hand = " ".join(what.split()), " ".join(hand.split())
    return _text(what), _text(hand[:1].upper() + hand[1:])


def _text(prose: str) -> str:
    """Docstring prose as Markdown: `code` stays code; everything else is literal text, so a
    test about `<script>` or `__N_NOTES__` shows those characters instead of acting on them."""
    parts = re.split(r"(`[^`]+`)", prose)
    for i in range(0, len(parts), 2):
        text = parts[i].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts[i] = re.sub(r"([\\*_\[\]])", r"\\\1", text)
    return "".join(parts)


def _title(name: str) -> str:
    text = name.removeprefix("test_").replace("_", " ")
    return text[:1].upper() + text[1:]


def _test_catalogue() -> str:
    out: list[str] = []
    total = described = manual = pictured = 0
    for plugin in _plugins():
        files = sorted((plugin / "tests").glob("test_*.py"))
        if not files:
            continue
        out += [f"## {plugin.name}", ""]
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            module_doc, tests = _tests(path)
            out += [f"### [`{path.name}`]({_blob(rel)})", ""]
            if module_doc:
                out += [" ".join(module_doc.split()), ""]
            for test in tests:
                total += 1
                what, hand = _split(test["doc"])
                described += bool(what)
                repeatable = hand and not re.match(
                    r"(not (reliably )?repeatable|hard to catch)", hand, re.I
                )
                manual += bool(repeatable)
                cases = f" · {test['cases']} cases" if test["cases"] else ""
                out += [
                    f"#### {_title(test['name'])}",
                    "",
                    f"[`{test['name']}`]({_blob(rel, test['line'])}){cases}",
                    "",
                    what or '!!! warning "No description"\n    This test has no docstring yet.',
                    "",
                ]
                if hand:
                    kind = "tip" if repeatable else "note"
                    label = "By hand" if repeatable else "By hand: not a live check"
                    out += [f'!!! {kind} "{label}"', f"    {hand}", ""]
                elif what:
                    out += ['!!! warning "No by-hand steps"', "    Add a `By hand:` paragraph.", ""]
                for s in _shots()["shots"]:
                    if s["plugin"] == plugin.name and test["name"] in s["illustrates"]:
                        out += _figure(s, "generated.md")
                        pictured += 1

    head = [
        "# Test catalogue",
        "",
        "Every unit test of the example plugins: what it checks, and how to see the same thing "
        "on a live Open-WebUI. It is built from the tests' docstrings each time the site is "
        "built (see [Describe every test](docs/testing.md#describe-every-test)), so it always "
        "matches the code it links to.",
        "",
        "Before a release, a reviewer can walk the green **By hand** boxes on a test instance. "
        "Grey boxes say why a test has no live equivalent.",
        "",
        f"**{total}** tests · **{described}** described · **{manual}** with live steps "
        f"· **{total - manual}** checked only by the unit test "
        f"· **{pictured}** [screenshots](docs/reference/screenshots.md) from a real Open-WebUI",
        "",
    ]
    return "\n".join(head + out + _library_tests())


def _library_tests() -> list[str]:
    rows = []
    for path in sorted((ROOT / "tests").glob("*.py")):
        module_doc, tests = _tests(path)
        if not tests:
            continue
        rel = path.relative_to(ROOT).as_posix()
        documented = sum(bool(t["doc"]) for t in tests)
        summary = " ".join(module_doc.split()).replace("|", "\\|")
        rows.append(f"| [`{path.name}`]({_blob(rel)}) | {summary} | {len(tests)} | {documented} |")
    return [
        "## The library's own tests",
        "",
        "The tests in [`tests/`](tests) cover owpp itself (the bundler, runtime, "
        "libraries, deploy and CLI) against stubbed Open-WebUI modules, so they have no live "
        "equivalent step by step. Run them with `uv run pytest`.",
        "",
        "| File | What it covers | Tests | With a docstring |",
        "| --- | --- | --- | --- |",
        *rows,
        "",
    ]


# ---- audit trail -----------------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def _audit_trail() -> str:
    head = [
        "# Audit trail",
        "",
        "Every change to this repository, newest first, as recorded in git: when, by whom, "
        "why (the commit message), and which files it touched. It is generated from `git log` "
        "each time the site is built. The [changelog](CHANGELOG.md) says what changed for "
        "users, and [decisions](docs/decisions.md) why things are the way they are.",
        "",
    ]
    try:
        if _git("rev-parse", "--is-shallow-repository").strip() == "true":
            head += [
                '!!! warning "Shallow clone"',
                "    Only part of the history was available to this build.",
                "",
            ]
        log = _git("log", "--format=%x1e%H%x1f%h%x1f%an%x1f%ad%x1f%s%x1f%b", "--date=iso-strict")
    except (OSError, subprocess.CalledProcessError):
        return "\n".join(head + ["The git history was not available to this build.", ""])

    out = []
    for record in log.split("\x1e")[1:]:
        sha, short, author, date, subject, body = record.split("\x1f", 5)
        stat = _git("show", "--format=", "--numstat", sha).strip().splitlines()
        changes = []
        for line in stat:
            added, removed, path = line.split("\t", 2)
            changes.append(f"    | `{path}` | {added} | {removed} |")
        body = re.sub(r"\s*<[^<>\s]+@[^<>\s]+>", "", body)  # never publish an email address
        lines, trailers = [], []
        for line in body.strip().splitlines():
            is_trailer = re.match(r"[\w-]+-by: ", line, re.I)
            (trailers if is_trailer else lines).append(line)
        out += [
            f"## {_text(subject)}",
            "",
            f"[`{short}`]({REPO_URL}/commit/{sha}) · {date[:10]} · {author}",
            "",
        ]
        if lines:
            out += ["\n".join(_text(line) for line in lines).strip(), ""]
        for trailer in trailers:
            key, value = trailer.split(":", 1)
            out += [f"- {key}: {_text(value.strip())}"]
        if trailers:
            out += [""]
        out += [
            f'??? abstract "{len(changes)} file(s) changed"',
            "    | File | Added | Removed |",
            "    | --- | --- | --- |",
            *changes,
            "",
        ]
    return "\n".join(head + out)


if __name__ == "__main__":
    sys.exit(main())
