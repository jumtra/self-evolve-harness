import hashlib
import shutil
from pathlib import Path

from seh.migration import inventory
from seh.migration.inventory import KnownPath
from seh.migration.planner import MigrationAction, plan_migration

E10_REPO = Path(__file__).parents[2] / "fixtures/eval/E10/repo"


def test_e10_v1_sample_plan_keeps_user_files_and_flags_modified_v1_file(
    tmp_path: Path, monkeypatch
) -> None:
    for src in (E10_REPO / "v1_sample/dot_claude").rglob("*.fixture"):
        rel = src.relative_to(E10_REPO / "v1_sample/dot_claude").with_suffix("")
        dest = tmp_path / ".claude" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    team_notes = tmp_path / "notes/team.md"
    team_notes.parent.mkdir()
    shutil.copyfile(E10_REPO / "v1_sample/notes/team.md", team_notes)
    # E10 の work Skill は v1 管理物。ここでは「手編集済み」として baseline と別 hash にする
    known = {
        ".claude/skills/work/SKILL.md": KnownPath(
            "skill", "DELETE", hashlib.sha256(b"pristine v1 work skill").hexdigest()
        )
    }
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))

    plan = plan_migration(tmp_path)

    assert {i.path: i.action for i in plan.items} == {
        ".claude/skills/work/SKILL.md": MigrationAction.USER_OWNED_CONFLICT,
    }
    assert (tmp_path / ".claude/skills/review/SKILL.md").exists()
    assert team_notes.exists()
