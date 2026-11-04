"""File / Engram の2実装に同じ Memory API テストを流す (FR-040)。"""

import pytest

from seh.contracts.common import ResultStatus
from seh.contracts.module import MemoryRecord
from seh.providers.memory import engram
from seh.providers.memory.engram import EngramMemoryProvider
from seh.providers.memory.files import FileMemoryProvider
from seh.runtime.process import ProcessResult


@pytest.fixture(params=["file", "engram"], ids=["file", "engram"])
def memory(request, tmp_path, monkeypatch):
    """(provider, get/delete が使えるか)。Engram は CLI 接続をモックする。"""
    if request.param == "file":
        return FileMemoryProvider(tmp_path), True

    saved: list[tuple[str, str, str]] = []

    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        if argv[1] == "save":
            saved.append((argv[2], argv[3], argv[argv.index("--type") + 1]))
            return ProcessResult("d", 0, b"Memory saved\n", b"", False, False, False, False, 0.1)
        query = argv[2].lower()
        lines = [
            f"#{i} [{kind}] {title}\n  {body}"
            for i, (title, body, kind) in enumerate(saved, 1)
            if query in f"{title} {body}".lower()
        ]
        out = "\n".join(lines) if lines else f'No memories found for: "{argv[2]}"'
        return ProcessResult("d", 0, out.encode(), b"", False, False, False, False, 0.1)

    monkeypatch.setattr(engram, "run_process", fake_run_process)
    monkeypatch.setattr(engram.shutil, "which", lambda cmd: "/usr/bin/engram")
    return EngramMemoryProvider(project="demo"), False


def test_saved_record_is_found_by_search(memory):
    provider, _ = memory
    record = MemoryRecord(
        id="feedback_reply_in_japanese",
        type="feedback",
        title="reply in japanese",
        body="Always answer in Japanese.",
    )

    saved = provider.save(record)
    found = provider.search("japanese")

    assert saved.status is ResultStatus.OK
    assert found.status is ResultStatus.OK
    assert isinstance(found.data, list)
    assert [r.title for r in found.data] == ["reply in japanese"]
    assert found.data[0].type == "feedback"


def test_search_without_match_is_not_found(memory):
    provider, _ = memory
    provider.save(MemoryRecord(id="user_a", type="user", title="alpha", body="first"))

    result = provider.search("zzz-nothing")

    assert result.status is ResultStatus.NOT_FOUND


def test_get_returns_record_or_unsupported(memory):
    provider, supports_lookup = memory
    provider.save(MemoryRecord(id="project_plan", type="project", title="plan", body="ship it"))

    result = provider.get("project_plan")

    if supports_lookup:
        assert result.status is ResultStatus.OK
        assert isinstance(result.data, MemoryRecord)
        assert result.data.body.strip() == "ship it"
    else:
        assert result.status is ResultStatus.UNSUPPORTED


def test_delete_removes_record_or_is_unsupported(memory):
    provider, supports_lookup = memory
    provider.save(MemoryRecord(id="project_plan", type="project", title="plan", body="ship it"))

    deleted = provider.delete("project_plan")
    after = provider.search("ship")

    if supports_lookup:
        assert deleted.status is ResultStatus.OK
        assert after.status is ResultStatus.NOT_FOUND
    else:
        assert deleted.status is ResultStatus.UNSUPPORTED


def test_secret_is_rejected_and_not_saved(memory):
    provider, _ = memory
    secret = "sk-ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    record = MemoryRecord(id="reference_key", type="reference", title="key", body=f"key {secret}")

    result = provider.save(record)

    assert result.status is ResultStatus.ERROR
    assert result.message is not None
    assert "SECRET_IN_MEMORY" in result.message
    assert provider.search("key").status is ResultStatus.NOT_FOUND
