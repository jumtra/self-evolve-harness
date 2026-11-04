"""Node 単位の JSONL trace。data は常にマスクして書く。"""

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from seh.redaction import mask_obj


class TraceWriter:
    def __init__(self, path: Path) -> None:
        self._path = path

    def emit(
        self,
        event: str,
        *,
        run_id: str,
        task_id: str | None = None,
        node_id: str | None = None,
        data: Mapping[str, object] | None = None,
        evidence_digest: str | None = None,
    ) -> str:
        event_id = uuid.uuid4().hex
        payload = dict(data) if data else {}
        prompt = payload.get("prompt")
        if prompt is not None:
            raw = prompt if isinstance(prompt, str) else json.dumps(prompt, ensure_ascii=False)
            payload["prompt"] = {
                "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                "length": len(raw),
            }
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "event_id": event_id,
            "event": event,
            "run_id": run_id,
            "task_id": task_id,
            "node_id": node_id,
            "data": mask_obj(payload),
            "evidence_digest": evidence_digest,
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
        return event_id


def read_trace(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    events: list[dict] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as e:
            if index == len(lines) - 1:
                break
            raise ValueError(f"{path}: line {index + 1} is not valid JSON") from e
    return events
