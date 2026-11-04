from pathlib import Path

from seh.audit import Reference, deleted_names, find_dangling_references


def _write(root: Path, rel: str, content: str | bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def test_deleted_names_contains_removed_assets_only() -> None:
    names = deleted_names()

    assert {"brainstorm", "create-pr", "self-review"} <= names.skills
    assert {"test-writer", "refactorer"} <= names.agents
    assert {"debugging", "workflow"} <= names.rules
    assert names.skills.isdisjoint({"harness-init"})
    assert names.agents.isdisjoint({"implementer", "reviewer", "fixer", "evolver"})


def test_detects_slash_command(tmp_path: Path) -> None:
    _write(tmp_path, "README.md", "intro\n`/brainstorm` で開始する\n")

    refs = find_dangling_references(tmp_path)

    assert refs == [Reference("README.md", 2, "skill", "brainstorm", "`/brainstorm` で開始する")]


def test_detects_skill_path_and_skill_call(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "see .claude/skills/create-pr/SKILL.md\nSkill(self-review)\n")

    refs = find_dangling_references(tmp_path)

    assert [(r.line, r.kind, r.name) for r in refs] == [
        (1, "skill", "create-pr"),
        (2, "skill", "self-review"),
    ]


def test_detects_skill_with_japanese_suffix(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "`desloppify` スキルを使う\n")

    refs = find_dangling_references(tmp_path)

    assert [(r.kind, r.name) for r in refs] == [("skill", "desloppify")]


def test_detects_agent_patterns(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.md",
        ".claude/agents/test-writer.md\n"
        "subagent_type: refactorer\n"
        'Agent(subagent_type="researcher")\n'
        "`ci-triage` エージェント\n",
    )

    refs = find_dangling_references(tmp_path)

    assert [(r.line, r.kind, r.name) for r in refs] == [
        (1, "agent", "test-writer"),
        (2, "agent", "refactorer"),
        (3, "agent", "researcher"),
        (4, "agent", "ci-triage"),
    ]


def test_detects_rule_path(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "参照: .claude/rules/workflow.md\n")

    refs = find_dangling_references(tmp_path)

    assert [(r.kind, r.name) for r in refs] == [("rule", "workflow")]


def test_ignores_generic_words(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "a.md",
        "この workflow は単純\nmemory を使う\nsrc/brainstorm/x と path/debugging\n",
    )

    assert find_dangling_references(tmp_path) == []


def test_ignores_surviving_assets(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "/harness-init\nsubagent_type: implementer\n.claude/rules/coding.md\n")

    assert find_dangling_references(tmp_path) == []


def test_truncates_long_line_text(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", "/brainstorm " + "x" * 500 + "\n")

    refs = find_dangling_references(tmp_path)

    assert len(refs[0].text) == 200


def test_excluded_paths_are_not_counted(tmp_path: Path) -> None:
    for rel in (
        "docs/design/a.md",
        "src/seh/migration/x.py",
        "tests/fixtures/v1/a.md",
        "CHANGELOG.md",
        ".git/x.md",
        "tests/unit/audit/t.md",
    ):
        _write(tmp_path, rel, "/brainstorm\n")

    assert find_dangling_references(tmp_path) == []


def test_v1_assets_themselves_are_excluded(tmp_path: Path) -> None:
    _write(tmp_path, ".claude/skills/brainstorm/SKILL.md", "/brainstorm\n")
    _write(tmp_path, ".claude/rules/memory.md", ".claude/rules/workflow.md\n")

    assert find_dangling_references(tmp_path) == []


def test_custom_excludes_replace_defaults(tmp_path: Path) -> None:
    _write(tmp_path, "docs/design/a.md", "/brainstorm\n")
    _write(tmp_path, "skip/a.md", "/brainstorm\n")

    refs = find_dangling_references(tmp_path, excludes=("skip/**",))

    assert [r.path for r in refs] == ["docs/design/a.md"]


def test_does_not_follow_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    root = tmp_path / "root"
    _write(outside, "a.md", "/brainstorm\n")
    root.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "file.md").symlink_to(outside / "a.md")

    assert find_dangling_references(root) == []


def test_ignores_binary_and_large_files(tmp_path: Path) -> None:
    _write(tmp_path, "bin.dat", b"\xff\xfe/brainstorm\n")
    _write(tmp_path, "big.md", "/brainstorm\n" + "a" * (1024 * 1024 + 1))

    assert find_dangling_references(tmp_path) == []
