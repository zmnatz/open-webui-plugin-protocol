"""Build the documentation site.

    uv run --group docs python tools/build_docs.py          # build into site/
    uv run --group docs python tools/build_docs.py serve    # preview at http://127.0.0.1:8000

The guides live in docs/. This script puts them, together with what lives elsewhere or has to be
generated, into build/docs/, then runs Zensical (zensical.toml) on that folder. The project's own
agent instructions in docs/agents/ stay in the repository but are not published. Nothing generated
is checked in, so none of it can drift from the repository:

- the root CHANGELOG, SECURITY, LICENSE and NOTICE files, and each example plugin's README;
- an examples overview, built from each plugin.yaml;
- the test catalogue, built from the test docstrings (docs/testing/writing.md, "Describe every test");
- the libraries table in docs/libraries.md, built from the library catalogue;
- llms.txt and llms-full.txt, for language models: the site's pages with their addresses, and
  the text of the guide in one file (https://llmstxt.org/);

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
SITE_URL = "https://zmnatz.github.io/open-webui-plugin-protocol/"
# The menu sections whose pages go, whole, into llms-full.txt: what someone using owpp reads.
FULL_TEXT_SECTIONS = ("Getting started", "Guide", "Commands")
# Link to the commit being built on CI (a pull request's own files), else to main.
REF = os.environ.get("GITHUB_SHA") or "main"

# Taken on a real Open-WebUI by tools/screenshots/run.py; see docs/screenshots.md.
SHOTS = DOCS / "screenshots" / "screenshots.json"

# Repository path -> the page that carries it on the site.
COPIED = {
    "CHANGELOG.md": "project/changelog.md",
    "SECURITY.md": "project/security.md",
    "LICENSE": "project/license.md",  # plain text: given a heading
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
            if uri.startswith("agents/"):
                continue  # project/agent instructions: in the repo, not on the site
            text = path.read_text()
            if uri == "libraries.md":
                text = text.replace(LIBRARY_MARKER, _library_table(), 1)
            pages[uri] = (f"docs/{uri}", text)
        else:
            (out / uri).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out / uri)
    copied = dict(COPIED)
    for path, uri in COPIED.items():
        text = (ROOT / path).read_text()
        pages[uri] = (path, text if path.endswith(".md") else f"# License\n\n{text}")
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
    _write_llms(out, pages)
    return problems


# ---- the library catalogue ----------------------------------------------------------------

LIBRARY_MARKER = "<!-- library catalogue -->"


def _library_table() -> str:
    """docs/libraries.md's table of what each library pulls in, what turns it on and what it
    carries, from src/owpp/libraries.py."""
    from owpp.libraries import table

    return table()


# ---- llms.txt ------------------------------------------------------------------------------


def _nav() -> list[tuple[str, list[tuple[str, str]]]]:
    """zensical.toml's menu as [(section, [(title, page)])]; a top-level page is its own section."""
    import tomllib

    nav = tomllib.loads((ROOT / "zensical.toml").read_text())["project"]["nav"]
    out = []
    for entry in nav:
        ((name, value),) = entry.items()
        if isinstance(value, str):
            out.append((name, [(name, value)]))
            continue
        flat = []
        for item in value:
            ((title, target),) = item.items()
            if isinstance(target, str):
                flat.append((title, target))
            else:  # a nested group: its pages, by name
                flat += [next(iter(i.items())) for i in target]
        out.append((name, flat))
    return out


def _page_url(page: str) -> str:
    return SITE_URL + ("" if page == "README.md" else page.removesuffix(".md") + "/").removesuffix(
        "index/"
    )


def _summary(text: str) -> str:
    """A page's first sentence of prose, as one line ("" when it opens with none)."""
    for para in re.sub(r"\A#[^\n]*\n+", "", text.lstrip()).split("\n\n"):
        para = para.strip()
        if not para or para.startswith("#"):
            continue  # a heading: the prose under it may follow
        if para.startswith(("```", "|", "!!!", "-", "<")):
            return ""
        line = " ".join(re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", para).split())
        m = re.match(r"(.+?[.:!?])(\s|$)", line)
        return m.group(1) if m else line
    return ""


def _write_llms(out: Path, pages: dict[str, tuple[str, str]]) -> None:
    """llms.txt (the pages, with their addresses) and llms-full.txt (the guide's text)."""
    index = [
        "# Open-WebUI plugin protocol (owpp)",
        "",
        "> Write, test and deploy Open-WebUI plugins (a function plus the tool and skills it "
        "installs) from a git repository, with the `owpp` CLI (`uvx owpp`). A plugin is a folder "
        "with a plugin.yaml; owpp bundles it into the single file Open-WebUI stores, tests it "
        "against a mock Open-WebUI, versions it and deploys it.",
        "",
        f"The whole guide as one text file: {SITE_URL}llms-full.txt. An agent skill for working "
        f"with owpp: {REPO_URL}/tree/main/skills/owpp. Every command's flags: `uvx owpp <command> "
        "--help`.",
    ]
    full = [
        "# Open-WebUI plugin protocol (owpp): the guide",
        "",
        f"The pages of {SITE_URL}, in menu order. Links inside are relative to the repository "
        f"{REPO_URL}.",
    ]
    for section, entries in _nav():
        index += ["", f"## {section}", ""]
        for title, page in entries:
            if page not in pages:
                continue
            text = pages[page][1]
            summary = _summary(text)
            index.append(f"- [{title}]({_page_url(page)})" + (f": {summary}" if summary else ""))
            if section in FULL_TEXT_SECTIONS:
                full += ["", "", f"<!-- {title}: {_page_url(page)} -->", "", text.strip()]
    (out / "llms.txt").write_text("\n".join(index) + "\n")
    (out / "llms-full.txt").write_text("\n".join(full) + "\n")


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
        "built (see [Describe every test](docs/testing/writing.md#describe-every-test)), so it always "
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


if __name__ == "__main__":
    sys.exit(main())
