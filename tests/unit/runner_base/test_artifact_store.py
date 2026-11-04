import hashlib

import pytest

from seh.artifacts import ArtifactStore


def test_put_writes_file_and_returns_evidence_with_content_hash(tmp_path):
    store = ArtifactStore(tmp_path)

    evidence = store.put("run1", "events.jsonl", "hello")

    assert evidence.uri == "artifact://run1/events.jsonl"
    assert evidence.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert (tmp_path / "run1" / "events.jsonl").read_bytes() == b"hello"


def test_put_accepts_bytes_and_overwrites_existing(tmp_path):
    store = ArtifactStore(tmp_path)
    store.put("run1", "a.bin", b"old")

    evidence = store.put("run1", "a.bin", b"new")

    assert (tmp_path / "run1" / "a.bin").read_bytes() == b"new"
    assert evidence.sha256 == hashlib.sha256(b"new").hexdigest()


def test_resolve_returns_path_under_root(tmp_path):
    store = ArtifactStore(tmp_path)
    evidence = store.put("run1", "a.txt", "x")

    path = store.resolve(evidence.uri)

    assert path == (tmp_path / "run1" / "a.txt").resolve()


def test_verify_true_for_intact_artifact(tmp_path):
    store = ArtifactStore(tmp_path)
    evidence = store.put("run1", "a.txt", "x")

    assert store.verify(evidence) is True


def test_verify_false_when_content_tampered(tmp_path):
    store = ArtifactStore(tmp_path)
    evidence = store.put("run1", "a.txt", "x")
    (tmp_path / "run1" / "a.txt").write_text("tampered")

    assert store.verify(evidence) is False


def test_verify_false_when_artifact_missing(tmp_path):
    store = ArtifactStore(tmp_path)
    evidence = store.put("run1", "a.txt", "x")
    (tmp_path / "run1" / "a.txt").unlink()

    assert store.verify(evidence) is False


@pytest.mark.parametrize(
    "uri",
    [
        "file:///etc/passwd",
        "artifact://run1/../escape",
        "artifact://../a.txt",
        "artifact:///etc/passwd",
        "artifact://run1/sub/a.txt",
        "artifact://run1",
        "artifact://run1/",
        "/etc/passwd",
    ],
)
def test_resolve_rejects_invalid_or_escaping_uri(tmp_path, uri):
    store = ArtifactStore(tmp_path)

    with pytest.raises(ValueError):
        store.resolve(uri)


@pytest.mark.parametrize(
    ("run_id", "name"),
    [
        ("..", "a.txt"),
        ("run1", ".."),
        ("run1", "../a.txt"),
        ("a/b", "a.txt"),
        ("run1", ""),
        ("run1", "a b"),
    ],
)
def test_put_rejects_unsafe_names(tmp_path, run_id, name):
    store = ArtifactStore(tmp_path)

    with pytest.raises(ValueError):
        store.put(run_id, name, "x")
