# ハンドラ契約: handler(args: argparse.Namespace) -> int（戻り値が終了コード）。
import argparse
import asyncio
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import seh.commands.eval as eval_cmd
from seh.artifacts import ArtifactStore
from seh.authoring.classify import FileChange, changes_from_git, classify_change, classify_changes
from seh.authoring.eval import (
    OverlayRunner,
    TriggerResult,
    TriggerRun,
    render_changes,
    render_generated_files,
    run_trigger_eval,
    trigger_run_from_json,
    trigger_run_to_json,
)
from seh.authoring.gate import (
    SPEC_PREFIX,
    GateDecision,
    GateStatus,
    evaluate_gate,
    file_digests,
    is_initial_generation,
)
from seh.authoring.inventory import Proposal, collect_inventory, decide, exploration_record
from seh.authoring.lint import has_errors, lint_generated, lint_spec
from seh.authoring.promote import (
    AUTHORING_DIR,
    PromotionRefused,
    load_records,
    promote,
    record_path,
    rollback_promotion,
    save_record,
)
from seh.authoring.spec import load_record
from seh.config import Config, ConfigError, load_config
from seh.contracts import (
    AuthoringRecord,
    AuthoringRisk,
    AuthoringState,
    CliAgentRunner,
    Diagnostic,
    DiagnosticLevel,
    HostId,
    RenderContext,
    transition_authoring,
)
from seh.contracts.schema import SchemaError
from seh.evals.fixtures import DEFAULT_SUITE_ROOT, FixtureError, load_suite
from seh.evals.report import compare, from_json, render_markdown, to_json
from seh.evals.runner import EvalRun, run_eval
from seh.evals.variants import VARIANTS
from seh.providers.hosts.common import MANAGED_BEGIN, MANAGED_BLOCK_REASON, MANAGED_END
from seh.runtime.runners.base import BaseCliRunner
from seh.spec_loader import SpecError, load_spec
from seh.sync import default_adapters

NOT_ENFORCED_NOTICE = "強制力: NOT_ENFORCED（GitHub 必須チェック未設定。CI で可視化のみ）"
CASES_PATH = Path("tests/fixtures/prompt_skill/cases.json")
CANDIDATES_DIR = AUTHORING_DIR / "candidates"
EVALS_DIR = AUTHORING_DIR / "evals"
ARTIFACTS_DIR = Path(".harness") / "artifacts" / "authoring"
SPEC_DIR = Path(".harness") / "spec"
_SKILL_PATH = re.compile(r"skills/([^/]+)/")
_LOAD_ERRORS = (OSError, ValueError, KeyError, SchemaError)


def _out(text: str = "") -> None:
    print(text)


def _err(text: str) -> None:
    print(text, file=sys.stderr)


def _config(root: Path) -> Config | None:
    """`.harness/config.toml` が無ければ None（未導入リポジトリ）。"""
    try:
        return load_config(root / ".harness" / "config.toml")
    except FileNotFoundError:
        return None
    except ConfigError as e:
        _err(f"設定エラー: {e}")
        raise SystemExit(1) from e


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _relative(root: Path, path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return path
    return posixpath.normpath(path.replace("\\", "/"))


# --- 記録・評価結果の保存 --------------------------------------------------------


def _write_json(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_eval_run(root: Path, run_id: str | None) -> EvalRun | None:
    if not run_id:
        return None
    try:
        return from_json((root / EVALS_DIR / f"{run_id}.json").read_text(encoding="utf-8"))
    except _LOAD_ERRORS:
        return None


def _load_triggers(root: Path, record_id: str) -> dict[str, TriggerRun]:
    latest: dict[str, TriggerRun] = {}
    directory = root / EVALS_DIR
    for path in sorted(directory.glob("trigger-*.json")) if directory.is_dir() else []:
        try:
            text = path.read_text(encoding="utf-8")
            if json.loads(text).get("record_id") != record_id:
                continue
            run = trigger_run_from_json(text)
        except _LOAD_ERRORS:
            continue
        if run.host not in latest or latest[run.host].created_at <= run.created_at:
            latest[run.host] = run
    return latest


def _required_hosts(cfg: Config) -> list[str]:
    hosts = cfg.authoring.required_hosts
    if hosts == "active":
        return [h.value for h in cfg.hosts.enabled]
    return [h.value for h in hosts]


# --- gate ------------------------------------------------------------------------


def _candidate_dir(root: Path, record: AuthoringRecord) -> Path:
    return root / CANDIDATES_DIR / record.id


def _merge_spec(spec_dir: Path, candidate: Path, merged: Path) -> None:
    shutil.copytree(spec_dir, merged)
    if candidate.is_dir():
        shutil.copytree(candidate, merged, dirs_exist_ok=True)


def _overlay_lint(root: Path, candidate: Path) -> list[Diagnostic]:
    """現正本に候補を重ねた正本と、そこから描画した生成物を lint する。正本が無ければ対象なし。"""
    spec_dir = root / SPEC_DIR
    if not spec_dir.is_dir():
        return []
    with tempfile.TemporaryDirectory(prefix="seh-author-") as tmp:
        merged = Path(tmp) / "spec"
        _merge_spec(spec_dir, candidate, merged)
        return _generated_lint(root, merged)


def _candidate_digests(candidate: EvalRun | None, current: Mapping[str, str]) -> dict[str, str]:
    if candidate is None:
        return dict(current)  # 比較対象の評価が無い。欠落は BLOCKED 側で表現する
    return {
        k.removeprefix("file:"): v for k, v in candidate.components.items() if k.startswith("file:")
    }


def _gate(root: Path, cfg: Config, record: AuthoringRecord, approval: str | None) -> GateDecision:
    candidate_dir = _candidate_dir(root, record)
    current = file_digests(candidate_dir)
    candidate = _load_eval_run(root, record.candidate_run_id)
    errors = [d for d in _overlay_lint(root, candidate_dir) if d.level == DiagnosticLevel.ERROR]
    return evaluate_gate(
        record,
        root=root,
        risk=record.risk,
        lint_errors=errors,
        baseline=_load_eval_run(root, record.baseline_run_id),
        candidate=candidate,
        triggers=_load_triggers(root, record.id),
        required_hosts=_required_hosts(cfg),
        approval_ref=approval or record.approval_ref,
        candidate_digests=_candidate_digests(candidate, current),
        current_digests=current,
    )


def _print_decision(decision: GateDecision) -> None:
    _out(f"gate: {decision.status.value}")
    for reason in decision.reasons:
        _out(f"  - {reason}")


# --- inspect / plan --------------------------------------------------------------


def _inspect(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if _config(root) is None:
        _out("NOT_CONFIGURED: .harness/config.toml がありません")
        return 0
    rel = _relative(root, args.path)
    target = root / rel
    after = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
    result = classify_change(FileChange(rel, None, after))
    if result is None:
        _err(f"TARGET_NOT_AUTHORING_PATH: {rel}")
        return 1
    _out(f"path: {result.path}")
    _out(f"kind: {result.kind.value}")
    _out(f"risk: {result.risk.value}")
    _out(f"reasons: {', '.join(result.reasons)}")
    stem = posixpath.basename(posixpath.dirname(rel)) or posixpath.basename(rel).split(".")[0]
    related = [i for i in collect_inventory(root) if i.source == rel or i.name == stem]
    _out("related:")
    for item in related:
        _out(f"  - {item.kind}:{item.name} ({item.source})")
    return 0


def _skill_id(record: AuthoringRecord) -> str:
    for path in record.target_paths:
        match = _SKILL_PATH.search(path)
        if match:
            return match.group(1)
    value = record.spec.get("skill_id")
    return value if isinstance(value, str) else record.id


def _plan(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if _config(root) is None:
        _out("NOT_CONFIGURED: .harness/config.toml がありません")
        return 0
    rel = _relative(root, args.target)
    target = root / rel
    after = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
    classified = classify_change(FileChange(rel, None, after))
    if classified is None:
        _err(f"TARGET_NOT_AUTHORING_PATH: {rel}")
        return 1
    record_id = args.id or f"AUTH-{datetime.now(UTC):%Y%m%d}-{uuid.uuid4().hex[:6]}"
    try:
        record_path(root, record_id)
    except ValueError as e:
        _err(str(e))
        return 1
    skill = _SKILL_PATH.search(rel)
    proposal = Proposal(
        id=skill.group(1) if skill else record_id,
        description=args.goal,
        trigger_examples=(),
        repeated=True,
        deterministic=False,
        always_needed=False,
        needs_isolation=False,
        branching_or_parallel=False,
    )
    inventory = collect_inventory(root)
    decision = decide(proposal, inventory)
    exploration = exploration_record(decision, root)
    refs = cast("list[str]", exploration["evidence_refs"])
    if target.is_file() and f"file:{rel}" not in refs:
        refs.append(f"file:{rel}")
    record = AuthoringRecord(
        id=record_id,
        target_kind=classified.kind.value,
        target_paths=(rel,),
        risk=classified.risk,
        exploration=exploration,
        spec={
            "goal": args.goal,
            "inputs": args.inputs,
            "boundaries": args.boundaries,
            "output": args.output,
            "feedback": args.feedback,
        },
    )
    for state in (AuthoringState.EXPLORED, AuthoringState.PLANNED):
        record = transition_authoring(record, state)
    if record.risk is AuthoringRisk.HIGH_RISK:
        record = transition_authoring(record, AuthoringState.AWAITING_APPROVAL)
    path = save_record(root, record)
    _out(f"record: {path.relative_to(root).as_posix()}")
    _out(f"risk: {record.risk.value}")
    _out(f"state: {record.state.value}")
    _out(f"placement: {decision.placement.value}")
    return 0


# --- lint ------------------------------------------------------------------------


def _resolve_base(root: Path, base: str | None) -> str:
    if base is not None:
        return base
    for ref in ("origin/main", "HEAD~1"):
        probe = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            capture_output=True,
        )
        if probe.returncode == 0:
            return ref
    raise ValueError("BASE_REF_UNRESOLVED: origin/main も HEAD~1 も解決できません。--base を指定")


def _generated_lint(root: Path, spec_dir: Path) -> list[Diagnostic]:
    try:
        spec = load_spec(spec_dir)
    except SpecError as e:
        return [Diagnostic(DiagnosticLevel.ERROR, "SPEC_INVALID", str(e))]
    adapters = default_adapters()
    hosts = tuple(HostId)
    context = RenderContext(root=root, enabled_hosts=hosts, project_name=root.resolve().name)
    plans = {host: adapters[host].render(spec, context) for host in hosts}
    return [*lint_spec(spec), *lint_generated(plans, adapters)]


def _reviewed_paths(root: Path, cfg: Config, diags: list[Diagnostic]) -> set[str]:
    reviewed: set[str] = set()
    try:
        records = load_records(root)
    except _LOAD_ERRORS as e:
        diags.append(Diagnostic(DiagnosticLevel.ERROR, "AUTHORING_RECORD_INVALID", str(e)))
        return reviewed
    for record in records:
        done = record.state is AuthoringState.PROMOTED or (
            _gate(root, cfg, record, None).status is GateStatus.PASS
        )
        if done:
            reviewed.update(posixpath.normpath(p) for p in record.target_paths)
    return reviewed


def _expected_generated(root: Path) -> dict[str, tuple[bytes, bool]]:
    """現行正本から全ホスト分を描画した {パス: (内容, managed-block か)}。正本が読めなければ空。"""
    spec_dir = root / SPEC_DIR
    if not spec_dir.is_dir():
        return {}
    expected: dict[str, tuple[bytes, bool]] = {}
    try:
        for host in HostId:
            for change in render_changes(spec_dir, root, host):
                expected[change.path] = (
                    cast("bytes", change.content),
                    change.reason == MANAGED_BLOCK_REASON,
                )
    except (SpecError, OSError):
        return {}
    return expected


def _managed_block(text: str) -> str | None:
    begin = text.find(MANAGED_BEGIN)
    end = text.find(MANAGED_END, begin) if begin >= 0 else -1
    return text[begin : end + len(MANAGED_END)] if end >= 0 else None


def _matches_generated(root: Path, path: str, content: bytes, is_block: bool) -> bool | None:
    """生成物が正本の描画と一致するか。None は比較対象外（管理ブロックの無い利用者ファイル）。"""
    target = root / path
    if not target.is_file():
        return False
    actual = target.read_bytes()
    if not is_block:
        return actual == content
    block = _managed_block(actual.decode("utf-8", errors="replace"))
    if block is None:
        return None
    return block.rstrip("\n") == content.decode("utf-8").rstrip("\n")


def _changed_findings(root: Path, cfg: Config, base: str) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    try:
        changes = changes_from_git(root, _resolve_base(root, base), None)
    except (ValueError, subprocess.CalledProcessError) as e:
        return [Diagnostic(DiagnosticLevel.ERROR, "BASE_REF_UNRESOLVED", str(e))]
    reviewed = _reviewed_paths(root, cfg, diags)
    expected = _expected_generated(root)
    level = DiagnosticLevel.WARN if cfg.authoring.policy == "advisory" else DiagnosticLevel.ERROR
    for item in classify_changes(changes):
        path = posixpath.normpath(item.path)
        if not path.startswith(SPEC_PREFIX) and path in expected:
            content, is_block = expected[path]
            if _matches_generated(root, path, content, is_block) is False:
                diags.append(
                    Diagnostic(
                        DiagnosticLevel.ERROR,
                        f"GENERATED_FILE_DRIFT:{item.path}",
                        "生成物を直接編集しています。"
                        ".harness/spec を変更して seh sync してください",
                        item.path,
                    )
                )
            continue
        if item.risk is AuthoringRisk.TEXT_ONLY:
            continue
        if path in reviewed or is_initial_generation(root, path):
            continue
        diags.append(
            Diagnostic(
                level,
                f"UNREVIEWED_AUTHORING_CHANGE:{item.path}",
                f"{item.risk.value} の変更が評価済みの Authoring Record に紐づいていない",
                item.path,
            )
        )
    return diags


def _enforcement_notice(cfg: Config) -> str | None:
    if cfg.authoring.require_ci_for_promote and os.environ.get("CI") == "true":
        return None
    return NOT_ENFORCED_NOTICE


def _lint(args: argparse.Namespace) -> int:
    root = Path(args.root)
    cfg = _config(root)
    if cfg is None:
        _out("NOT_CONFIGURED: .harness/config.toml がありません")
        return 0
    diags: list[Diagnostic] = []
    spec_dir = root / SPEC_DIR
    if spec_dir.is_dir():
        diags += _generated_lint(root, spec_dir)
    if args.changed:
        diags += _changed_findings(root, cfg, args.base)
    notice = _enforcement_notice(cfg)
    if args.format == "json":
        payload = {
            "diagnostics": [{**asdict(d), "level": d.level.value} for d in diags],
            "enforcement": notice,
        }
        _out(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for d in diags:
            where = f" ({d.path})" if d.path else ""
            _out(f"{d.level.value} {d.code}: {d.message}{where}")
        if not diags:
            _out("OK: 指摘なし")
        if notice:
            _out(notice)
    return 1 if has_errors(diags) else 0


# --- eval / compare --------------------------------------------------------------


def _usable_runner(host: str, store: ArtifactStore) -> tuple[CliAgentRunner | None, str | None]:
    if host == HostId.ANTIGRAVITY.value:
        return None, "POLICY_BLOCKED: antigravity は eval の自動実行対象外"
    try:
        runner = eval_cmd.REGISTRY.get(host)
    except KeyError:
        return None, f"RUNNER_NOT_REGISTERED: {host}"
    if isinstance(runner, BaseCliRunner):
        # events.jsonl を読めるよう、保存先をこのコマンドの ArtifactStore にした Runner を作り直す
        try:
            return type(runner)(artifacts=store), None
        except TypeError:
            return None, f"RUNNER_NOT_REBUILDABLE: {host}"
    return runner, None


def _load_cases(root: Path) -> list[Mapping[str, object]]:
    try:
        data = json.loads((root / CASES_PATH).read_text(encoding="utf-8"))
    except _LOAD_ERRORS:
        return []
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


def _save_trigger(root: Path, record: AuthoringRecord, run: TriggerRun) -> None:
    payload = {**json.loads(trigger_run_to_json(run)), "record_id": record.id}
    _write_json(root / EVALS_DIR / f"{run.run_id}.json", json.dumps(payload, indent=2))


async def _trigger_for_host(
    root: Path,
    record: AuthoringRecord,
    host: str,
    runner: CliAgentRunner,
    store: ArtifactStore,
) -> TriggerRun:
    cases = _load_cases(root)
    run_id = f"trigger-{record.id}-{host}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:4]}"
    if record.target_kind == "skill":
        skills = [_skill_id(record)]
    else:
        skills = sorted({str(c["target_skill"]) for c in cases if "target_skill" in c})
    results: list[TriggerResult] = []
    with tempfile.TemporaryDirectory(prefix="seh-trigger-") as workdir:
        for skill in skills:
            part = await run_trigger_eval(
                skill, cases, runner, workdir=Path(workdir), artifacts=store
            )
            results += part.results
    return TriggerRun(run_id, host, _skill_id(record), tuple(results), _now())


def _blocked_trigger(record: AuthoringRecord, host: str, reason: str) -> TriggerRun:
    run_id = f"trigger-{record.id}-{host}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:4]}"
    placeholder = TriggerResult(reason, "BLOCKED", False, None)
    return TriggerRun(run_id, host, _skill_id(record), (placeholder,), _now())


async def _outcome(
    root: Path, cfg: Config, record: AuthoringRecord, runner: CliAgentRunner
) -> tuple[EvalRun, EvalRun]:
    cases = load_suite(root / DEFAULT_SUITE_ROOT)
    if not cases:
        raise FixtureError("評価 suite が空です")
    candidate_dir = _candidate_dir(root, record)
    runs: list[EvalRun] = []
    with tempfile.TemporaryDirectory(prefix="seh-author-eval-") as workroot:
        # 実 CLI は生成物を読むため、baseline / candidate とも同条件で描画した生成物を重ねる
        merged = Path(workroot) / "candidate-spec"
        try:
            host = HostId(runner.host)
            _merge_spec(root / SPEC_DIR, candidate_dir, merged)
            variants = (
                render_generated_files(root / SPEC_DIR, root, host),
                render_generated_files(merged, root, host),
            )
        except (ValueError, OSError, SpecError) as e:
            raise FixtureError(f"生成物を描画できません: {e}") from e
        for files in variants:
            overlaid = OverlayRunner(runner, files)
            runs.append(
                await run_eval(
                    cases,
                    VARIANTS["V0"],
                    overlaid,
                    trials=cfg.evaluation.trials,
                    workroot=Path(workroot),
                )
            )
    baseline, candidate = runs
    digests = {f"file:{k}": v for k, v in file_digests(candidate_dir).items()}
    candidate = replace(candidate, components={**candidate.components, **digests})
    return baseline, candidate


def _eval_hosts(raw: str, cfg: Config) -> list[str]:
    if raw == "active":
        return [h.value for h in cfg.hosts.enabled]
    return [h.strip() for h in raw.split(",") if h.strip()]


async def _run_eval_command(
    root: Path, cfg: Config, record: AuthoringRecord, hosts: list[str]
) -> AuthoringRecord:
    store = ArtifactStore(root / ARTIFACTS_DIR)
    outcome_runner: CliAgentRunner | None = None
    for host in hosts:
        runner, blocked = _usable_runner(host, store)
        if runner is None:
            run = _blocked_trigger(record, host, blocked or "BLOCKED")
            _out(f"BLOCKED_NO_EVAL {host}: {blocked}")
        else:
            outcome_runner = outcome_runner or runner
            run = await _trigger_for_host(root, record, host, runner, store)
            undetermined = [r.case_id for r in run.results if r.observed is None]
            _out(f"trigger {host}: {len(run.results)} cases, undetermined={len(undetermined)}")
        _save_trigger(root, record, run)
    if outcome_runner is None:
        _out("BLOCKED_NO_EVAL outcome: 利用可能な Runner がありません")
        return record
    try:
        baseline, candidate = await _outcome(root, cfg, record, outcome_runner)
    except FixtureError as e:
        _out(f"BLOCKED_NO_EVAL outcome: {e}")
        return record
    for run in (baseline, candidate):
        _write_json(root / EVALS_DIR / f"{run.run_id}.json", to_json(run))
    _out(f"outcome baseline: {baseline.run_id}")
    _out(f"outcome candidate: {candidate.run_id}")
    return replace(record, baseline_run_id=baseline.run_id, candidate_run_id=candidate.run_id)


def _eval(args: argparse.Namespace) -> int:
    root = Path(args.root)
    cfg = _config(root)
    if cfg is None:
        _out("NOT_CONFIGURED: .harness/config.toml がありません")
        return 0
    try:
        record = load_record(Path(args.record))
    except _LOAD_ERRORS as e:
        _err(f"record を読めません: {e}")
        return 1
    updated = asyncio.run(_run_eval_command(root, cfg, record, _eval_hosts(args.hosts, cfg)))
    save_record(root, updated)
    return 0


def _read_run(root: Path, ref: str) -> EvalRun:
    direct = Path(ref)
    path = direct if direct.is_file() else root / EVALS_DIR / f"{ref}.json"
    return from_json(path.read_text(encoding="utf-8"))


def _compare(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if _config(root) is None:
        _out("NOT_CONFIGURED: .harness/config.toml がありません")
        return 0
    try:
        baseline = _read_run(root, args.baseline)
        candidate = _read_run(root, args.candidate)
    except _LOAD_ERRORS as e:
        _err(f"評価結果を読めません: {e}")
        return 1
    result = compare(baseline, candidate)
    _out(render_markdown([baseline, candidate], result))
    return 0 if result.promotable else 1


# --- promote / rollback ----------------------------------------------------------


@dataclass(frozen=True)
class _Approval:
    ref: str | None


def _ask_approval(record: AuthoringRecord) -> _Approval:
    """D19: 承認は対話の y/N のみ。フラグや環境変数では代替できない。"""
    if not sys.stdin.isatty():
        return _Approval(None)
    _out(f"high_risk の変更です: {', '.join(record.target_paths)}")
    answer = input("昇格を承認しますか? [y/N] ")
    return _Approval(f"human-tty:{_now()}" if answer.strip().lower() == "y" else None)


def _promote(args: argparse.Namespace) -> int:
    root = Path(args.root)
    cfg = _config(root)
    if cfg is None:
        _out("NOT_CONFIGURED: .harness/config.toml がありません")
        return 0
    try:
        record = load_record(Path(args.record))
    except _LOAD_ERRORS as e:
        _err(f"record を読めません: {e}")
        return 1
    approval = record.approval_ref
    if record.risk is AuthoringRisk.HIGH_RISK and not approval:
        # 承認が得られたと仮定しても通らない候補には、人間に確認を求めない
        preview = _gate(root, cfg, record, "pending-human-approval")
        if preview.status is not GateStatus.PASS:
            _print_decision(preview)
            return 1
        approval = _ask_approval(record).ref
        if approval is None:
            _print_decision(GateDecision(GateStatus.NEEDS_HUMAN, ("APPROVAL_REQUIRED",)))
            _err("承認が得られませんでした（対話端末での y のみ有効）")
            return 1
        record = replace(record, approval_ref=approval)
    decision = _gate(root, cfg, record, approval)
    _print_decision(decision)
    if decision.status is not GateStatus.PASS:
        return 1
    try:
        promotion_id = promote(root, record, decision, candidate_dir=_candidate_dir(root, record))
    except PromotionRefused as e:
        _err(f"PromotionRefused: {e}")
        return 1
    _out(f"promotion: {promotion_id}")
    _out("生成物への反映は `seh sync` で行ってください")
    return 0


def _rollback(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if _config(root) is None:
        _out("NOT_CONFIGURED: .harness/config.toml がありません")
        return 0
    try:
        restored = rollback_promotion(root, args.promotion)
    except (KeyError, OSError, ValueError) as e:
        _err(f"rollback できません: {e!r}")
        return 1
    for path in restored:
        _out(f"restored: {path}")
    return 0


# --- 登録 ------------------------------------------------------------------------


def register(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    parser = subparsers.add_parser("author", help="Skill / Prompt の作成・評価・昇格ガード")
    sub = parser.add_subparsers(dest="author_command", required=True, metavar="<action>")

    def add(name: str, help_text: str, handler: object) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--root", default=".", help="対象リポジトリのルート")
        p.set_defaults(handler=handler)
        return p

    inspect = add("inspect", "変更対象の分類と関連資産を表示する", _inspect)
    inspect.add_argument("--path", required=True)

    plan = add("plan", "Authoring Record を作成する", _plan)
    plan.add_argument("--target", required=True)
    for key in ("goal", "inputs", "boundaries", "output", "feedback"):
        plan.add_argument(f"--{key}", required=True)
    plan.add_argument("--id")

    lint = add("lint", "正本と生成物を lint し、未評価の変更を検出する", _lint)
    lint.add_argument("--changed", action="store_true")
    lint.add_argument("--base", help="比較基準（既定 origin/main、無ければ HEAD~1）")
    lint.add_argument("--format", choices=("text", "json"), default="text")

    ev = add("eval", "trigger / outcome 評価を実行して保存する", _eval)
    ev.add_argument("--record", required=True)
    ev.add_argument("--hosts", default="active", help="active または host のカンマ区切り")
    ev.add_argument("--fresh", action="store_true", help="常に新規セッション（既定動作）")

    cmp_ = add("compare", "2 つの評価結果を比較する", _compare)
    cmp_.add_argument("--baseline", required=True)
    cmp_.add_argument("--candidate", required=True)

    prom = add("promote", "gate を通過した候補を正本へ昇格する", _promote)
    prom.add_argument("--record", required=True)

    back = add("rollback", "昇格を巻き戻す", _rollback)
    back.add_argument("--promotion", required=True)
