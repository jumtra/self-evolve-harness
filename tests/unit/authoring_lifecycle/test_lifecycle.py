import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from seh.authoring.lifecycle import advance, native_stop, write_is_authorized, write_requires_plan
from seh.contracts import AuthoringRecord, AuthoringRisk, AuthoringState


def record() -> AuthoringRecord:
    return AuthoringRecord(
        "a", "skill", (".claude/skills/a/SKILL.md",), AuthoringRisk.HIGH_RISK, {}, {}
    )


def test_managed_write_requires_approval_and_baseline() -> None:
    r = record()
    for state in (
        AuthoringState.EXPLORED,
        AuthoringState.PLANNED,
        AuthoringState.AWAITING_APPROVAL,
    ):
        r = advance(r, state)
    with pytest.raises(ValueError):
        advance(r, AuthoringState.WRITTEN)
    with pytest.raises(ValueError):
        advance(r, AuthoringState.APPROVED)
    r = advance(replace(r, approval_ref="human"), AuthoringState.APPROVED)
    with pytest.raises(ValueError):
        advance(r, AuthoringState.BASELINED)
    r = advance(replace(r, baseline_run_id="base"), AuthoringState.BASELINED)
    assert advance(r, AuthoringState.WRITTEN).state == AuthoringState.WRITTEN


def test_native_write_requires_real_baseline_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import seh.authoring.lifecycle as lifecycle

    baselined = replace(
        record(), approval_ref="human", baseline_run_id="missing", state=AuthoringState.BASELINED
    )
    monkeypatch.setattr(lifecycle, "load_records", lambda root: [baselined])
    assert not write_is_authorized(tmp_path, baselined.target_paths)


def test_native_write_accepts_matching_nonempty_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import seh.authoring.lifecycle as lifecycle
    from seh.evals.report import to_json
    from seh.evals.runner import EvalRun, TrialResult

    trial = TrialResult("case", "regression", 1, "FAIL", 1, 0, 0, 0.1, None, None, None, None, ())
    baseline = EvalRun(
        "base", "", "", {"target:.claude/skills/a/SKILL.md": "MISSING"}, {}, (trial,)
    )
    path = tmp_path / ".harness/authoring/evals/base.json"
    path.parent.mkdir(parents=True)
    path.write_text(to_json(baseline))
    baselined = replace(
        record(), approval_ref="human", baseline_run_id="base", state=AuthoringState.BASELINED
    )
    monkeypatch.setattr(lifecycle, "load_records", lambda root: [baselined])
    assert write_is_authorized(tmp_path, baselined.target_paths)
    target = tmp_path / baselined.target_paths[0]
    target.parent.mkdir(parents=True)
    target.write_text("changed after baseline")
    assert not write_is_authorized(tmp_path, baselined.target_paths)
    target.unlink()
    path.write_text(to_json(replace(baseline, trials=())))
    assert not write_is_authorized(tmp_path, baselined.target_paths)


def test_write_detection_limits_itself_to_authoring_files(tmp_path: Path) -> None:
    assert write_requires_plan(tmp_path, (".claude/skills/a/SKILL.md",))
    assert not write_requires_plan(tmp_path, ("src/a.py",))


def test_native_stop_records_unreviewed_change_and_limits_retries(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@x",
            "commit",
            "--allow-empty",
            "-qm",
            "base",
        ],
        check=True,
    )
    target = tmp_path / ".claude/skills/a/SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\nname: a\ndescription: does stuff\n---\nnew behavior\n")
    first = native_stop(tmp_path, "session")
    second = native_stop(tmp_path, "session")
    third = native_stop(tmp_path, "session")
    assert first.needs_eval and first.block
    assert second.needs_eval and second.block
    assert third.needs_eval and not third.block


def test_native_pretool_blocks_unplanned_write_and_stop_reports_need(tmp_path: Path) -> None:
    import json

    from seh.contracts import HostId
    from seh.events import run_hook
    from seh.policy import Policy

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@x",
            "commit",
            "--allow-empty",
            "-qm",
            "base",
        ],
        check=True,
    )
    (tmp_path / ".harness").mkdir()
    target = tmp_path / ".claude/skills/a/SKILL.md"
    target.parent.mkdir(parents=True)
    payload = json.dumps(
        {"cwd": str(tmp_path), "tool_name": "Write", "tool_input": {"file_path": str(target)}}
    ).encode()
    code, _, error = run_hook(
        "PreToolUse", HostId.CLAUDE, payload, policy=Policy(), trace=None, unattended=False
    )
    assert code == 2 and "author" in error.lower()
    target.write_text("---\nname: a\ndescription: does stuff\n---\nbody\n")
    payload = json.dumps({"cwd": str(tmp_path), "session_id": "s"}).encode()
    code, output, _ = run_hook(
        "Stop", HostId.CLAUDE, payload, policy=Policy(), trace=None, unattended=False
    )
    assert code == 0 and json.loads(output)["decision"] == "block"


def test_native_stop_only_accepts_evidence_matching_changed_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    import seh.authoring.lifecycle as lifecycle
    import seh.commands.author as author
    from seh.authoring.gate import GateDecision, GateStatus
    from seh.evals.runner import EvalRun

    path = ".harness/spec/skills/a.yaml"
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    target.write_text("validated")
    rec = replace(record(), target_paths=(path,), candidate_run_id="candidate")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    run = EvalRun("candidate", "", "", {"file:skills/a.yaml": digest}, {}, ())
    monkeypatch.setattr(lifecycle, "load_records", lambda root: [rec])
    import seh.config as config

    monkeypatch.setattr(config, "load_config", lambda path: object())
    monkeypatch.setattr(author, "_gate", lambda *args: GateDecision(GateStatus.PASS, ()))
    monkeypatch.setattr(author, "_load_eval_run", lambda *args: run)
    assert lifecycle._reviewed_paths(tmp_path) == {path}
    target.write_text("changed after evaluation")
    assert lifecycle._reviewed_paths(tmp_path) == set()


def test_broad_allowlist_is_classified_as_authoring(tmp_path: Path) -> None:
    assert write_requires_plan(tmp_path, ("**",))
    assert write_requires_plan(tmp_path, (".claude/**",))
    assert not write_requires_plan(tmp_path, ("src/**/*.py",))


@pytest.mark.parametrize(
    "pattern",
    [
        ".claude/*.json",
        ".claude/skills/*/custom.md",
        ".agents/agents/*.yaml",
        "src/**/AGENTS.md",
        "src/../.claude/*.json",
    ],
)
def test_authoring_globs_cannot_bypass_prewrite_gate(tmp_path: Path, pattern: str) -> None:
    assert write_requires_plan(tmp_path, (pattern,))
