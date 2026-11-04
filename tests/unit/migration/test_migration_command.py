import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

from seh.cli import main
from seh.migration import inventory
from seh.migration.inventory import KnownPath


class _FakeStdin(io.StringIO):
    def __init__(self, text: str, *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _write_v1_agent(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (root / ".claude/agents").mkdir(parents=True)
    (root / ".claude/agents/fixer.md").write_bytes(b"v1 fixer")
    known = {
        ".claude/agents/fixer.md": KnownPath(
            "agent", "DELETE", hashlib.sha256(b"v1 fixer").hexdigest()
        )
    }
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", known))


def test_plan_prints_items_and_saves_plan_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_v1_agent(tmp_path, monkeypatch)

    code = main(["migrate", "plan", "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "DELETE" in out
    assert ".claude/agents/fixer.md" in out
    assert len(list((tmp_path / ".harness/state").glob("migrate-plan-*.json"))) == 1


def test_plan_json_format_outputs_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_v1_agent(tmp_path, monkeypatch)

    code = main(["migrate", "plan", "--root", str(tmp_path), "--format", "json"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["items"][0]["action"] == "DELETE"


def test_plan_reports_no_v1_harness_with_exit_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(inventory, "load_known_paths", lambda: ("base", {}))

    code = main(["migrate", "plan", "--root", str(tmp_path)])

    assert code == 0
    assert "v1 ハーネスは見つかりません" in capsys.readouterr().out


def test_apply_without_tty_is_refused_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_v1_agent(tmp_path, monkeypatch)
    main(["migrate", "plan", "--root", str(tmp_path)])
    plan_file = next((tmp_path / ".harness/state").glob("migrate-plan-*.json"))
    monkeypatch.setattr(sys, "stdin", _FakeStdin("y\n", tty=False))

    code = main(["migrate", "apply", "--plan", str(plan_file), "--root", str(tmp_path)])

    assert code == 1
    assert "承認が必要です。対話モードで再実行してください" in capsys.readouterr().err
    assert (tmp_path / ".claude/agents/fixer.md").exists()


def test_apply_on_tty_with_y_applies_and_prints_rollback_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_v1_agent(tmp_path, monkeypatch)
    main(["migrate", "plan", "--root", str(tmp_path)])
    plan_file = next((tmp_path / ".harness/state").glob("migrate-plan-*.json"))
    monkeypatch.setattr(sys, "stdin", _FakeStdin("y\n", tty=True))

    code = main(["migrate", "apply", "--plan", str(plan_file), "--root", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert not (tmp_path / ".claude/agents/fixer.md").exists()
    assert "適用しますか? [y/N]" in out
    assert "seh migrate rollback " in out


def test_apply_on_tty_with_anything_but_y_does_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_v1_agent(tmp_path, monkeypatch)
    main(["migrate", "plan", "--root", str(tmp_path)])
    plan_file = next((tmp_path / ".harness/state").glob("migrate-plan-*.json"))
    monkeypatch.setattr(sys, "stdin", _FakeStdin("yes\n", tty=True))

    code = main(["migrate", "apply", "--plan", str(plan_file), "--root", str(tmp_path)])

    assert code == 1
    assert (tmp_path / ".claude/agents/fixer.md").exists()


def test_apply_reports_stale_plan_with_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_v1_agent(tmp_path, monkeypatch)
    main(["migrate", "plan", "--root", str(tmp_path)])
    plan_file = next((tmp_path / ".harness/state").glob("migrate-plan-*.json"))
    (tmp_path / ".claude/agents/fixer.md").write_bytes(b"changed")
    monkeypatch.setattr(sys, "stdin", _FakeStdin("y\n", tty=True))

    code = main(["migrate", "apply", "--plan", str(plan_file), "--root", str(tmp_path)])

    assert code == 1
    assert "計画後に変更" in capsys.readouterr().err
    assert (tmp_path / ".claude/agents/fixer.md").read_bytes() == b"changed"


def test_rollback_command_restores_files_and_prints_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_v1_agent(tmp_path, monkeypatch)
    main(["migrate", "plan", "--root", str(tmp_path)])
    plan_file = next((tmp_path / ".harness/state").glob("migrate-plan-*.json"))
    monkeypatch.setattr(sys, "stdin", _FakeStdin("y\n", tty=True))
    main(["migrate", "apply", "--plan", str(plan_file), "--root", str(tmp_path)])
    snapshot_id = next((tmp_path / ".harness/backups").iterdir()).name
    capsys.readouterr()

    code = main(["migrate", "rollback", snapshot_id, "--root", str(tmp_path)])

    assert code == 0
    assert ".claude/agents/fixer.md" in capsys.readouterr().out
    assert (tmp_path / ".claude/agents/fixer.md").read_bytes() == b"v1 fixer"


def test_approve_conflict_option_allows_replacing_modified_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_v1_agent(tmp_path, monkeypatch)
    (tmp_path / ".claude/agents/fixer.md").write_bytes(b"user edit")
    main(["migrate", "plan", "--root", str(tmp_path)])
    plan_file = next((tmp_path / ".harness/state").glob("migrate-plan-*.json"))
    monkeypatch.setattr(sys, "stdin", _FakeStdin("y\n", tty=True))

    code = main(
        [
            "migrate",
            "apply",
            "--plan",
            str(plan_file),
            "--root",
            str(tmp_path),
            "--approve-conflict",
            ".claude/agents/fixer.md",
        ]
    )

    assert code == 0
    assert not (tmp_path / ".claude/agents/fixer.md").exists()
