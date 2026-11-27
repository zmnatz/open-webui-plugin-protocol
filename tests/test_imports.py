"""add_lib_imports: the `from owpp.lib import` line it writes for a plugin's file."""

from owpp.imports import add_lib_imports
from owpp.libraries import exports


def test_defaults_its_export_list_to_every_library_name():
    # A caller passes only the code; the library names come from owpp.libraries.exports().
    out = add_lib_imports("def f():\n    return reload_log\n")
    assert out == "from owpp.lib import reload_log\n\n\ndef f():\n    return reload_log\n"


def test_the_default_is_the_same_as_passing_exports_explicitly():
    code = "def f():\n    return reload_log, reload_tasks\n"
    assert add_lib_imports(code) == add_lib_imports(code, exports())


def test_a_name_outside_the_export_list_is_not_imported():
    code = "def f():\n    return not_a_library_name\n"
    assert add_lib_imports(code) == code
