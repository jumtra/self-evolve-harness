import subprocess
import sys

import pytest

from seh import __version__
from seh.cli import main
from seh.commands import GROUPS


def test_help_lists_every_group(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    out = capsys.readouterr().out
    assert exc.value.code == 0
    for group in GROUPS:
        assert group in out


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_subcommand_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    code = main([])

    assert code == 2
    assert "usage" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("group", GROUPS)
def test_stub_returns_2_with_message(group: str, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([group])

    assert code == 2
    assert f"未実装: seh {group}" in capsys.readouterr().err


def test_module_entrypoint_runs_as_script() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "seh", "--version"], capture_output=True, text=True
    )

    assert result.returncode == 0
    assert __version__ in result.stdout
