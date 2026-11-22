"""The bundler: headers, function folders, tool and skills, built-in libraries, function types."""

from __future__ import annotations

import json
import re

import pytest
from conftest import DOCS, EXAMPLES, FILTER, embedded, fake_sources, write_tree

from owpp.bundle import (
    FunctionFile,
    bundle_function,
    check_frontmatter,
    function_type,
    load_function_files,
    parse_frontmatter,
    parse_skill,
)
from owpp.cli import check_bundle
from owpp.deploy import MANAGED_BY, Result, plan_deploy, render_report
from owpp.errors import OwppError


class TestFrontmatterAndIds:
    def test_reads_the_one_line_header_values(self):
        meta = parse_frontmatter(FILTER)
        assert meta["title"] == "Demo Filter"
        assert meta["description"] == "A demo filter."

    def test_uses_the_lowercased_filename_stem_as_the_function_id(self, functions_dir):
        files = load_function_files(functions_dir({"one.py": FILTER, "Two_Fn.py": FILTER}))
        assert [f.id for f in files] == ["two_fn", "one"]
        assert files[0].name == "Demo Filter"

    def test_refuses_a_header_value_open_webui_cannot_read(self, functions_dir):
        folded = FILTER.replace(
            "description: A demo filter.", "description: >\n  A demo\n  filter."
        )
        with pytest.raises(OwppError, match="one `key: value` per line"):
            check_frontmatter("x.py", folded)
        literal = FILTER.replace("description: A demo filter.", "description: |\n  A demo")
        with pytest.raises(OwppError, match="one `key: value` per line"):
            check_frontmatter("x.py", literal)
        with pytest.raises(OwppError, match=r"x\.py"):
            load_function_files(functions_dir({"x.py": folded}))
        check_frontmatter("x.py", FILTER)  # no error

    def test_every_example_header_is_on_one_line(self):
        files = load_function_files(EXAMPLES, fake_sources())
        assert len(files) >= 3
        for f in files:
            assert len(f.description) > 20, f"{f.file} has a description"
            assert ">" not in f.description, f"{f.file} description is not a block marker"

    def test_global_true_in_the_docstring_only(self, functions_dir):
        with_global = FILTER.replace("author: me\n", "author: me\nglobal: true\n")
        not_global = FILTER.replace("author: me\n", "author: me\nglobal: false\n")
        files = load_function_files(
            functions_dir({"a.py": with_global, "b.py": FILTER, "c.py": not_global})
        )
        assert [(f.id, f.want_global) for f in files] == [("a", True), ("b", False), ("c", False)]

    def test_flags_an_id_open_webui_would_reject(self):
        plan = plan_deploy([FunctionFile(id="bad-name", file="bad-name.py", content="x")], [])
        assert plan[0].action == "invalid"

    def test_treats_trailing_whitespace_and_crlf_as_unchanged(self):
        live = [
            {
                "id": "a",
                "content": "x = 1\r\n\n",
                "meta": {"description": "d", "managed_by": MANAGED_BY},
            }
        ]
        plan = plan_deploy(
            [FunctionFile(id="a", file="a.py", content="x = 1\n", description="d")], live
        )
        assert plan[0].action == "unchanged"

    def test_reads_headers_line_by_line_like_open_webui(self):
        header = '"""\ntitle: A\nauthor: @G30\nglobal: true\nversion: 1.2.3\n"""\n'
        assert parse_frontmatter(header) == {
            "title": "A",
            "author": "@G30",
            "global": True,
            "version": "1.2.3",
        }


@pytest.fixture
def folder(tmp_path):
    """A plugins folder with one plugin `demo`: manifest lines go under `function:`."""

    def make(manifest: str, parts: dict[str, str]):
        body = "\n".join(
            f"  {line}"
            for line in manifest.split("\n")
            if line.strip() and not line.startswith("#")
        )
        write_tree(tmp_path / "demo", {"plugin.yaml": f"function:\n{body}\n", **parts})
        return tmp_path

    return make


@pytest.fixture
def plugin(tmp_path):
    """A plugins folder with one plugin `viz` made from a full manifest and files."""

    def make(manifest: str, files: dict[str, str | bytes] | None = None):
        write_tree(tmp_path / "viz", {"plugin.yaml": manifest, **(files or {})})
        return tmp_path

    return make


class TestFunctionFolders:
    def test_bundles_the_manifest_as_the_header_above_function_py(self, folder):
        dir_ = folder(
            "# note\ntitle: Demo\nglobal: true\ndescription: One line.\n",
            {"function.py": "A = 1\n", "page.html": "<p>x</p>\n"},
        )
        assert (
            bundle_function(dir_ / "demo")
            == '"""\ntitle: Demo\nglobal: true\ndescription: One line.\n"""\nA = 1\n'
        )

    def test_inlines_file_tokens_from_the_plugin_folder(self, folder):
        dir_ = folder(
            "title: Demo\n",
            {"function.py": 'PAGE = """{{file:page.html}}"""\n', "page.html": "<p>x</p>\n"},
        )
        assert 'PAGE = """<p>x</p>\n"""' in bundle_function(dir_ / "demo")

    def test_refuses_a_missing_include_a_multiline_value_and_no_code(self, folder, tmp_path):
        with pytest.raises(OwppError, match=r"nope\.html"):
            bundle_function(folder("title: D\n", {"function.py": "{{file:nope.html}}\n"}) / "demo")

    def test_refuses_a_multiline_header_value(self, folder):
        d = folder("title: D\ndescription: |\n  a\n  b\n", {"function.py": "x\n"})
        with pytest.raises(OwppError, match="one-line"):
            bundle_function(d / "demo")

    def test_refuses_a_plugin_without_function_py(self, folder):
        with pytest.raises(OwppError, match=r"no function\.py"):
            bundle_function(folder("title: D\n", {}) / "demo")

    def test_loads_folders_and_flat_files_together_by_folder_name(self, folder):
        d = folder(
            "title: Demo\nglobal: true\ndescription: d\n",
            {"function.py": "class Filter:\n    pass\n"},
        )
        (d / "flat.py").write_text(FILTER)
        files = load_function_files(d)
        assert [(f.id, f.file, f.want_global) for f in files] == [
            ("demo", "demo/", True),
            ("flat", "flat.py", False),
        ]

    def test_skips_a_plugin_with_nothing_to_deploy_and_refuses_a_tool_without_a_function(
        self, folder
    ):
        d = folder("title: Demo\n", {"function.py": "class Event:\n    pass\n"})
        write_tree(d / "empty", {"plugin.yaml": "{}\n"})
        assert [f.id for f in load_function_files(d)] == ["demo"]
        write_tree(d / "viz", {"plugin.yaml": "tool:\n  from: function\n"})
        with pytest.raises(OwppError, match="need a `function:` section"):
            load_function_files(d)

    def test_yaml_scalars_are_not_reinterpreted(self, folder):
        # YAML 1.1 would turn `on` into True and 12:30 into 750; the header keeps the text.
        d = folder(
            "title: 'on'\nversion: 12:30\nnote: no\n", {"function.py": "class Event:\n    pass\n"}
        )
        assert bundle_function(d / "demo").startswith(
            '"""\ntitle: on\nversion: 12:30\nnote: no\n"""\n'
        )


class TestToolAndSkills:
    def test_a_tool_only_plugin_is_a_stub_parent_plus_the_runtime(self, plugin):
        d = plugin(
            "function:\n  title: Viz\n  global: true\ntool:\n  access: public\n  title: Viz Tool\n",
            {"tool.py": 'class Tools:\n    note = "quote \\" and \\\\"\n'},
        )
        (fn,) = load_function_files(d)
        assert fn.id == "viz"
        assert fn.want_global is True
        assert fn.content.startswith('"""\ntitle: Viz\nglobal: true\n"""\n')
        assert "class Filter:" in fn.content
        assert fn.content.endswith("_plugin_start()\n")
        tool = embedded(fn.content)["tools"][0]
        assert (tool["id"], tool["access"], tool["self"]) == ("viz", "public", False)
        assert tool["content"].startswith('"""\ntitle: Viz Tool\n"""\nclass Tools:')
        assert 'quote \\" and \\\\' in tool["content"]

    def test_the_stub_parent_has_only_the_valves_that_apply(self, plugin, tmp_path):
        both = plugin(
            "function:\n  title: T\ntool:\n  id: t\n  valves: {level: strict}\n",
            {"tool.py": "class Tools:\n    pass\n", "skills/s/SKILL.md": "body\n"},
        )
        (fn,) = load_function_files(both)
        for v in ("INSTALL_TOOLS", "INSTALL_SKILLS", "TOOL_VALVES"):
            assert f"{v}:" in fn.content, v
        assert embedded(fn.content)["tools"][0]["valves"] == {"level": "strict"}

    def test_skills_only_has_no_tool_valves(self, plugin):
        d = plugin("function:\n  title: T\n", {"skills/s/SKILL.md": "body\n"})
        (sk,) = load_function_files(d)
        assert "INSTALL_SKILLS:" in sk.content
        assert "INSTALL_TOOLS:" not in sk.content and "TOOL_VALVES:" not in sk.content

    def test_tool_valves_must_be_a_map(self, plugin):
        d = plugin(
            "function:\n  title: T\ntool:\n  id: t\n  valves: [1]\n",
            {"tool.py": "class Tools:\n    pass\n"},
        )
        with pytest.raises(OwppError, match=r"tool\.valves must be a map"):
            load_function_files(d)

    def test_shared_py_goes_in_front_of_function_and_tool_in_a_fixed_order(self, plugin):
        d = plugin(
            "function:\n  title: T\ntool:\n  id: t\n  title: T\ninclude: [routes]\n",
            {
                "shared.py": "SHARED = 1\n",
                "function.py": "class Filter:\n    pass\n",
                "tool.py": "class Tools:\n    pass\n",
            },
        )
        (fn,) = load_function_files(d)
        code = fn.content.split("_PLUGIN = ")[0]
        at = code.index
        # header, then the built-in library, then shared.py, then function.py
        assert code.startswith('"""\ntitle: T')
        assert at("def plugin_mount(") < at("SHARED = 1") < at("class Filter:")
        tool = embedded(fn.content)["tools"][0]["content"]
        assert tool.startswith('"""\ntitle: T\n"""\nSHARED = 1\nclass Tools:')
        assert "def plugin_mount(" not in tool  # include applies to the function only

    def test_from_shared_imports_are_removed_once_shared_py_is_inlined(self, plugin):
        """`from shared import NAME` is a real import for the editor and the tests; in the bundle
        shared.py is already above the file, so the line goes, however many lines it spans."""
        d = plugin(
            "function:\n  title: T\ntool:\n  id: t\n  title: T\n",
            {
                "shared.py": "import json\n\nSHARED = 1\nOTHER = json.dumps(2)\n",
                "function.py": "# top\nfrom shared import SHARED\n\nclass Filter:\n    x = SHARED\n",
                "tool.py": "from shared import (\n    OTHER,\n    SHARED,\n)\n\nclass Tools:\n    y = OTHER\n",
            },
        )
        (fn,) = load_function_files(d)
        tool = embedded(fn.content)["tools"][0]["content"]
        for code in (fn.content, tool):
            assert "from shared" not in code and "    OTHER,\n" not in code
            assert code.index("SHARED = 1") < code.index("class ")
        assert "# top\n\nclass Filter:" in fn.content
        assert "\n\nclass Tools:" in tool

    @pytest.mark.parametrize(
        ("source", "error"),
        [
            ("from shared import SHARED as S\n", r"function\.py:1: .*`as`"),
            ("import shared\n", r"function\.py:1: .*`from shared import NAME`"),
            ("def f():\n    from shared import SHARED\n", r"function\.py:2: .*top level"),
            ("from shared import *\n", r"function\.py:1: .*import \*`: name what you use"),
            (
                "from shared import MISSING\n",
                r"function\.py:1: .*MISSING.*not defined in shared\.py",
            ),
            ("from shared import SHARED\nSHARED = 2\n", r"function\.py:2: .*SHARED.*shared\.py"),
            ("def SHARED():\n    pass\n", r"function\.py:1: .*SHARED.*shared\.py"),
            ("from tool import X\n", r"function\.py:1: .*tool\.py.*separate.*shared\.py"),
            ("import tool\n", r"function\.py:1: .*tool\.py.*separate.*shared\.py"),
            ("from . import tool\n", r"function\.py:1: .*tool\.py.*separate.*shared\.py"),
            ("from .tool import X\n", r"function\.py:1: .*tool\.py.*separate.*shared\.py"),
            ("from .helpers import X\n", r"function\.py:1: a relative import has no package"),
        ],
    )
    def test_refuses_imports_that_would_break_once_flattened(self, plugin, source, error):
        """The bundler removes `from shared import` lines; each refused form would leave a name
        undefined, or import something that is not there, once the files are one module."""
        d = plugin("function:\n  title: T\n", {"shared.py": "SHARED = 1\n", "function.py": source})
        with pytest.raises(OwppError, match=error):
            load_function_files(d)

    def test_owpp_lib_imports_are_removed_and_their_libraries_are_inlined_above(self, plugin):
        """`from owpp.lib import NAME` resolves for an editor and tests; Open-WebUI has no owpp,
        so the line goes and the library is already in the bundle, from shared.py too."""
        d = plugin(
            "function:\n  title: T\ninclude: [routes, chat_data]\n",
            {
                "shared.py": "from owpp.lib import plugin_chat_read\n\nREAD = plugin_chat_read\n",
                "function.py": "from owpp.lib import (\n    plugin_mount,\n)\n\nclass Filter:\n    m = plugin_mount\n",
            },
        )
        (fn,) = load_function_files(d)
        c = fn.content
        assert "from owpp" not in c and "from ." not in c
        assert c.index("def plugin_mount(") < c.index("READ = ") < c.index("class Filter:")

    @pytest.mark.parametrize(
        ("source", "error"),
        [
            ("from owpp.lib import plugin_mount as m\n", r"function\.py:1: .*`as`"),
            ("import owpp.lib\n", r"function\.py:1: .*`from owpp\.lib import NAME`"),
            ("from owpp import lib\n", r"function\.py:1: .*`from owpp\.lib import NAME`"),
            ("from owpp.runtime.lib.plugin_core import plugin_app\n", r"function\.py:1: .*owpp"),
            ("def f():\n    from owpp.lib import plugin_app\n", r"function\.py:2: .*top level"),
            ("from owpp.lib import *\n", r"function\.py:1: .*name what you use"),
            ("from owpp.lib import nope\n", r"function\.py:1: owpp\.lib has no nope"),
            (
                "from owpp.lib import plugin_chat_read\n",
                r"function\.py:1: plugin_chat_read is from the chat_data library.*include",
            ),
            (
                "from owpp.lib import plugin_ensure\n",
                r"function\.py:1: plugin_ensure is the plugin runtime's.*tool or skills",
            ),
        ],
    )
    def test_refuses_owpp_imports_that_would_break_once_flattened(self, plugin, source, error):
        """owpp is not installed in Open-WebUI: only a top-level `from owpp.lib import NAME`,
        for a name whose library is in the bundle, can be removed and still work."""
        d = plugin("function:\n  title: T\ninclude: [routes]\n", {"function.py": source})
        with pytest.raises(OwppError, match=error):
            load_function_files(d)

    @pytest.mark.parametrize(
        ("source", "error"),
        [
            (
                "class Filter:\n    m = plugin_mount\n",
                r"function\.py:2: plugin_mount is used without importing it: add "
                r"`from owpp\.lib import plugin_mount` \(`owpp migrate`",
            ),
            (
                "class Filter:\n    x = SHARED\n",
                r"function\.py:2: SHARED is shared\.py's, used without importing it: add "
                r"`from shared import SHARED` \(`owpp migrate`",
            ),
            (
                "class Filter:\n    x = json.dumps(1)\n",
                r"function\.py:2: json is imported in shared\.py, not here: import it",
            ),
        ],
    )
    def test_refuses_names_used_without_their_import(self, plugin, source, error):
        """Before protocol 0.5 a plugin used them as globals. Bundled they would still be there,
        but the file would not read as Python on its own; owpp migrate adds the imports."""
        d = plugin(
            "function:\n  title: T\ninclude: [routes]\n",
            {"shared.py": "import json\n\nSHARED = 1\n", "function.py": source},
        )
        with pytest.raises(OwppError, match=error):
            load_function_files(d)

    def test_a_tool_checks_its_imports_against_its_own_include(self, plugin):
        """The tool is its own bundle, with the libraries `tool.include` asks for."""
        files = {
            "function.py": "class Filter:\n    pass\n",
            "tool.py": "from owpp.lib import plugin_chat_read\n\nclass Tools:\n    pass\n",
        }
        bad = plugin("function:\n  title: T\ninclude: [chat_data]\ntool:\n  id: t\n", files)
        with pytest.raises(OwppError, match=r"tool\.py:1: .*chat_data.*tool\.include"):
            load_function_files(bad)
        good = plugin("function:\n  title: T\ntool:\n  id: t\n  include: [chat_data]\n", files)
        load_function_files(good)

    @pytest.mark.parametrize(
        "source",
        [
            "from os.path import join as SHARED\n",
            "for SHARED in range(2):\n    pass\n",
            "with open(__file__) as SHARED:\n    pass\n",
            "try:\n    pass\nexcept Exception as SHARED:\n    pass\n",
            "if (SHARED := 3):\n    pass\n",
            "def f():\n    global SHARED\n    SHARED = 2\n",
            "match 1:\n    case SHARED:\n        pass\n",
            "from json import loads as SHARED\nfrom shared import SHARED\n",
        ],
    )
    def test_any_binding_of_a_shared_py_name_is_refused(self, plugin, source):
        """Not only an assignment or a def: every way a module binds a name would replace
        shared.py's once the two are one module."""
        d = plugin("function:\n  title: T\n", {"shared.py": "SHARED = 1\n", "function.py": source})
        with pytest.raises(OwppError, match=r"SHARED is defined in shared\.py and bound here too"):
            load_function_files(d)

    def test_a_name_shared_py_imports_may_be_imported_here_too(self, plugin):
        """The same module, imported in both: one object, nothing replaced."""
        d = plugin(
            "function:\n  title: T\n",
            {
                "shared.py": "import json\n\nX = json\n",
                "function.py": "import json\n\nclass Filter:\n    j = json\n",
            },
        )
        load_function_files(d)

    def test_tool_py_cannot_import_from_function_py(self, plugin):
        """They are separate modules in Open-WebUI, so the import would find nothing."""
        d = plugin(
            "function:\n  title: T\ntool:\n  id: t\n  title: T\n",
            {
                "function.py": "class Filter:\n    pass\n",
                "tool.py": "from function import Filter\n\nclass Tools:\n    pass\n",
            },
        )
        with pytest.raises(OwppError, match=r"tool\.py:1: .*function\.py.*separate.*shared\.py"):
            load_function_files(d)

    def test_from_shared_without_a_shared_py(self, plugin):
        """There is nothing to put above the file, so the name would be undefined."""
        d = plugin("function:\n  title: T\n", {"function.py": "from shared import X\n"})
        with pytest.raises(OwppError, match=r"function\.py:1: .*no shared\.py"):
            load_function_files(d)

    def test_future_imports_move_above_the_libraries_and_shared_py(self, plugin):
        d = plugin(
            "function:\n  title: T\ninclude: [jobs]\n",
            {
                "shared.py": "SHARED = 1\n",
                "function.py": "# c\nfrom __future__ import annotations\n\nclass Event:\n    pass\n",
            },
        )
        (fn,) = load_function_files(d)
        c = fn.content
        assert c.count("from __future__ import annotations") == 1
        assert 0 < c.index("from __future__") < c.index("import asyncio as _asyncio")
        assert c.index("from __future__") < c.index("SHARED = 1")

    def test_tool_include_applies_to_the_tool_bundle_only(self, plugin):
        d = plugin(
            "function:\n  title: T\ninclude: [routes]\ntool:\n  id: t\n  title: T\n  include: [chat_data]\n",
            {"function.py": "class Filter:\n    pass\n", "tool.py": "class Tools:\n    pass\n"},
        )
        (fn,) = load_function_files(d)
        code = fn.content.split("_PLUGIN = ")[0]
        tool = embedded(fn.content)["tools"][0]["content"]
        assert "def plugin_mount(" in code and "def plugin_chat_read(" not in code
        assert "async def plugin_chat_read(" in tool and "def plugin_mount(" not in tool
        assert "include:" not in tool  # not written into the tool's header

    def test_a_tool_gets_the_runtime_with_only_the_ids_to_remove(self, plugin):
        d = plugin(
            "function:\n  title: T\ntool:\n  id: t\n  title: T\n",
            {"tool.py": "class Tools:\n    pass\n", "skills/s/SKILL.md": "x\n"},
        )
        tool = embedded(load_function_files(d)[0].content)["tools"][0]["content"]
        assert tool.endswith("_plugin_start()\n")
        assert embedded(tool) == {"tools": [{"id": "t"}], "skills": [{"id": "s"}]}

    def test_the_tool_can_reuse_the_functions_own_bundle(self, plugin):
        d = plugin(
            "function:\n  title: Draw\ntool:\n  id: Draw_Tool\n  from: function\n",
            {"function.py": "class Filter:\n    pass\n\nclass Tools:\n    pass\n"},
        )
        (fn,) = load_function_files(d)
        tool = embedded(fn.content)["tools"][0]
        assert (tool["id"], tool["self"], tool["content"]) == ("draw_tool", True, None)
        assert "class Tools:" in fn.content

    def test_skills_read_name_description_and_access_from_the_front_matter(self, plugin):
        visualize = "---\nname: Visualize\ndescription: Draw it.\naccess: public\n---\n# Body\n"
        d = plugin(
            "function:\n  title: Viz\n",
            {"skills/visualize/SKILL.md": visualize, "skills/other/SKILL.md": "No front matter\n"},
        )
        (fn,) = load_function_files(d)

        def md(text):
            return [{"path": "SKILL.md", "content": text}]

        assert embedded(fn.content)["skills"] == [
            {
                "id": "other",
                "name": "other",
                "description": "",
                "access": "private",
                "files": md("No front matter\n"),
            },
            {
                "id": "visualize",
                "name": "Visualize",
                "description": "Draw it.",
                "access": "public",
                "files": md(visualize),
            },
        ]

    def test_a_skill_folder_keeps_its_supporting_files_binary_ones_as_base64(self, plugin):
        d = plugin(
            "function:\n  title: Viz\n",
            {
                "skills/big/SKILL.md": "---\nname: Big\n---\n# Body\n",
                "skills/big/references/palette.md": "colours\n",
                "skills/big/templates/a.js": "// a\n",
                "skills/big/logo.bin": bytes([0xFF, 0xFE, 0x00, 0x80]),
            },
        )
        (fn,) = load_function_files(d)
        (skill,) = embedded(fn.content)["skills"]
        assert [(f["path"], f.get("encoding", "utf8")) for f in skill["files"]] == [
            ("SKILL.md", "utf8"),
            ("logo.bin", "base64"),
            ("references/palette.md", "utf8"),
            ("templates/a.js", "utf8"),
        ]
        assert skill["files"][0]["content"] == "---\nname: Big\n---\n# Body\n"  # front matter kept

    def test_refuses_a_bad_skill_id_and_a_missing_skill_md(self, plugin, tmp_path):
        d = plugin("function:\n  title: V\n", {"skills/Bad Id/SKILL.md": "x"})
        with pytest.raises(OwppError, match="skill id"):
            load_function_files(d)
        write_tree(tmp_path / "other" / "viz", {"plugin.yaml": "function:\n  title: V\n"})
        (tmp_path / "other" / "viz" / "skills" / "empty").mkdir(parents=True)
        with pytest.raises(OwppError, match=r"SKILL\.md is missing"):
            load_function_files(tmp_path / "other")

    def test_symlinks_in_a_skill_folder_are_not_followed(self, plugin, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("secret")
        d = plugin("function:\n  title: V\n", {"skills/s/SKILL.md": "x\n"})
        (d / "viz" / "skills" / "s" / "leak.txt").symlink_to(secret)
        (fn,) = load_function_files(d)
        assert [f["path"] for f in embedded(fn.content)["skills"][0]["files"]] == ["SKILL.md"]

    def test_parse_skill_reads_front_matter(self):
        fm, body = parse_skill("x", "---\nname: a\n---\nbody\n")
        assert fm == {"name": "a"} and body == "body\n"
        with pytest.raises(OwppError, match="not valid YAML"):
            parse_skill("x", "---\nname: [a\n---\nbody\n")


def _data(code, var):
    return json.loads(json.loads(re.search(rf'{var} = _json\.loads\((".*")\)\n', code).group(1)))


class TestStaticAndTemplates:
    """static/: files served as they are. templates/: files the function renders, never served."""

    FN = {"function.py": "class Filter:\n    pass\n"}

    def test_a_static_folder_brings_in_routes_and_static_and_embeds_its_files(self, plugin):
        d = plugin(
            "function:\n  title: T\nstatic:\n  prefix: /demo\n",
            {
                **self.FN,
                "static/app.js": "console.log(1)\n",
                "static/img/a.bin": "x",
                "static/img/b.bin": bytes([0xFF, 0x00]),
            },
        )
        (fn,) = load_function_files(d)
        c = fn.content
        assert c.index("def plugin_mount(") < c.index("def plugin_static_serve(")
        assert c.index("plugin_static_ensure()\n") < c.index("class Filter:")
        data = _data(c, "_STATIC")
        assert (data["prefix"], data["access"]) == ("/demo", "user")
        assert sorted(data["files"]) == ["app.js", "img/a.bin", "img/b.bin"]
        assert data["files"]["img/b.bin"]["encoding"] == "base64"
        assert "plugin_template_text" not in c  # no templates folder, no templates library

    def test_a_templates_folder_is_embedded_and_never_served(self, plugin):
        d = plugin(
            "function:\n  title: T\n",
            {
                **self.FN,
                "templates/page.html": "<p>__TOKEN__</p>\n",
                "templates/img/b.bin": bytes([0xFF, 0x00]),
            },
        )
        (fn,) = load_function_files(d)
        c = fn.content
        assert c.index("def plugin_template_text(") < c.index("class Filter:")
        data = _data(c, "_TEMPLATES")
        assert (
            data["page.html"]["content"] == "<p>__TOKEN__</p>\n"
            and data["img/b.bin"]["encoding"] == "base64"
        )
        for served in ("def plugin_mount(", "def plugin_static_serve(", "plugin_function_id"):
            assert served not in c, (
                served
            )  # nothing is mounted: no routes, no static, not even core

    def test_a_template_can_be_read_back_by_the_bundled_function(self, plugin):
        d = plugin(
            "function:\n  title: T\n",
            {
                "function.py": (
                    "from owpp.lib import plugin_template_text\n\n"
                    'class Event:\n    pass\n\nPAGE = plugin_template_text("page.html")\n'
                ),
                "templates/page.html": 'a "quoted" \\ page\n',
            },
        )
        ns: dict = {}
        exec(compile(load_function_files(d)[0].content, "bundle.py", "exec"), ns)
        assert ns["PAGE"] == 'a "quoted" \\ page\n' and ns["plugin_template_files"]() == [
            "page.html"
        ]

    def test_a_tool_reads_the_templates_when_it_includes_them(self, plugin):
        """tool.py has no other way to keep a page out of a Python string, now that
        {{file:NAME}} is deprecated; a tool that does not ask is not given the files."""
        d = plugin(
            "function:\n  title: T\ntool:\n  id: t\n  include: [templates]\n",
            {
                "function.py": "class Filter:\n    pass\n",
                "tool.py": (
                    "from owpp.lib import plugin_template_text\n\n"
                    'PAGE = plugin_template_text("page.html")\n\nclass Tools:\n    pass\n'
                ),
                "templates/page.html": "<p>tool page</p>\n",
            },
        )
        (fn,) = load_function_files(d)
        tool = embedded(fn.content)["tools"][0]["content"]
        ns: dict = {"__name__": "tool_t_" + "0" * 32}
        exec(compile(tool, "tool.py", "exec"), ns)
        assert ns["PAGE"] == "<p>tool page</p>\n"
        (d / "viz" / "plugin.yaml").write_text("function:\n  title: T\ntool:\n  id: t\n")
        (d / "viz" / "tool.py").write_text("class Tools:\n    pass\n")
        (fn,) = load_function_files(d)
        assert "tool page" not in embedded(fn.content)["tools"][0]["content"]  # it did not ask

    TOOL_READS = {
        "function.py": "class Filter:\n    pass\n",
        "tool.py": (
            "from owpp.lib import plugin_template_files\n\n"
            "FILES = plugin_template_files()\n\nclass Tools:\n    pass\n"
        ),
        "templates/page.html": "<p>the function's page</p>\n",
        "templates/card/card.html": "<p>card</p>\n",
        "templates/card/card.css": "p {}\n",
        "templates/embed.html": "<p>embed</p>\n",
    }

    def tool_files(self, d) -> list:
        (fn,) = load_function_files(d)
        tool = embedded(fn.content)["tools"][0]["content"]
        ns: dict = {"__name__": "tool_t_" + "0" * 32}
        exec(compile(tool, "tool.py", "exec"), ns)
        return ns["FILES"], tool

    def test_a_tool_embeds_only_the_templates_it_lists(self, plugin):
        """`tool: templates:` names the files (or folders, with a trailing /) the tool embeds, so
        a function's large page is not copied into its tool; the key is not a header line."""
        d = plugin(
            "function:\n  title: T\ntool:\n  id: t\n  include: [templates]\n"
            "  templates: [card/, embed.html]\n",
            self.TOOL_READS,
        )
        files, tool = self.tool_files(d)
        assert files == ["card/card.css", "card/card.html", "embed.html"]
        assert "the function's page" not in tool
        assert "templates:" not in tool.split('"""')[1]  # not in the tool's header
        (fn,) = load_function_files(d)
        assert "the function's page" in fn.content  # the function still has every file

    def test_without_the_list_a_tool_embeds_every_template(self, plugin):
        d = plugin(
            "function:\n  title: T\ntool:\n  id: t\n  include: [templates]\n", self.TOOL_READS
        )
        files, _ = self.tool_files(d)
        assert files == ["card/card.css", "card/card.html", "embed.html", "page.html"]

    @pytest.mark.parametrize(
        ("listed", "error"),
        [
            ("[cards/]", r"tool\.templates: `cards/` is not in templates/"),
            (
                "[card]",
                r"tool\.templates: `card` is not in templates/ \(a folder is written `card/`\)",
            ),
            ("card/", r"tool\.templates must be a list of paths in templates/"),
            ("['']", r"tool\.templates must be a list of paths in templates/"),
        ],
    )
    def test_a_template_list_that_names_nothing_is_refused(self, plugin, listed, error):
        d = plugin(
            "function:\n  title: T\ntool:\n  id: t\n  include: [templates]\n"
            f"  templates: {listed}\n",
            self.TOOL_READS,
        )
        with pytest.raises(OwppError, match=error):
            load_function_files(d)

    def test_a_template_list_needs_the_tool_to_include_templates(self, plugin):
        d = plugin(
            "function:\n  title: T\ntool:\n  id: t\n  templates: [embed.html]\n",
            {**self.TOOL_READS, "tool.py": "class Tools:\n    pass\n"},
        )
        with pytest.raises(OwppError, match=r"tool\.templates needs `templates` in tool\.include"):
            load_function_files(d)

    def test_both_folders_can_be_in_one_plugin(self, plugin):
        d = plugin(
            "function:\n  title: T\n", {**self.FN, "static/a.txt": "a", "templates/p.html": "p"}
        )
        c = load_function_files(d)[0].content
        assert "end plugin static library" in c and "end plugin templates library" in c

    def test_the_prefix_defaults_to_the_plugin_id_and_bad_ones_are_refused(self, tmp_path):
        files = {**self.FN, "static/a.txt": "a"}

        def make(name, manifest, files=files):
            d = tmp_path / name
            write_tree(d / "viz", {"plugin.yaml": manifest, **files})
            return d

        assert (
            _data(load_function_files(make("ok", "function:\n  title: T\n"))[0].content, "_STATIC")[
                "prefix"
            ]
            == "/viz"
        )
        with pytest.raises(OwppError, match="prefix must be a path"):
            load_function_files(make("a", "function:\n  title: T\nstatic: {prefix: /a b}\n"))

    @pytest.mark.parametrize("access", ["user", "admin", "public"])
    def test_the_access_is_embedded(self, tmp_path, access):
        write_tree(
            tmp_path / "viz",
            {
                "plugin.yaml": f"function:\n  title: T\nstatic: {{access: {access}}}\n",
                **self.FN,
                "static/a.txt": "a",
            },
        )
        assert _data(load_function_files(tmp_path)[0].content, "_STATIC")["access"] == access

    def test_the_old_layout_is_refused_loudly_not_silently_unserved(self, tmp_path):
        write_tree(
            tmp_path / "viz",
            {"plugin.yaml": "function:\n  title: T\n", **self.FN, "public/a.txt": "a"},
        )
        with pytest.raises(OwppError, match=r"public/ is now two folders: static/.*templates/"):
            load_function_files(tmp_path)

    def test_dynamic_is_gone_and_says_where_its_files_go(self, tmp_path):
        write_tree(
            tmp_path / "viz",
            {
                "plugin.yaml": "function:\n  title: T\nstatic: {dynamic: [a.txt]}\n",
                **self.FN,
                "static/a.txt": "a",
            },
        )
        with pytest.raises(OwppError, match=r"unknown key dynamic \(known: prefix, access\)"):
            load_function_files(tmp_path)

    def test_a_static_section_needs_its_folder(self, tmp_path):
        write_tree(
            tmp_path / "viz", {"plugin.yaml": "function:\n  title: T\nstatic: {}\n", **self.FN}
        )
        with pytest.raises(OwppError, match=r"static: needs a static/ folder"):
            load_function_files(tmp_path)

    @pytest.mark.parametrize(
        ("folder", "message"),
        [("static", "static/ has no files"), ("templates", "templates/ has no files")],
    )
    def test_an_empty_folder_is_refused(self, tmp_path, folder, message):
        write_tree(tmp_path / "viz", {"plugin.yaml": "function:\n  title: T\n", **self.FN})
        (tmp_path / "viz" / folder).mkdir()
        with pytest.raises(OwppError, match=message):
            load_function_files(tmp_path)


class TestAssets:
    """assets/loader.js and assets/custom.css: fragments of the Shared Assets Protocol."""

    LOADER = 'console.log("hi from the plugin");\nvar q = """still fine""";\n'
    CSS = ":root { --x: __ACCENT__; }\n"

    def make(self, plugin, manifest="function:\n  title: T\n", files=None):
        return plugin(
            manifest,
            {"assets/loader.js": self.LOADER, "assets/custom.css": self.CSS, **(files or {})},
        )

    @staticmethod
    def data(code):
        m = re.search(r'_ASSETS = _json\.loads\((".*")\)\n', code)
        assert m, "no assets data in the bundle"
        return json.loads(json.loads(m.group(1)))

    def test_a_plugin_with_only_assets_gets_a_generated_event(self, plugin):
        (fn,) = load_function_files(self.make(plugin))
        assert fn.type == "event"
        assert "class Event(PluginAssets):" in fn.content
        assert fn.content.endswith("\n")
        data = self.data(fn.content)
        assert data == {
            "id": "viz",
            "order": 0,
            "wrap": True,
            "files": {"loader.js": self.LOADER, "custom.css": self.CSS},
        }

    def test_the_protocol_blocks_come_in_by_themselves_in_the_right_order(self, plugin):
        (fn,) = load_function_files(self.make(plugin))
        c = fn.content
        for end in (
            "end shared asset block",
            "end plugin core library",
            "end plugin assets library",
        ):
            assert c.count(end) == 1, end
        assert (
            c.index("end shared asset block")
            < c.index("end plugin core library")
            < c.index("def plugin_assets_register(")
            < c.index("class Event(PluginAssets):")
        )
        assert "end live reload block" not in c  # live reload is opt-in

    def test_live_reload_is_opt_in_and_needs_nothing_else_listed(self, plugin):
        (fn,) = load_function_files(
            self.make(plugin, "function:\n  title: T\ninclude: [live_reload]\n")
        )
        c = fn.content
        assert (
            c.index("end live reload block")
            < c.index("end shared asset block")
            < c.index("class Event(PluginAssets)")
        )

    def test_text_survives_exactly_whatever_quotes_it_holds(self, plugin):
        # In a Python string this loader would end the string early.
        (fn,) = load_function_files(self.make(plugin))
        assert self.data(fn.content)["files"]["loader.js"] == self.LOADER

    def test_settings_order_and_wrap(self, plugin):
        d = self.make(plugin, "function:\n  title: T\nassets:\n  order: -5\n  wrap: false\n")
        data = self.data(load_function_files(d)[0].content)
        assert (data["order"], data["wrap"]) == (-5, False)

    @pytest.mark.parametrize(
        ("manifest", "message"),
        [
            (
                "function:\n  title: T\nassets: {order: late}\n",
                r"assets\.order must be a whole number",
            ),
            (
                "function:\n  title: T\nassets: {order: true}\n",
                r"assets\.order must be a whole number",
            ),
            (
                "function:\n  title: T\nassets: {wrap: sure}\n",
                r"assets\.wrap must be true or false",
            ),
            ("function:\n  title: T\nassets: {colour: red}\n", r"unknown key colour"),
            ("function:\n  title: T\nassets: [a]\n", r"must be a mapping"),
        ],
    )
    def test_refuses_bad_settings(self, plugin, manifest, message):
        with pytest.raises(OwppError, match=message):
            load_function_files(self.make(plugin, manifest))

    def test_only_the_two_protocol_files_are_allowed(self, plugin):
        d = self.make(plugin, files={"assets/logo.png": b"\x89PNG"})
        with pytest.raises(OwppError, match="only loader.js and custom.css"):
            load_function_files(d)

    def test_one_of_the_two_is_enough_and_none_is_not(self, plugin, tmp_path):
        only_css = plugin("function:\n  title: T\n", {"assets/custom.css": "a{}\n"})
        assert list(self.data(load_function_files(only_css)[0].content)["files"]) == ["custom.css"]
        write_tree(tmp_path / "empty" / "viz", {"plugin.yaml": "function:\n  title: T\n"})
        (tmp_path / "empty" / "viz" / "assets").mkdir()
        with pytest.raises(OwppError, match="neither loader.js nor custom.css"):
            load_function_files(tmp_path / "empty")

    def test_the_assets_key_needs_the_folder(self, plugin):
        d = plugin(
            "function:\n  title: T\nassets: {order: 1}\n",
            {"function.py": "class Event:\n    pass\n"},
        )
        with pytest.raises(OwppError, match="needs an assets/ folder"):
            load_function_files(d)

    def test_a_function_py_must_use_the_mixin(self, plugin):
        d = self.make(plugin, files={"function.py": "class Event:\n    pass\n"})
        with pytest.raises(OwppError, match=r"class Event\(PluginAssets\)"):
            load_function_files(d)

    def test_a_function_py_with_the_mixin_is_bundled_after_the_libraries(self, plugin):
        d = self.make(
            plugin,
            files={
                "function.py": (
                    "from owpp.lib import PluginAssets\n\n"
                    "class Event(PluginAssets):\n    def asset_vars(self):\n        return {}\n"
                )
            },
        )
        (fn,) = load_function_files(d)
        assert fn.content.index("class PluginAssets(PluginEvents):") < fn.content.index(
            "class Event(PluginAssets):"
        )

    def test_assets_with_a_tool_needs_a_function_py(self, plugin):
        d = self.make(
            plugin,
            "function:\n  title: T\ntool:\n  id: t\n  title: T\n",
            {"tool.py": "class Tools:\n    pass\n"},
        )
        with pytest.raises(OwppError, match="needs a function.py"):
            load_function_files(d)

    def test_include_assets_needs_the_folder_and_the_tool_does_not_get_it(self, plugin):
        d = plugin(
            "function:\n  title: T\ninclude: [assets]\n",
            {"function.py": "class Event:\n    pass\n"},
        )
        with pytest.raises(OwppError, match="needs an assets/ folder"):
            load_function_files(d)


class TestConfig:
    """config.yaml: parsed when bundling, embedded as data, read with plugin_config()."""

    def make(self, plugin, config, manifest="function:\n  title: T\n"):
        return plugin(manifest, {"function.py": "class Event:\n    pass\n", "config.yaml": config})

    @staticmethod
    def namespace(fn):
        ns: dict = {}
        exec(compile(fn.content, "bundle.py", "exec"), ns)
        return ns

    def test_embeds_the_parsed_file_before_the_code(self, plugin):
        d = self.make(plugin, "retries: 3\nservers:\n  a: {name: A}\n")
        (fn,) = load_function_files(d)
        assert fn.content.count("end plugin config library") == 1
        assert fn.content.index("def plugin_config(") < fn.content.index("class Event:")
        m = re.search(r'_CONFIG = _json\.loads\((".*")\)\n', fn.content)
        assert json.loads(json.loads(m.group(1))) == {"retries": 3, "servers": {"a": {"name": "A"}}}

    def test_the_function_reads_it_laid_over_its_defaults(self, plugin):
        d = self.make(plugin, "retries: 3\nservers:\n  a: {name: A}\ntags: [x]\n")
        ns = self.namespace(load_function_files(d)[0])
        defaults = {
            "retries": 1,
            "timeout": 15,
            "servers": {"b": {"name": "B"}},
            "tags": ["old", "y"],
        }
        merged = ns["plugin_config"](defaults)
        assert merged == {
            "retries": 3,  # replaced
            "timeout": 15,  # kept
            "servers": {"b": {"name": "B"}, "a": {"name": "A"}},  # mappings merge key by key
            "tags": ["x"],  # a list is replaced, not appended to
        }
        assert defaults["retries"] == 1 and defaults["tags"] == ["old", "y"]  # defaults untouched

    def test_each_call_returns_a_copy_the_caller_may_change(self, plugin):
        ns = self.namespace(load_function_files(self.make(plugin, "servers:\n  a: {name: A}\n"))[0])
        first = ns["plugin_config"]()
        first["servers"]["a"]["name"] = "changed"
        assert ns["plugin_config"]()["servers"]["a"]["name"] == "A"

    def test_yaml_is_read_as_1_2_so_on_and_no_stay_text(self, plugin):
        d = self.make(plugin, "mode: on\nanswer: no\nclock: 12:30\nreal: true\nn: 007\n")
        m = re.search(r'_CONFIG = _json\.loads\((".*")\)\n', load_function_files(d)[0].content)
        assert json.loads(json.loads(m.group(1))) == {
            "mode": "on",
            "answer": "no",
            "clock": "12:30",
            "real": True,
            "n": 7,
        }

    def test_an_empty_file_is_an_empty_config(self, plugin):
        ns = self.namespace(load_function_files(self.make(plugin, ""))[0])
        assert ns["plugin_config"]({"a": 1}) == {"a": 1}

    def test_a_mistake_in_it_fails_the_bundle_not_the_deployed_plugin(self, plugin):
        with pytest.raises(OwppError, match=r"config\.yaml: not valid YAML"):
            load_function_files(self.make(plugin, "servers: [a\n"))
        with pytest.raises(OwppError, match="must be a mapping"):
            load_function_files(self.make(plugin, "- a\n- b\n"))

    def test_include_config_needs_the_file(self, plugin):
        d = plugin(
            "function:\n  title: T\ninclude: [config]\n",
            {"function.py": "class Event:\n    pass\n"},
        )
        with pytest.raises(OwppError, match=r"include: config needs a config\.yaml"):
            load_function_files(d)

    @pytest.mark.parametrize(
        ("lib", "needs"), [("static", "a static/ folder"), ("templates", "a templates/ folder")]
    )
    def test_include_static_and_templates_need_their_folders(self, plugin, lib, needs):
        d = plugin(
            f"function:\n  title: T\ninclude: [{lib}]\n",
            {"function.py": "class Event:\n    pass\n"},
        )
        with pytest.raises(OwppError, match=rf"include: {lib} needs {needs}"):
            load_function_files(d)

    def test_the_tool_bundle_does_not_get_it(self, plugin):
        d = self.make(
            plugin,
            "a: 1\n",
            "function:\n  title: T\ntool:\n  id: t\n  title: T\n",
        )
        (d / "viz" / "tool.py").write_text("class Tools:\n    pass\n")
        (fn,) = load_function_files(d)
        assert "plugin_config" not in embedded(fn.content)["tools"][0]["content"]

    def test_an_example_that_ships_one_bundles_it(self):
        (fn,) = [f for f in load_function_files(EXAMPLES, fake_sources()) if f.id == "mcpo_sync"]
        m = re.search(r'_CONFIG = _json\.loads\((".*")\)\n', fn.content)
        assert "servers" in json.loads(json.loads(m.group(1)))


class TestIncludeLibraries:
    FN = {"function.py": "class Event:\n    pass\n"}

    @pytest.fixture
    def mk(self, tmp_path):
        def make(manifest, files=None):
            write_tree(
                tmp_path / "p", {"plugin.yaml": manifest, **(self.FN if files is None else files)}
            )
            return tmp_path

        return make

    def test_inserts_the_vendored_libraries_after_the_header_live_reload_first(self, mk):
        (fn,) = load_function_files(
            mk("function: {title: T}\ninclude: [shared_assets, live_reload]\n")
        )
        c = fn.content
        assert c.startswith('"""\ntitle: T\n"""\n')
        lr, sa = c.index("end live reload block"), c.index("end shared asset block")
        assert 0 < lr < sa < c.index("class Event:")
        assert "Copy everything below this header" not in c
        assert re.search(r"ASSET_IMPL_VERSION = \d+", c)

    def test_does_not_insert_a_library_the_code_already_carries(self, mk):
        code = "class Event:\n    pass\n# ===== end shared asset block =====\n"
        (fn,) = load_function_files(
            mk("function: {title: T}\ninclude: [shared_assets]\n", {"function.py": code})
        )
        assert fn.content.count("end shared asset block") == 1

    def test_inserts_routes_and_jobs_once_each_with_their_public_names(self, mk):
        (fn,) = load_function_files(
            mk("function: {title: T}\ninclude: [jobs, routes, chat_data]\n")
        )
        for name in (
            "def plugin_mount(",
            "async def plugin_require_active(",
            "async def plugin_claim(",
            "def plugin_every(",
            "def plugin_spawn(",
            "async def plugin_chat_read(",
        ):
            assert fn.content.count(name) == 1, name

    def test_adds_core_ahead_of_routes_jobs_and_static_but_not_for_chat_data_alone(
        self, mk, tmp_path
    ):
        (fn,) = load_function_files(mk("function: {title: T}\ninclude: [jobs, routes]\n"))
        c = fn.content
        assert c.count("def plugin_function_id(") == 1
        assert c.index("end plugin core library") < c.index("def plugin_mount(")
        assert c.index("end plugin core library") < c.index("async def plugin_claim(")
        write_tree(
            tmp_path / "solo" / "p",
            {"plugin.yaml": "function: {title: T}\ninclude: [chat_data]\n", **self.FN},
        )
        (solo,) = load_function_files(tmp_path / "solo")
        assert "plugin_function_id" not in solo.content

    def test_refuses_unknown_libraries_and_live_reload_without_shared_assets(self, mk):
        with pytest.raises(OwppError, match="unknown include nope"):
            load_function_files(mk("function: {title: T}\ninclude: [nope]\n"))

    def test_live_reload_needs_shared_assets(self, tmp_path):
        write_tree(
            tmp_path / "p",
            {"plugin.yaml": "function: {title: T}\ninclude: [live_reload]\n", **self.FN},
        )
        with pytest.raises(OwppError, match="needs shared_assets"):
            load_function_files(tmp_path)


class TestExamples:
    names = sorted(p.name for p in EXAMPLES.iterdir())

    def test_bundle_and_compile_without_undefined_names_when_the_code_is_local(self):
        files = {f.id: f for f in load_function_files(EXAMPLES, fake_sources())}
        assert sorted(files) == self.names
        for n in self.names:
            if re.search(r"^source:", (EXAMPLES / n / "plugin.yaml").read_text(), re.MULTILINE):
                continue
            assert check_bundle(files[n].content, f"{n}.py") is None, n

    def test_every_built_in_library_is_documented(self):
        doc = (DOCS / "libraries.md").read_text()
        for lib in (
            "core",
            "routes",
            "jobs",
            "chat_data",
            "static",
            "templates",
            "shared_assets",
            "live_reload",
        ):
            assert f"`{lib}`" in doc or f"## {lib}" in doc, lib

    def test_every_example_documents_how_to_test_and_deploy_itself(self):
        for n in self.names:
            readme = (EXAMPLES / n / "README.md").read_text()
            for heading in ("## Test", "## Deploy"):
                assert f"\n{heading}" in readme, f'{n}/README.md needs a "{heading}" section'
            assert f"owpp check {n}" in readme, f"{n}/README.md should show `owpp check {n}`"
            assert f"owpp test {n}" in readme, f"{n}/README.md should show `owpp test {n}`"

    def test_every_example_has_unit_tests(self):
        for n in self.names:
            assert list((EXAMPLES / n / "tests").glob("test_*.py")), f"{n}/tests/ has no tests"

    def test_the_excalidraw_folder_bundles_into_a_complete_function(self):
        (fn,) = [f for f in load_function_files(EXAMPLES, fake_sources()) if f.id == "excalidraw"]
        assert fn.want_global is True
        for needle in (
            "class Filter:",
            'VIEWER = plugin_template_text("viewer.html")',
            "<!doctype html>",
            "def plugin_mount(",
            "def plugin_template_text(",
        ):
            assert needle in fn.content, needle
        assert (
            "def plugin_static_serve(" not in fn.content
        )  # the page is rendered, never served as a file
        assert "{{file:" not in fn.content
        # The Tool is its own bundle (tool.py), declared in plugin.yaml and installed by the
        # runtime appended to the function, not by code inside the function.
        assert fn.content.endswith("_plugin_start()\n")
        above = fn.content.split("_PLUGIN = ")[0]  # the tool's code is also inside the data literal
        assert "class Tools:" not in above
        tool = embedded(fn.content)["tools"][0]
        assert tool["self"] is False
        assert tool["content"].startswith('"""\ntitle: Excalidraw\n')
        assert "class Tools:" in tool["content"] and "class Filter:" not in tool["content"]
        # The scene store is the chat_data library in both bundles.
        for code in (fn.content, tool["content"]):
            assert "async def plugin_chat_update(" in code
        assert (
            "INSERT" not in above
            and "json_set(COALESCE(meta, '{}'), '$.{META_KEY}'" not in fn.content
        )
        # shared.py is in front of both, after the header and before the code.
        for code, cls in ((fn.content, "class Filter:"), (tool["content"], "class Tools:")):
            assert 0 < code.index("def _simplify(") < code.index(cls)
        # The tool carries the runtime with only the ids, so it can notice a disabled parent.
        assert tool["content"].endswith("_plugin_start()\n")
        for gone in (
            "def _install_tool(",
            "_LifecycleSink",
            "def _prune_tool(",
            "SHARE_TOOL",
            "TOOL_ID",
        ):
            assert gone not in fn.content, gone


class TestFunctionTypes:
    @pytest.fixture
    def mk(self, tmp_path):
        def make(manifest, files):
            write_tree(tmp_path / "p", {"plugin.yaml": manifest, **files})
            return tmp_path

        return make

    def test_is_told_from_the_top_level_class_like_open_webui_does(self):
        assert function_type("class Filter:\n    pass\n") == ["filter"]
        assert function_type("class Event:\n    pass\n") == ["event"]
        assert function_type("x = 1\n    class Filter:\n") == []  # nested: not a function class
        assert sorted(function_type("class Pipe:\n\nclass Action:\n")) == ["action", "pipe"]

    def test_refuses_no_class_two_classes_and_global_on_an_event(self, mk, tmp_path):
        with pytest.raises(OwppError, match="exactly one of class"):
            load_function_files(mk("function: {title: T}\n", {"function.py": "x = 1\n"}))
        two = "class Filter:\n    pass\nclass Event:\n    pass\n"
        write_tree(
            tmp_path / "two" / "p", {"plugin.yaml": "function: {title: T}\n", "function.py": two}
        )
        with pytest.raises(OwppError, match="exactly one of class"):
            load_function_files(tmp_path / "two")
        write_tree(
            tmp_path / "glob" / "p",
            {
                "plugin.yaml": "function: {title: T, global: true}\n",
                "function.py": "class Event:\n    pass\n",
            },
        )
        with pytest.raises(OwppError, match="only applies to filters and actions"):
            load_function_files(tmp_path / "glob")

    def test_reports_the_type_of_each_example_events_never_global(self):
        types = {f.id: f.type for f in load_function_files(EXAMPLES, fake_sources())}
        assert types["mcpo_sync"] == "event"
        assert types["stale_data"] == "event"
        assert types["inline_visualizer"] == "filter"
        assert types["excalidraw"] == "filter"

    def test_names_the_type_in_the_report(self):
        report = render_report([Result(id="a", file="a/", action="created", type="event")], False)
        assert "- event function `a`" in report


class TestUnknownManifestKeys:
    """A setting that is silently ignored (a typo) is worst when it is a security one."""

    def load(self, tmp_path, manifest):
        write_tree(
            tmp_path / "p", {"plugin.yaml": manifest, "function.py": "class Event:\n    pass\n"}
        )
        return load_function_files(tmp_path)

    @pytest.mark.parametrize(
        ("typo", "suggestion"),
        [
            ("statc", "static"),
            ("incldue", "include"),
            ("asset", "assets"),
            ("job", "jobs"),
            ("tools", "tool"),
            ("skill", "skills"),
        ],
    )
    def test_a_typo_is_refused_with_a_suggestion(self, tmp_path, typo, suggestion):
        with pytest.raises(
            OwppError, match=rf"unknown key `{typo}:`.*did you mean `{suggestion}:`"
        ):
            self.load(tmp_path, f"function:\n  title: T\n{typo}: {{}}\n")

    def test_a_key_that_is_nothing_like_one_is_refused_without_a_guess(self, tmp_path):
        with pytest.raises(OwppError, match="unknown key `zzzzzz:`") as caught:
            self.load(tmp_path, "function:\n  title: T\nzzzzzz: 1\n")
        assert "did you mean" not in str(caught.value)

    def test_x_keys_are_left_for_yaml_anchors_and_notes(self, tmp_path):
        assert (
            self.load(tmp_path, "x-common: &c {a: 1}\nfunction:\n  title: T\n")[0].type == "event"
        )

    def test_every_documented_key_is_accepted(self):
        from owpp.manifest import MANIFEST_KEYS

        assert set(MANIFEST_KEYS) == {
            "function",
            "tool",
            "skills",
            "source",
            "include",
            "static",
            "assets",
            "jobs",
            "requires",
            "protocol",
        }


class TestProtocol:
    """A manifest says which version of the protocol it was written for."""

    def load(self, tmp_path, manifest):
        write_tree(
            tmp_path / "p", {"plugin.yaml": manifest, "function.py": "class Event:\n    pass\n"}
        )
        return load_function_files(tmp_path)

    def test_the_current_version_is_accepted(self, tmp_path):
        assert self.load(tmp_path, 'protocol: "0.2"\nfunction: {title: T}\n')[0].type == "event"

    def test_an_older_version_is_accepted(self, tmp_path):
        assert self.load(tmp_path, 'protocol: "0.1"\nfunction: {title: T}\n')[0].type == "event"

    def test_a_manifest_without_the_key_still_loads(self, tmp_path):
        assert self.load(tmp_path, "function: {title: T}\n")[0].type == "event"

    def test_an_unquoted_version_is_refused(self, tmp_path):
        with pytest.raises(OwppError, match=r"`protocol:` must be a quoted major.minor string"):
            self.load(tmp_path, "protocol: 0.2\nfunction: {title: T}\n")

    @pytest.mark.parametrize("value", ['"1"', '"0.2.0"', '"protocol"', "true", "[0.2]"])
    def test_a_malformed_version_is_refused(self, tmp_path, value):
        with pytest.raises(OwppError, match=r"`protocol:` must be a quoted major.minor string"):
            self.load(tmp_path, f"protocol: {value}\nfunction: {{title: T}}\n")

    @pytest.mark.parametrize("value", ["0.6", "1.0"])
    def test_a_newer_version_is_refused(self, tmp_path, value):
        with pytest.raises(OwppError, match=rf"protocol {value} is newer than owpp supports"):
            self.load(tmp_path, f'protocol: "{value}"\nfunction: {{title: T}}\n')
