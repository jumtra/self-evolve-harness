"""Authoring 候補の昇格証拠を検証する。"""

from pathlib import Path

from seh.authoring.classify import FileChange, classify_changes


def check_authoring_gate(
    root: Path, files: dict[str, bytes | None], record_path: str | None
) -> None:
    changes = classify_changes(FileChange(path, None, "change") for path in files)
    if not changes:
        return
    if not record_path:
        raise ValueError("AUTHORING_RECORD_REQUIRED")
    from seh.authoring.gate import GateStatus
    from seh.authoring.spec import load_record
    from seh.commands.author import _config, _gate, _load_eval_run

    record = load_record(Path(record_path))
    cfg = _config(root)
    run = _load_eval_run(root, record.candidate_run_id)
    if cfg is None or run is None or _gate(root, cfg, record, None).status is not GateStatus.PASS:
        raise ValueError("AUTHORING_GATE_NOT_PASSED")
    import hashlib

    for path, content in files.items():
        if not any(c.path == path for c in changes):
            continue
        if (
            path not in record.target_paths
            or not path.startswith(".harness/spec/")
            or content is None
        ):
            raise ValueError("AUTHORING_TARGET_NOT_EVALUATED")
        key = "file:" + path.removeprefix(".harness/spec/")
        if run.components.get(key) != hashlib.sha256(content).hexdigest():
            raise ValueError("AUTHORING_TARGET_CHANGED_AFTER_EVAL")
