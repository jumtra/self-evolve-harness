"""Evidence の保存先。URI は root 相対の論理名で、絶対パスを成果物に残さない。"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from seh.contracts import Evidence

_SCHEME = "artifact://"
_SAFE = re.compile(r"[A-Za-z0-9._-]+")


def _check_component(value: str, label: str) -> str:
    if not _SAFE.fullmatch(value) or value in (".", ".."):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, run_id: str, name: str, data: bytes | str) -> Evidence:
        _check_component(run_id, "run_id")
        _check_component(name, "name")
        payload = data.encode() if isinstance(data, str) else data
        directory = self._root / run_id
        directory.mkdir(parents=True, exist_ok=True)
        # 同一ディレクトリの一時ファイル + rename で読み手に書きかけを見せない
        fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
            os.replace(tmp_name, directory / name)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return Evidence(uri=f"{_SCHEME}{run_id}/{name}", sha256=hashlib.sha256(payload).hexdigest())

    def resolve(self, uri: str) -> Path:
        if not uri.startswith(_SCHEME):
            raise ValueError(f"unsupported uri: {uri!r}")
        parts = uri[len(_SCHEME) :].split("/")
        if len(parts) != 2:
            raise ValueError(f"invalid artifact uri: {uri!r}")
        run_id, name = (_check_component(p, "uri component") for p in parts)
        root = self._root.resolve()
        path = (root / run_id / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"uri escapes root: {uri!r}")
        return path

    def verify(self, evidence: Evidence) -> bool:
        path = self.resolve(evidence.uri)
        if not path.is_file():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == evidence.sha256
