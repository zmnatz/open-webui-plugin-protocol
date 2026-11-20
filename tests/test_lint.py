"""The warnings owpp check gives about valves and tools."""

from __future__ import annotations

import pytest
from conftest import EXAMPLES, write_tree

from owpp.cli import main
from owpp.lint import lint_plugin, lint_source


def lint(tmp_path, code, name="function.py"):
    path = tmp_path / name
    path.write_text(code)
    return lint_source(path)


def messages(findings):
    return [f.message for f in findings]


class TestValves:
    def test_a_plain_default_has_no_description(self, tmp_path):
        found = lint(tmp_path, "class Event:\n    class Valves(BaseModel):\n        N: int = 3\n")
        assert messages(found) == ["valve N has no description: the admin UI shows it"]

    def test_a_field_without_a_description_is_flagged(self, tmp_path):
        assert (
            len(lint(tmp_path, "class Valves(BaseModel):\n    N: int = Field(default=3, ge=0)\n"))
            == 1
        )

    def test_an_empty_description_is_flagged(self, tmp_path):
        assert (
            len(
                lint(
                    tmp_path,
                    'class Valves(BaseModel):\n    N: int = Field(default=3, description=" ")\n',
                )
            )
            == 1
        )

    @pytest.mark.parametrize(
        "field",
        [
            'Field(default=3, description="How many.")',
            'Field(default=3, description=("How " "many."))',
            'Field(default=3, description=f"How {1}.")',
            "Field(default=3, description=TEXT)",
            'pydantic.Field(default=3, description="How many.")',
        ],
    )
    def test_a_description_in_any_form_passes(self, tmp_path, field):
        assert lint(tmp_path, f"class Valves(BaseModel):\n    N: int = {field}\n") == []

    def test_private_fields_and_other_classes_are_left_alone(self, tmp_path):
        code = "class Valves(BaseModel):\n    _cache: dict = {}\n\nclass Other:\n    N: int = 3\n"
        assert lint(tmp_path, code) == []

    def test_user_valves_too_and_each_field_is_reported_with_its_line(self, tmp_path):
        code = "class UserValves(BaseModel):\n    A: int = 1\n    B: int = Field(default=2, description='ok')\n    C: str = 'x'\n"
        assert [(f.line, f.message.split()[1]) for f in lint(tmp_path, code)] == [
            (2, "A"),
            (4, "C"),
        ]


class TestTools:
    def test_no_docstring(self, tmp_path):
        found = lint(
            tmp_path, "class Tools:\n    async def go(self, x: int):\n        pass\n", "tool.py"
        )
        assert messages(found) == ["tool method go() has no docstring: it is what the model reads"]

    def test_an_untyped_parameter(self, tmp_path):
        code = 'class Tools:\n    def go(self, x):\n        """Go.\n\n        :param x: The thing.\n        """\n'
        assert messages(lint(tmp_path, code)) == ["go(): parameter x has no type hint"]

    def test_an_undescribed_parameter(self, tmp_path):
        code = 'class Tools:\n    def go(self, x: int, y: int):\n        """Go.\n\n        :param x: The thing.\n        """\n'
        assert messages(lint(tmp_path, code)) == [
            "go(): parameter y is not described (`:param y:` in the docstring)"
        ]

    def test_a_complete_method_passes_and_so_does_async(self, tmp_path):
        code = 'class Tools:\n    async def go(self, x: int, *, y: str = "a") -> str:\n        """Go.\n\n        :param x: One.\n        :param y: Two.\n        """\n'
        assert lint(tmp_path, code) == []

    def test_injected_parameters_and_self_are_not_the_models_business(self, tmp_path):
        code = 'class Tools:\n    async def go(self, __user__=None, __metadata__: dict = None, __event_emitter__=None):\n        """Go."""\n'
        assert lint(tmp_path, code) == []

    def test_private_methods_and_init_are_skipped(self, tmp_path):
        code = "class Tools:\n    def __init__(self):\n        pass\n\n    def _helper(self, x):\n        pass\n"
        assert lint(tmp_path, code) == []

    def test_a_function_class_is_not_a_tool(self, tmp_path):
        assert lint(tmp_path, "class Filter:\n    def inlet(self, body):\n        pass\n") == []


class TestPlugins:
    BAD = "class Event:\n    class Valves(BaseModel):\n        N: int = 3\n"

    def test_a_folder_is_linted_by_file_with_a_readable_name(self, tmp_path):
        write_tree(
            tmp_path / "p",
            {
                "plugin.yaml": "function:\n  title: T\n",
                "function.py": self.BAD,
                "tool.py": "class Tools:\n    def go(self, x):\n        pass\n",
            },
        )
        assert [str(f) for f in lint_plugin(tmp_path / "p", "p")] == [
            "p/function.py:3: valve N has no description: the admin UI shows it",
            "p/tool.py:2: tool method go() has no docstring: it is what the model reads",
        ]

    def test_shared_py_is_linted_too(self, tmp_path):
        write_tree(
            tmp_path / "p", {"plugin.yaml": "function:\n  title: T\n", "shared.py": self.BAD}
        )
        assert len(lint_plugin(tmp_path / "p", "p")) == 1

    def test_code_taken_from_a_source_is_not_ours_to_lint(self, tmp_path):
        manifest = (
            "source: {git: https://example.com/o/r.git, ref: "
            + "a" * 40
            + ", path: x}\nfunction: {title: T}\n"
        )
        write_tree(tmp_path / "p", {"plugin.yaml": manifest, "function.py": self.BAD})
        assert lint_plugin(tmp_path / "p", "p") == []

    def test_a_loose_file_is_linted(self, tmp_path):
        (tmp_path / "x.py").write_text(self.BAD)
        assert [str(f) for f in lint_plugin(tmp_path / "x.py", "x.py")] == [
            "x.py:3: valve N has no description: the admin UI shows it"
        ]

    def test_a_file_that_does_not_parse_is_left_to_the_compile_check(self, tmp_path):
        assert lint(tmp_path, "class Valves(:\n") == []

    @pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.iterdir()))
    def test_the_examples_are_clean(self, name):
        assert lint_plugin(EXAMPLES / name, name) == []


class TestTheCommand:
    def make(self, tmp_path):
        write_tree(
            tmp_path / "p",
            {
                "plugin.yaml": 'protocol: "0.2"\nfunction:\n  title: T\n',
                "function.py": "from pydantic import BaseModel\n\nclass Event:\n    class Valves(BaseModel):\n        N: int = 3\n",
            },
        )

    def test_warnings_are_printed_and_do_not_fail_by_default(self, tmp_path, capsys):
        self.make(tmp_path)
        assert main(["check", "--dir", str(tmp_path)], env={}) == 0
        out = capsys.readouterr().out
        assert "warn  p/function.py:5: valve N has no description" in out and "1 warning(s)" in out

    def test_strict_makes_them_fail(self, tmp_path, capsys):
        self.make(tmp_path)
        assert main(["check", "--strict", "--dir", str(tmp_path)], env={}) == 1
        assert "failing because of --strict" in capsys.readouterr().out

    def test_strict_passes_a_clean_plugin(self, tmp_path, capsys):
        write_tree(
            tmp_path / "p",
            {
                "plugin.yaml": 'protocol: "0.2"\nfunction:\n  title: T\n',
                "function.py": "class Event:\n    pass\n",
            },
        )
        assert main(["check", "--strict", "--dir", str(tmp_path)], env={}) == 0
        assert "warn" not in capsys.readouterr().out


class TestPublicNotes:
    """Every place a plugin serves people who are not signed in is listed, so a reviewer sees it."""

    def notes(self, tmp_path, files):
        from owpp.lint import lint_notes

        write_tree(tmp_path / "p", {"plugin.yaml": "function:\n  title: T\n", **files})
        return [str(n) for n in lint_notes(tmp_path / "p", "p")]

    MOUNT = "class Event:\n    def go(self, app, router):\n        plugin_mount(app, router, '/hook', {})\n"

    def test_a_public_mount_is_noted_with_its_line(self, tmp_path):
        notes = self.notes(tmp_path, {"function.py": self.MOUNT.format('access="public"')})
        assert notes == [
            'p/function.py:3: mounts routes that serve people who are not signed in (access="public")'
        ]

    @pytest.mark.parametrize("access", ['access="user"', 'access="admin"', "name='x'", ""])
    def test_other_mounts_are_not(self, tmp_path, access):
        assert self.notes(tmp_path, {"function.py": self.MOUNT.format(access)}) == []

    def test_a_computed_access_is_noted_because_it_cannot_be_told(self, tmp_path):
        notes = self.notes(tmp_path, {"function.py": self.MOUNT.format("access=LEVEL")})
        assert len(notes) == 1 and "computed here" in notes[0]

    def test_a_static_folder_that_is_public_is_noted_with_the_manifest_line(self, tmp_path):
        manifest = "function:\n  title: T\nstatic:\n  prefix: /x\n  access: public\n"
        write_tree(
            tmp_path / "p",
            {
                "plugin.yaml": manifest,
                "function.py": "class Event:\n    pass\n",
                "static/a.txt": "a",
            },
        )
        from owpp.lint import lint_notes

        assert [str(n) for n in lint_notes(tmp_path / "p", "p")] == [
            "p/plugin.yaml:5: serves its static/ files to people who are not signed in (static: access: public)"
        ]

    def test_a_static_folder_for_signed_in_users_is_not(self, tmp_path):
        write_tree(
            tmp_path / "p",
            {
                "plugin.yaml": "function:\n  title: T\nstatic: {access: admin}\n",
                "function.py": "class Event:\n    pass\n",
                "static/a.txt": "a",
            },
        )
        from owpp.lint import lint_notes

        assert lint_notes(tmp_path / "p", "p") == []

    def test_the_examples_serve_nobody_publicly(self):
        from owpp.lint import lint_notes

        for folder in EXAMPLES.iterdir():
            assert lint_notes(folder, folder.name) == [], folder.name

    def test_owpp_check_prints_them_without_failing_even_when_strict(self, tmp_path, capsys):
        write_tree(
            tmp_path / "p",
            {
                "plugin.yaml": 'protocol: "0.2"\nfunction:\n  title: T\ninclude: [routes]\n',
                "function.py": "class Event:\n    def go(self, app, router):\n        plugin_mount(app, router, '/hook', access='public')\n",
            },
        )
        assert main(["check", "--strict", "--dir", str(tmp_path)], env={}) == 0
        out = capsys.readouterr().out
        assert (
            'note  p/function.py:3: mounts routes that serve people who are not signed in (access="public")'
            in out
        )
        assert "warning(s)" not in out
