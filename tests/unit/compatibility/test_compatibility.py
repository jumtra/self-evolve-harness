from pathlib import Path

from seh.compatibility import build_report
from seh.contracts import (
    CanonicalSpec,
    CapabilityLevel,
    Diagnostic,
    DiscoveryReport,
    GeneratedPlan,
    HostCapability,
    HostId,
    RenderContext,
    RuntimeCapabilityReport,
)


class FakeAdapter:
    def __init__(self, host: HostId, installed: bool = True, policy_blocked: bool = False):
        self.id = host
        self.installed = installed
        self.policy_blocked = policy_blocked

    def probe(self) -> RuntimeCapabilityReport:
        return RuntimeCapabilityReport(
            self.id.value,
            self.installed,
            "1.0" if self.installed else None,
            None,
            {"json": CapabilityLevel.NATIVE},
            self.policy_blocked,
            (),
        )

    def render(self, spec: CanonicalSpec, ctx: RenderContext) -> GeneratedPlan:

        return GeneratedPlan(
            self.id, (), (), (HostCapability("hooks", CapabilityLevel.UNVERIFIED, "not tested"),)
        )

    def lint(self, plan: GeneratedPlan) -> tuple[Diagnostic, ...]:
        return ()

    def discover(self, workspace: Path) -> DiscoveryReport:

        paths = (".agents/skills/work/SKILL.md", ".claude/skills/work/SKILL.md")
        return DiscoveryReport(self.id, {"work": paths}, ("work",))


def test_reports_collision_hashes_and_unknown_permissions(tmp_path: Path):
    for base in (".agents", ".claude"):
        path = tmp_path / base / "skills/work/SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(base)
    result = build_report(
        tmp_path, [HostId.OPENCODE], adapters={HostId.OPENCODE: FakeAdapter(HostId.OPENCODE)}
    )
    host = result["hosts"]["opencode"]
    assert host["verdict"] == "PARTIAL"
    assert host["collisions"] == ["work"]
    assert len(host["skills"]["work"][0]["sha256"]) == 64
    assert host["skills"]["work"][0]["effective_permissions"] == "UNVERIFIED"
    assert "Graphify" in result["graphify"]["reason"]


def test_missing_cli_is_blocked(tmp_path):
    result = build_report(
        tmp_path, [HostId.CODEX], adapters={HostId.CODEX: FakeAdapter(HostId.CODEX, False)}
    )
    assert result["hosts"]["codex"]["verdict"] == "BLOCKED"


def test_report_uses_canonical_permissions_and_reports_unsupported_mapping(tmp_path):
    from seh.sync import default_adapters

    spec = tmp_path / ".harness/spec"
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions/core.md").write_text("instructions")
    (spec / "permissions.yaml").write_text("write: deny\n")
    adapter = default_adapters()[HostId.CODEX]
    result = build_report(tmp_path, [HostId.CODEX], adapters={HostId.CODEX: adapter})
    host = result["hosts"]["codex"]
    assert host["canonical_spec"]["permissions"] == {"write": "deny"}
    assert host["permissions"]["effective"] == "UNVERIFIED"
    assert any(d["code"] == "UNSUPPORTED_PERMISSION" for d in host["diagnostics"])
    assert host["verdict"] == "BLOCKED"


def test_missing_and_invalid_spec_are_explicit(tmp_path):
    host = HostId.CODEX
    adapter = FakeAdapter(host)
    missing = build_report(tmp_path, [host], adapters={host: adapter})["hosts"]["codex"]
    assert missing["canonical_spec"]["status"] == "MISSING"
    spec = tmp_path / ".harness/spec"
    spec.mkdir(parents=True)
    invalid = build_report(tmp_path, [host], adapters={host: adapter})["hosts"]["codex"]
    assert invalid["canonical_spec"]["status"] == "INVALID"
    assert invalid["verdict"] == "BLOCKED"


def test_compatible_requested_permissions_are_not_claimed_effective(tmp_path):
    from seh.sync import default_adapters

    spec = tmp_path / ".harness/spec"
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions/core.md").write_text("instructions")
    (spec / "permissions.yaml").write_text("write: deny\n")
    host = HostId.CLAUDE
    result = build_report(tmp_path, [host], adapters={host: default_adapters()[host]})
    permissions = result["hosts"]["claude"]["permissions"]
    assert permissions["requested"] == {"write": "deny"}
    assert permissions["representable"] == {"write": "deny"}
    assert permissions["effective"] == "UNVERIFIED"


def test_doctor_hosts_outputs_json_and_optional_file(tmp_path, monkeypatch, capsys):
    import json

    from seh.cli import main

    monkeypatch.setattr(
        "seh.compatibility.default_adapters",
        lambda: {HostId.CODEX: FakeAdapter(HostId.CODEX, False)},
    )
    output = tmp_path / "compatibility.json"
    code = main(
        [
            "doctor",
            "--root",
            str(tmp_path),
            "--hosts",
            "codex",
            "--format",
            "json",
            "--output",
            str(output),
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert report["compatibility"]["hosts"]["codex"]["verdict"] == "BLOCKED"
    assert json.loads(output.read_text()) == report["compatibility"]
    assert code == 1


def test_policy_blocked_host_is_partial_in_native_mode_and_blocked_in_managed_mode(
    tmp_path: Path,
) -> None:
    spec = tmp_path / ".harness/spec"
    (spec / "instructions").mkdir(parents=True)
    (spec / "instructions/core.md").write_text("instructions")
    adapter = FakeAdapter(HostId.ANTIGRAVITY, installed=True, policy_blocked=True)

    native = build_report(tmp_path, [HostId.ANTIGRAVITY], adapters={HostId.ANTIGRAVITY: adapter})[
        "hosts"
    ]["antigravity"]
    assert native["verdict"] == "PARTIAL"
    assert native["managed_execution"] == "POLICY_BLOCKED"
    assert "managed execution is policy blocked" in native["reasons"]

    (tmp_path / ".harness/config.toml").write_text(
        'profile = "full"\n[hosts]\nenabled = ["antigravity"]\n[runtime]\nmode = "managed"\n',
        encoding="utf-8",
    )
    managed = build_report(tmp_path, [HostId.ANTIGRAVITY], adapters={HostId.ANTIGRAVITY: adapter})[
        "hosts"
    ]["antigravity"]
    assert managed["verdict"] == "BLOCKED"
    assert managed["managed_execution"] == "POLICY_BLOCKED"
