from seh.providers.memory import engram
from seh.providers.memory.engram import EngramMemoryProvider
from seh.providers.memory.files import FileMemoryProvider
from seh.providers.memory.migrate import copy_memories
from seh.runtime.process import ProcessResult


def test_file_to_engram_copy_keeps_source_files(tmp_path, monkeypatch):
    memdir = tmp_path / ".agent-memory"
    memdir.mkdir()
    (memdir / "user_role.md").write_text(
        "---\nname: role\ndescription: user role\nmetadata:\n  type: user\n---\nengineer\n",
        encoding="utf-8",
    )
    (memdir / "MEMORY.md").write_text("# MEMORY 索引\n- [user role](user_role.md) — x\n")
    argvs = []

    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        argvs.append(list(argv))
        return ProcessResult("d", 0, b"saved", b"", False, False, False, False, 0.1)

    monkeypatch.setattr(engram, "run_process", fake_run_process)
    monkeypatch.setattr(engram.shutil, "which", lambda cmd: "/usr/bin/engram")

    report = copy_memories(FileMemoryProvider(tmp_path), EngramMemoryProvider(project="demo"))

    assert report.copied == 1
    assert report.errors == []
    assert argvs[0][:4] == ["engram", "save", "user role", "engineer\n"]
    assert (memdir / "user_role.md").is_file()
    assert "user_role.md" in (memdir / "MEMORY.md").read_text()


def test_copy_to_unavailable_engram_reports_errors_and_keeps_source(tmp_path, monkeypatch):
    memdir = tmp_path / ".agent-memory"
    memdir.mkdir()
    (memdir / "user_role.md").write_text(
        "---\nname: role\ndescription: user role\nmetadata:\n  type: user\n---\nengineer\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(engram.shutil, "which", lambda cmd: None)

    report = copy_memories(FileMemoryProvider(tmp_path), EngramMemoryProvider(project="demo"))

    assert report.copied == 0
    assert len(report.errors) == 1
    assert "engram が見つかりません" in report.errors[0]
    assert (memdir / "user_role.md").is_file()


def test_copy_does_not_touch_real_repo_memory(tmp_path):
    src = FileMemoryProvider(tmp_path / "a")
    dst = FileMemoryProvider(tmp_path / "b")

    report = copy_memories(src, dst)

    assert (report.copied, report.skipped, report.errors) == (0, 0, [])
