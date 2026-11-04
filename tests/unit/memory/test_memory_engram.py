from seh.contracts.common import ResultStatus
from seh.contracts.module import HealthResult, MemoryRecord
from seh.providers.memory import engram
from seh.providers.memory.engram import EngramMemoryProvider
from seh.runtime.process import ProcessResult


def test_healthcheck_explains_missing_engram(monkeypatch):
    monkeypatch.setattr(engram.shutil, "which", lambda cmd: None)

    result = EngramMemoryProvider(project="demo").healthcheck()

    assert isinstance(result.data, HealthResult)
    assert result.data.ok is False
    assert "engram が見つかりません" in result.data.message
    assert 'memory.provider = "file"' in result.data.message


def test_save_without_engram_is_error_with_guidance(monkeypatch):
    monkeypatch.setattr(engram.shutil, "which", lambda cmd: None)
    record = MemoryRecord(id="user_a", type="user", title="a", body="b")

    result = EngramMemoryProvider(project="demo").save(record)

    assert result.status is ResultStatus.ERROR
    assert 'memory.provider = "file"' in (result.message or "")


def test_save_passes_arguments_as_argv_without_shell_expansion(monkeypatch):
    calls = []

    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        calls.append(list(argv))
        return ProcessResult("d", 0, b"ok", b"", False, False, False, False, 0.1)

    monkeypatch.setattr(engram, "run_process", fake_run_process)
    monkeypatch.setattr(engram.shutil, "which", lambda cmd: "/usr/bin/engram")
    record = MemoryRecord(id="user_a", type="user", title="$(echo hi); rm", body="`x` && y")

    EngramMemoryProvider(project="demo").save(record)

    assert calls[0][:4] == ["engram", "save", "$(echo hi); rm", "`x` && y"]
    assert calls[0][-2:] == ["--project", "demo"]


def test_unparseable_search_output_is_error_not_empty_ok(monkeypatch):
    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        return ProcessResult("d", 0, b"???garbage", b"", False, False, False, False, 0.1)

    monkeypatch.setattr(engram, "run_process", fake_run_process)
    monkeypatch.setattr(engram.shutil, "which", lambda cmd: "/usr/bin/engram")

    result = EngramMemoryProvider(project="demo").search("x")

    assert result.status is ResultStatus.ERROR


def test_nonzero_exit_is_error(monkeypatch):
    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        return ProcessResult("d", 1, b"", b"connection refused", False, False, False, False, 0.1)

    monkeypatch.setattr(engram, "run_process", fake_run_process)
    monkeypatch.setattr(engram.shutil, "which", lambda cmd: "/usr/bin/engram")

    result = EngramMemoryProvider(project="demo").search("x")

    assert result.status is ResultStatus.ERROR
    assert "connection refused" in (result.message or "")


def test_search_argv_matches_cli_usage_and_real_no_result_message(monkeypatch):
    calls = []

    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        calls.append(list(argv))
        out = b'No memories found for: "q"'
        return ProcessResult("d", 0, out, b"", False, False, False, False, 0.1)

    monkeypatch.setattr(engram, "run_process", fake_run_process)
    monkeypatch.setattr(engram.shutil, "which", lambda cmd: "/usr/bin/engram")

    result = EngramMemoryProvider(project="demo").search("q")

    assert calls == [["engram", "search", "q", "--project", "demo"]]
    assert result.status is ResultStatus.NOT_FOUND
