import hashlib
from pathlib import Path

import pytest

from seh.trace import TraceWriter, read_trace


def test_emit_records_ids_in_order_with_masked_data(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "trace.jsonl"
    writer = TraceWriter(path)
    secret = "AKIA" + "A" * 16

    first = writer.emit("start", run_id="r1", task_id="t1", node_id="n1", data={"note": secret})
    second = writer.emit("end", run_id="r1", evidence_digest="sha256:abc")
    events = read_trace(path)

    assert [e["event"] for e in events] == ["start", "end"]
    assert [e["event_id"] for e in events] == [first, second]
    assert events[0]["run_id"] == "r1"
    assert events[0]["task_id"] == "t1"
    assert events[0]["node_id"] == "n1"
    assert secret not in path.read_text(encoding="utf-8")
    assert events[1]["evidence_digest"] == "sha256:abc"
    assert events[1]["task_id"] is None
    assert events[0]["ts"].endswith("+00:00") or events[0]["ts"].endswith("Z")


def test_prompt_key_is_replaced_by_digest_and_length(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = TraceWriter(path)
    prompt = "日本語のプロンプト本文"

    writer.emit("call", run_id="r1", data={"prompt": prompt})
    events = read_trace(path)

    assert events[0]["data"]["prompt"] == {
        "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "length": len(prompt),
    }
    assert prompt not in path.read_text(encoding="utf-8")


def test_read_trace_ignores_broken_last_line(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    TraceWriter(path).emit("ok", run_id="r1")
    with path.open("a", encoding="utf-8") as f:
        f.write('{"event": "tru')

    events = read_trace(path)

    assert [e["event"] for e in events] == ["ok"]


def test_read_trace_rejects_broken_middle_line(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    path.write_text('{"event": "a"}\nnot json\n{"event": "b"}\n', encoding="utf-8")

    with pytest.raises(ValueError):
        read_trace(path)
