"""compare(): what changed between two copies of a function's code, as Open-WebUI stores them."""

from owpp.compare import Part, compare
from owpp.embedding import embed_runtime

FUNCTION = '"""\ntitle: F\nversion: 1.0.0\n"""\nclass Filter:\n    pass\n'


def tool(version: str = "", body: str = "pass") -> dict:
    header = f'"""\ntitle: T\nversion: {version}\n"""\n' if version else ""
    return {"id": "t", "content": f"{header}class Tools:\n    {body}\n"}


def skill(version: str = "", text: str = "Draw.") -> dict:
    v = f"version: {version}\n" if version else ""
    md = f"---\nname: s\ndescription: d\n{v}---\n{text}\n"
    return {"id": "s", "files": [{"path": "SKILL.md", "content": md}]}


def bundle(tools=(), skills=(), code: str = FUNCTION) -> str:
    return embed_runtime(code, {"tools": list(tools), "skills": list(skills)})


def part(comparison, kind: str) -> Part:
    return next(p for p in comparison.parts if p.kind == kind)


def test_line_endings_and_trailing_space_do_not_count():
    assert compare("x = 1\r\n", "x = 1   \n").unchanged


def test_code_that_differs_only_in_a_rewritten_import_prefix_is_unchanged():
    # Open-WebUI stores `from utils` as `from open_webui.utils`: both copies are stored alike.
    stored = bundle([tool(body="from open_webui.utils.misc import x")])
    local = bundle([tool(body="from utils.misc import x")])
    c = compare(stored, local)
    assert c.unchanged and all(p.status == "unchanged" for p in c.parts)


def test_with_no_old_copy_every_part_is_new():
    c = compare(None, bundle([tool("2.0")], [skill("3.0")]))
    assert not c.unchanged
    assert c.parts == (
        Part("function", "", "new", "", "1.0.0"),
        Part("tool", "t", "new", "", "2.0"),
        Part("skill", "s", "new", "", "3.0"),
    )


def test_a_new_tool_and_a_removed_skill():
    c = compare(bundle(skills=[skill("1.0")]), bundle([tool("2.0")]))
    assert part(c, "function").status == "unchanged"
    assert part(c, "tool") == Part("tool", "t", "new", "", "2.0")
    assert part(c, "skill") == Part("skill", "s", "removed", "1.0", "")


def test_a_changed_tool_keeps_its_versions_and_the_function_is_unchanged():
    c = compare(bundle([tool("1.0")]), bundle([tool("1.1", body="x = 1")]))
    assert not c.unchanged
    assert part(c, "function").status == "unchanged"
    assert part(c, "tool") == Part("tool", "t", "changed", "1.0", "1.1")
    assert c.downgrades == ()


def test_a_changed_function_code():
    c = compare(bundle(), bundle(code=FUNCTION.replace("pass", "x = 1")))
    assert part(c, "function") == Part("function", "", "changed", "1.0.0", "1.0.0")


def test_a_skill_whose_version_goes_back_is_a_downgrade():
    c = compare(bundle(skills=[skill("2.0.0")]), bundle(skills=[skill("1.9.0", "Older.")]))
    assert c.downgrades == (Part("skill", "s", "changed", "2.0.0", "1.9.0"),)


def test_an_unversioned_part_is_never_a_downgrade():
    c = compare(bundle([tool("1.0")]), bundle([tool(body="x = 1")]))
    assert part(c, "tool") == Part("tool", "t", "changed", "1.0", "")
    assert c.downgrades == ()


def test_a_removed_tool_and_a_new_skill():
    c = compare(bundle([tool("2.0")]), bundle(skills=[skill("1.0")]))
    assert part(c, "tool") == Part("tool", "t", "removed", "2.0", "")
    assert part(c, "skill") == Part("skill", "s", "new", "", "1.0")


def test_an_unversioned_skill_that_changes_is_never_a_downgrade():
    c = compare(bundle(skills=[skill()]), bundle(skills=[skill(text="Paint.")]))
    assert part(c, "skill") == Part("skill", "s", "changed", "", "")
    assert c.downgrades == ()
