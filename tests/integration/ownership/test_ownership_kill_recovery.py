import os
import subprocess
import sys
from pathlib import Path

from seh.ownership import Transaction, recover_incomplete

SRC = str(Path(__file__).resolve().parents[3] / "src")


def test_recover_incomplete_after_process_killed_mid_transaction(tmp_path: Path) -> None:
    (tmp_path / "mod.txt").write_bytes(b"orig")
    (tmp_path / "gone.txt").write_bytes(b"keep me")
    (tmp_path / "link").symlink_to("target-a")
    script = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "from seh.ownership import Transaction\n"
        "tx = Transaction(Path(sys.argv[1]))\n"
        "tx.__enter__()\n"
        "tx.write('mod.txt', b'changed')\n"
        "tx.write('deep/new.txt', b'n')\n"
        "tx.delete('gone.txt')\n"
        "tx.replace_symlink('link', 'other')\n"
        "os._exit(1)\n"
    )
    env = {**os.environ, "PYTHONPATH": SRC}

    proc = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], env=env, capture_output=True
    )
    assert proc.returncode == 1, proc.stderr
    assert (tmp_path / "mod.txt").read_bytes() == b"changed"

    recovered = recover_incomplete(tmp_path)

    assert len(recovered) == 1
    assert (tmp_path / "mod.txt").read_bytes() == b"orig"
    assert (tmp_path / "gone.txt").read_bytes() == b"keep me"
    assert os.readlink(tmp_path / "link") == "target-a"
    assert not (tmp_path / "deep").exists()


def test_recover_incomplete_is_idempotent_after_kill(tmp_path: Path) -> None:
    (tmp_path / "mod.txt").write_bytes(b"orig")
    script = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "from seh.ownership import Transaction\n"
        "tx = Transaction(Path(sys.argv[1]))\n"
        "tx.write('mod.txt', b'changed')\n"
        "os._exit(1)\n"
    )
    env = {**os.environ, "PYTHONPATH": SRC}
    subprocess.run([sys.executable, "-c", script, str(tmp_path)], env=env, capture_output=True)

    first = recover_incomplete(tmp_path)
    (tmp_path / "mod.txt").write_bytes(b"user edit")
    second = recover_incomplete(tmp_path)

    assert len(first) == 1
    assert second == []
    assert (tmp_path / "mod.txt").read_bytes() == b"user edit"


def test_recover_incomplete_skips_committed_transaction(tmp_path: Path) -> None:
    with Transaction(tmp_path) as tx:
        tx.write("a.txt", b"x")

    assert recover_incomplete(tmp_path) == []
    assert (tmp_path / "a.txt").read_bytes() == b"x"


def test_recover_incomplete_skips_in_progress_transaction_of_live_process(tmp_path: Path) -> None:
    (tmp_path / "mod.txt").write_bytes(b"orig")
    tx = Transaction(tmp_path)
    tx.write("mod.txt", b"changed")

    recovered = recover_incomplete(tmp_path)

    assert recovered == []
    assert (tmp_path / "mod.txt").read_bytes() == b"changed"
