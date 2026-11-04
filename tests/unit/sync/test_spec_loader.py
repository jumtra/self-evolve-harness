from pathlib import Path

import pytest

from seh.spec_loader import SpecError, load_spec


def test_loads_all_four_sections(tmp_path: Path) -> None:
    (tmp_path / "instructions").mkdir()
    (tmp_path / "instructions" / "core.md").write_text("共通指示\n", encoding="utf-8")
    (tmp_path / "skills" / "my-skill").mkdir(parents=True)
    (tmp_path / "skills" / "my-skill" / "SKILL.md").write_text(
        "---\ndescription: 説明です\n---\n\n本文\n", encoding="utf-8"
    )
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "reviewer.yaml").write_text(
        "description: レビュー\ninstructions: 見る\ntools: [Read, Grep]\nread_only: true\n"
        "model: opus\neffort: high\n",
        encoding="utf-8",
    )
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "style.md").write_text(
        "---\ndescription: 書式\nglobs: ['src/**']\nalways: true\n---\n\nルール本文\n",
        encoding="utf-8",
    )

    spec = load_spec(tmp_path)

    assert spec.instructions.strip() == "共通指示"
    assert [s.id for s in spec.skills] == ["my-skill"]
    assert spec.skills[0].description == "説明です"
    assert spec.skills[0].body.strip() == "本文"
    agent = spec.agents[0]
    assert (agent.id, agent.tools, agent.read_only, agent.model, agent.effort) == (
        "reviewer",
        ("Read", "Grep"),
        True,
        "opus",
        "high",
    )
    rule = spec.rules[0]
    assert (rule.id, rule.description, rule.globs, rule.always) == (
        "style",
        "書式",
        ("src/**",),
        True,
    )
    assert rule.body.strip() == "ルール本文"


def test_missing_sections_are_empty(tmp_path: Path) -> None:
    (tmp_path / "instructions").mkdir()
    (tmp_path / "instructions" / "core.md").write_text("x", encoding="utf-8")

    spec = load_spec(tmp_path)

    assert (spec.skills, spec.agents, spec.rules) == ((), (), ())


def test_skill_references_and_claude_mapping(tmp_path: Path) -> None:
    (tmp_path / "instructions").mkdir()
    (tmp_path / "instructions" / "core.md").write_text("x", encoding="utf-8")
    skill_dir = tmp_path / "skills" / "deploy"
    (skill_dir / "references" / "deep").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: d\nclaude:\n  allowed-tools: Read\n---\nbody\n", encoding="utf-8"
    )
    (skill_dir / "references" / "a.md").write_text("A", encoding="utf-8")
    (skill_dir / "references" / "deep" / "b.md").write_text("B", encoding="utf-8")

    skill = load_spec(tmp_path).skills[0]

    assert dict(skill.references) == {"references/a.md": "A", "references/deep/b.md": "B"}
    assert dict(skill.claude_frontmatter) == {"allowed-tools": "Read"}


def test_missing_description_raises_with_path(tmp_path: Path) -> None:
    (tmp_path / "instructions").mkdir()
    (tmp_path / "instructions" / "core.md").write_text("x", encoding="utf-8")
    (tmp_path / "skills" / "bad").mkdir(parents=True)
    (tmp_path / "skills" / "bad" / "SKILL.md").write_text("---\nname: x\n---\nb", encoding="utf-8")

    with pytest.raises(SpecError) as raised:
        load_spec(tmp_path)

    assert "skills/bad/SKILL.md" in str(raised.value)


def test_unknown_agent_key_raises(tmp_path: Path) -> None:
    (tmp_path / "instructions").mkdir()
    (tmp_path / "instructions" / "core.md").write_text("x", encoding="utf-8")
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "a.yaml").write_text(
        "description: d\ninstructions: i\ntools: []\nread_only: false\nbogus: 1\n",
        encoding="utf-8",
    )

    with pytest.raises(SpecError) as raised:
        load_spec(tmp_path)

    assert "bogus" in str(raised.value)


def test_wrong_type_raises(tmp_path: Path) -> None:
    (tmp_path / "instructions").mkdir()
    (tmp_path / "instructions" / "core.md").write_text("x", encoding="utf-8")
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "a.yaml").write_text(
        "description: d\ninstructions: i\ntools: Read\nread_only: false\n", encoding="utf-8"
    )

    with pytest.raises(SpecError):
        load_spec(tmp_path)


def test_unknown_rule_frontmatter_key_raises(tmp_path: Path) -> None:
    (tmp_path / "instructions").mkdir()
    (tmp_path / "instructions" / "core.md").write_text("x", encoding="utf-8")
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "r.md").write_text(
        "---\ndescription: d\nzzz: 1\n---\nb", encoding="utf-8"
    )

    with pytest.raises(SpecError) as raised:
        load_spec(tmp_path)

    assert "zzz" in str(raised.value)


def test_missing_core_instructions_raises(tmp_path: Path) -> None:
    with pytest.raises(SpecError) as raised:
        load_spec(tmp_path)

    assert "instructions/core.md" in str(raised.value)
