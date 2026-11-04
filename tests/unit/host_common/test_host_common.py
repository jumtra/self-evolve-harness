import pytest

from seh.contracts import CanonicalSpec, ChangeAction, SkillSpec
from seh.providers.hosts.common import (
    MANAGED_BLOCK_REASON,
    agents_md_change,
    frontmatter_document,
    managed_block,
    shared_skill_changes,
)


def test_frontmatter_document_keeps_key_order_and_ends_with_single_newline() -> None:
    text = frontmatter_document({"name": "work", "description": "開発依頼を処理する"}, "本文\n\n")

    assert text == "---\nname: work\ndescription: 開発依頼を処理する\n---\n\n本文\n"


def test_managed_block_wraps_text_in_seh_markers() -> None:
    text = managed_block("共通方針\n")

    assert text == "<!-- seh:begin -->\n共通方針\n<!-- seh:end -->\n"


def test_shared_skill_changes_writes_minimal_frontmatter_under_agents_dir() -> None:
    skill = SkillSpec(
        id="work",
        description="開発依頼を処理する",
        body="手順",
        claude_frontmatter={"allowed-tools": "Bash"},
    )

    changes = shared_skill_changes(skill, owner="host:codex")

    assert [(c.path, c.action, c.owner) for c in changes] == [
        (".agents/skills/work/SKILL.md", ChangeAction.UPDATE, "host:codex")
    ]
    assert changes[0].content == (
        "---\nname: work\ndescription: 開発依頼を処理する\n---\n\n手順\n".encode()
    )


def test_shared_skill_changes_includes_references_next_to_skill() -> None:
    skill = SkillSpec(
        id="work",
        description="d",
        body="b",
        references={"references/flow.md": "流れ"},
    )

    changes = shared_skill_changes(skill, owner="host:antigravity")

    assert [(c.path, c.content) for c in changes][1] == (
        ".agents/skills/work/references/flow.md",
        "流れ\n".encode(),
    )


@pytest.mark.parametrize(
    "reference_path",
    ["../escape.md", "/abs/path.md", "references/../../x.md"],
    ids=["parent", "absolute", "nested-parent"],
)
def test_shared_skill_changes_rejects_reference_outside_skill_dir(reference_path: str) -> None:
    skill = SkillSpec(id="work", description="d", body="b", references={reference_path: "x"})

    with pytest.raises(ValueError, match="reference path"):
        shared_skill_changes(skill, owner="host:codex")


def test_agents_md_change_is_managed_block_of_instructions() -> None:
    spec = CanonicalSpec(instructions="短い共通方針", skills=(), agents=(), rules=())

    change = agents_md_change(spec, owner="host:opencode")

    assert (change.path, change.action, change.reason, change.owner) == (
        "AGENTS.md",
        ChangeAction.UPDATE,
        MANAGED_BLOCK_REASON,
        "host:opencode",
    )
    assert change.content == "<!-- seh:begin -->\n短い共通方針\n<!-- seh:end -->\n".encode()
