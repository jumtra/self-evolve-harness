from pathlib import Path

from seh.contracts import HostId
from seh.providers.hosts.discovery import static_discovery


def test_opencode_sees_claude_and_shared_dirs(tmp_path: Path) -> None:
    planned = [".claude/skills/a/SKILL.md", ".agents/skills/a/SKILL.md"]

    seen = static_discovery([HostId.OPENCODE], planned, tmp_path)

    assert seen[HostId.OPENCODE]["a"] == (".claude/skills/a/SKILL.md", ".agents/skills/a/SKILL.md")


def test_codex_ignores_claude_dir(tmp_path: Path) -> None:
    planned = [".claude/skills/a/SKILL.md", ".agents/skills/a/SKILL.md"]

    seen = static_discovery([HostId.CODEX], planned, tmp_path)

    assert seen[HostId.CODEX]["a"] == (".agents/skills/a/SKILL.md",)


def test_existing_files_are_included_once(tmp_path: Path) -> None:
    existing = tmp_path / ".claude" / "skills" / "b" / "SKILL.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("x", encoding="utf-8")

    seen = static_discovery([HostId.CLAUDE], [".claude/skills/b/SKILL.md"], tmp_path)

    assert seen[HostId.CLAUDE]["b"] == (".claude/skills/b/SKILL.md",)
