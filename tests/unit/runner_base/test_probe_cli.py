import shutil

from seh.contracts import CapabilityLevel
from seh.runtime.cli_capability import ProbeSpec, probe_cli, probe_cli_async


def test_probe_reports_version_and_native_when_flags_present():
    spec = ProbeSpec(command="python3", required_flags={"version_flag": ("--version",)})

    report = probe_cli("py", spec)

    assert report.installed is True
    assert report.version is not None
    assert report.version[0].isdigit()
    assert report.capabilities["version_flag"] is CapabilityLevel.NATIVE
    assert report.authenticated is None
    assert report.policy_blocked is False


def test_probe_marks_capability_unsupported_when_flag_missing_from_help():
    spec = ProbeSpec(
        command="python3",
        required_flags={"ok": ("--version",), "bogus": ("--version", "--no-such-flag-xyz")},
    )

    report = probe_cli("py", spec)

    assert report.capabilities["ok"] is CapabilityLevel.NATIVE
    assert report.capabilities["bogus"] is CapabilityLevel.UNSUPPORTED


def test_probe_reports_not_installed_for_missing_command():
    spec = ProbeSpec(command="seh-no-such-command-xyz", required_flags={"x": ("--x",)})

    report = probe_cli("ghost", spec)

    assert report.installed is False
    assert report.version is None
    assert report.capabilities["x"] is CapabilityLevel.UNSUPPORTED


def test_probe_report_does_not_contain_absolute_executable_path():
    spec = ProbeSpec(command="python3", required_flags={"version_flag": ("--version",)})
    resolved = shutil.which("python3")

    report = probe_cli("py", spec)

    assert resolved is not None
    assert resolved not in repr(report)


def test_probe_with_policy_blocked_still_reports_and_flags_block():
    spec = ProbeSpec(command="python3", required_flags={"version_flag": ("--version",)})

    report = probe_cli("py", spec, policy_blocked=True)

    assert report.policy_blocked is True
    assert report.installed is True


async def test_probe_cli_can_be_called_from_running_event_loop():
    spec = ProbeSpec(command="python3", required_flags={"version_flag": ("--version",)})

    report = probe_cli("py", spec)

    assert report.installed is True
    assert report.capabilities["version_flag"] is CapabilityLevel.NATIVE


async def test_probe_cli_async_returns_report():
    spec = ProbeSpec(command="python3", required_flags={"version_flag": ("--version",)})

    report = await probe_cli_async("py", spec)

    assert report.installed is True
