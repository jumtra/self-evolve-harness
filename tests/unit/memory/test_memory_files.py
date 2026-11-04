from seh.contracts.common import ResultStatus
from seh.contracts.module import MemoryRecord
from seh.providers.memory.files import FileMemoryProvider


def test_v1_file_is_listed_and_read_with_unknown_metadata(tmp_path):
    memdir = tmp_path / ".agent-memory"
    memdir.mkdir()
    (memdir / "feedback_reply_in_japanese.md").write_text(
        "---\n"
        "name: reply-in-japanese\n"
        "description: 説明はいつも日本語で返す\n"
        "metadata:\n"
        "  type: feedback\n"
        "  evolve: pending\n"
        "  count: 2\n"
        "  evolved_to: rules/lang.md\n"
        "---\n"
        "日本語で返す。\n\n**Why:** 指摘された\n",
        encoding="utf-8",
    )
    provider = FileMemoryProvider(tmp_path)

    listed = provider.list()
    got = provider.get("feedback_reply_in_japanese")

    assert listed.status is ResultStatus.OK
    assert isinstance(listed.data, list)
    assert isinstance(got.data, MemoryRecord)
    assert [r.id for r in listed.data] == ["feedback_reply_in_japanese"]
    assert got.data.title == "説明はいつも日本語で返す"
    assert got.data.type == "feedback"
    assert got.data.metadata["evolve"] == "pending"
    assert got.data.metadata["evolved_to"] == "rules/lang.md"
    assert "**Why:** 指摘された" in got.data.body


def test_update_keeps_v1_metadata_keys_and_index_lines(tmp_path):
    memdir = tmp_path / ".agent-memory"
    memdir.mkdir()
    (memdir / "feedback_reply_in_japanese.md").write_text(
        "---\n"
        "name: reply-in-japanese\n"
        "description: 説明はいつも日本語で返す\n"
        "metadata:\n"
        "  type: feedback\n"
        "  evolve: pending\n"
        "  count: 2\n"
        "---\n"
        "古い本文\n",
        encoding="utf-8",
    )
    (memdir / "MEMORY.md").write_text(
        "# MEMORY 索引\n\n"
        "<!-- 記憶の索引。規約は memory.md -->\n"
        "- [説明はいつも日本語で返す](feedback_reply_in_japanese.md) — 古い一言\n"
        "- [別の記憶](project_other.md) — 触らない行\n",
        encoding="utf-8",
    )
    provider = FileMemoryProvider(tmp_path)

    result = provider.save(
        MemoryRecord(
            id="feedback_reply_in_japanese",
            type="feedback",
            title="説明はいつも日本語で返す",
            body="新しい本文",
            metadata={"count": 3},
        )
    )

    text = (memdir / "feedback_reply_in_japanese.md").read_text(encoding="utf-8")
    index = (memdir / "MEMORY.md").read_text(encoding="utf-8")
    assert result.status is ResultStatus.OK
    assert "evolve: pending" in text
    assert "count: 3" in text
    assert "新しい本文" in text
    assert "古い本文" not in text
    assert "<!-- 記憶の索引。規約は memory.md -->" in index
    assert "- [別の記憶](project_other.md) — 触らない行" in index
    assert index.count("feedback_reply_in_japanese.md") == 1


def test_same_title_save_updates_instead_of_creating_new_file(tmp_path):
    provider = FileMemoryProvider(tmp_path)
    provider.save(MemoryRecord(id="", type="project", title="Home Layout", body="v1"))

    provider.save(MemoryRecord(id="", type="project", title="Home Layout", body="v2"))

    files = sorted(p.name for p in (tmp_path / ".agent-memory").glob("*.md"))
    assert files == ["MEMORY.md", "project_home_layout.md"]
    got = provider.get("project_home_layout")
    assert isinstance(got.data, MemoryRecord)
    assert got.data.body.strip() == "v2"


def test_save_adds_index_line_truncated_to_150_chars(tmp_path):
    provider = FileMemoryProvider(tmp_path)

    provider.save(MemoryRecord(id="", type="user", title="t" * 200, body="b"))

    lines = (tmp_path / ".agent-memory" / "MEMORY.md").read_text(encoding="utf-8").splitlines()
    entries = [line for line in lines if line.startswith("- [")]
    assert len(entries) == 1
    assert len(entries[0]) <= 150


def test_delete_removes_file_and_index_line_only(tmp_path):
    memdir = tmp_path / ".agent-memory"
    memdir.mkdir()
    (memdir / "MEMORY.md").write_text(
        "# MEMORY 索引\n- [残す](user_keep.md) — keep\n", encoding="utf-8"
    )
    provider = FileMemoryProvider(tmp_path)
    provider.save(MemoryRecord(id="", type="user", title="drop me", body="x"))

    result = provider.delete("user_drop_me")

    index = (memdir / "MEMORY.md").read_text(encoding="utf-8")
    assert result.status is ResultStatus.OK
    assert not (memdir / "user_drop_me.md").exists()
    assert "user_drop_me" not in index
    assert "- [残す](user_keep.md) — keep" in index
    assert provider.delete("user_drop_me").status is ResultStatus.NOT_FOUND


def test_secret_save_writes_nothing(tmp_path):
    provider = FileMemoryProvider(tmp_path)
    secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"

    result = provider.save(MemoryRecord(id="", type="reference", title="token", body=secret))

    assert result.status is ResultStatus.ERROR
    assert "SECRET_IN_MEMORY" in (result.message or "")
    assert not (tmp_path / ".agent-memory").exists()


def test_get_rejects_path_traversal_id(tmp_path):
    (tmp_path / "secret.md").write_text("---\nname: x\n---\nbody", encoding="utf-8")
    provider = FileMemoryProvider(tmp_path)

    result = provider.get("../secret")

    assert result.status is ResultStatus.ERROR


def test_search_matches_frontmatter_case_insensitively(tmp_path):
    memdir = tmp_path / ".agent-memory"
    memdir.mkdir()
    (memdir / "reference_api.md").write_text(
        "---\nname: api\ndescription: Billing API Notes\nmetadata:\n  type: reference\n---\nbody\n",
        encoding="utf-8",
    )
    provider = FileMemoryProvider(tmp_path)

    result = provider.search("billing api")

    assert result.status is ResultStatus.OK
    assert isinstance(result.data, list)
    assert [r.id for r in result.data] == ["reference_api"]
