import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from seh.cli import main
from seh.contracts import (
    CanonicalSpec,
    ChangeAction,
    Diagnostic,
    DiscoveryReport,
    GeneratedPlan,
    HostId,
    PlannedChange,
    RenderContext,
    RuntimeCapabilityReport,
)
from seh.contracts.host import HostAdapter
from seh.providers.hosts.codex import CodexHostAdapter


class SettingsAdapter:
    id = HostId.CLAUDE

    def probe(self) -> RuntimeCapabilityReport:
        return RuntimeCapabilityReport(self.id.value, False, None, None, {}, False, ())

    def render(self, spec: CanonicalSpec, ctx: RenderContext) -> GeneratedPlan:
        change = PlannedChange(".claude/settings.json", ChangeAction.UPDATE, b"{}\n", "r", "o")
        return GeneratedPlan(self.id, (change,), (), ())

    def lint(self, plan: GeneratedPlan) -> tuple[Diagnostic, ...]:
        return ()

    def discover(self, workspace: Path) -> DiscoveryReport:
        return DiscoveryReport(self.id, {}, ())


def write_project(root: Path, hosts: str) -> None:
    (root / ".harness" / "spec" / "instructions").mkdir(parents=True)
    (root / ".harness" / "spec" / "instructions" / "core.md").write_text("指示\n", encoding="utf-8")
    (root / ".harness" / "config.toml").write_text(
        f"[hosts]\nenabled = [{hosts}]\n", encoding="utf-8"
    )


def test_plan_prints_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_project(tmp_path, '"codex"')

    code = main(["sync", "--root", str(tmp_path), "--plan"])

    out = capsys.readouterr().out
    assert code == 0
    assert "AGENTS.md" in out
    assert not (tmp_path / "AGENTS.md").exists()


def test_plan_json_lists_items(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_project(tmp_path, '"codex"')

    code = main(["sync", "--root", str(tmp_path), "--plan", "--format", "json"])

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    items = {item["path"]: item for item in document["items"]}
    assert items["AGENTS.md"]["risk"] == "R1"
    assert items[".codex/hooks.json"]["risk"] == "R2"


def test_missing_config_tells_user_to_init(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["sync", "--root", str(tmp_path), "--plan"])

    assert code == 1
    assert "seh init" in capsys.readouterr().err


def test_hosts_option_overrides_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_project(tmp_path, '"codex"')

    code = main(["sync", "--root", str(tmp_path), "--plan", "--hosts", "claude"])

    out = capsys.readouterr().out
    assert code == 0
    assert "CLAUDE.md" in out


def test_apply_low_risk_needs_no_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project(tmp_path, '"codex"')

    class LowRiskAdapter(CodexHostAdapter):
        def render(self, spec: CanonicalSpec, ctx: RenderContext) -> GeneratedPlan:
            plan = super().render(spec, ctx)
            return replace(plan, changes=tuple(c for c in plan.changes if c.path == "AGENTS.md"))

    monkeypatch.setattr(
        "seh.commands.sync.default_adapters", lambda: {HostId.CODEX: LowRiskAdapter()}
    )
    monkeypatch.setattr("seh.commands.sync._cli_versions", lambda adapters, hosts: {})

    code = main(["sync", "--root", str(tmp_path), "--apply"])

    assert code == 0
    assert "指示" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert (tmp_path / ".harness/generated.lock.json").is_file()


def test_apply_with_r2_item_refuses_without_tty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_project(tmp_path, '"claude"')
    adapters: Mapping[HostId, HostAdapter] = {HostId.CLAUDE: SettingsAdapter()}
    monkeypatch.setattr("seh.commands.sync.default_adapters", lambda: adapters)
    monkeypatch.setattr("seh.commands.sync._cli_versions", lambda adapters, hosts: {})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    code = main(["sync", "--root", str(tmp_path), "--apply"])

    assert code == 1
    assert "承認が必要です" in capsys.readouterr().err
    assert not (tmp_path / ".claude").exists()


def test_apply_with_r2_item_proceeds_after_tty_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project(tmp_path, '"claude"')
    adapters: Mapping[HostId, HostAdapter] = {HostId.CLAUDE: SettingsAdapter()}
    monkeypatch.setattr("seh.commands.sync.default_adapters", lambda: adapters)
    monkeypatch.setattr("seh.commands.sync._cli_versions", lambda adapters, hosts: {})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    code = main(["sync", "--root", str(tmp_path), "--apply"])

    assert code == 0
    assert (tmp_path / ".claude/settings.json").read_text(encoding="utf-8") == "{}\n"


def test_apply_tty_no_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_project(tmp_path, '"claude"')
    adapters: Mapping[HostId, HostAdapter] = {HostId.CLAUDE: SettingsAdapter()}
    monkeypatch.setattr("seh.commands.sync.default_adapters", lambda: adapters)
    monkeypatch.setattr("seh.commands.sync._cli_versions", lambda adapters, hosts: {})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    code = main(["sync", "--root", str(tmp_path), "--apply"])

    assert code == 1
    assert not (tmp_path / ".claude").exists()


def test_apply_blocks_on_conflict_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project(tmp_path, '"codex"')
    (tmp_path / "AGENTS.md").write_text("x", encoding="utf-8")
    block_file = tmp_path / ".agents/skills/s/SKILL.md"
    block_file.parent.mkdir(parents=True)
    block_file.write_text("手書き", encoding="utf-8")
    (tmp_path / ".harness/spec/skills/s").mkdir(parents=True)
    (tmp_path / ".harness/spec/skills/s/SKILL.md").write_text(
        "---\ndescription: d\n---\nb", encoding="utf-8"
    )
    monkeypatch.setattr("seh.commands.sync._cli_versions", lambda adapters, hosts: {})

    code = main(["sync", "--root", str(tmp_path), "--apply"])

    assert code == 1
    assert block_file.read_text(encoding="utf-8") == "手書き"
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "x"


def test_codex_hook_requires_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write_project(tmp_path, '"codex"')
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    code = main(["sync", "--root", str(tmp_path), "--apply"])
    assert code == 1
    assert "承認が必要です" in capsys.readouterr().err
    assert not (tmp_path / ".codex/hooks.json").exists()
    assert not (tmp_path / "AGENTS.md").exists()
