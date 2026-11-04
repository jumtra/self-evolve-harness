"""`seh init --plan`: 検出・設定・正本 spec・v1 移行・sync を read-only で計画する。"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from seh.config import Config, defaults, dump_config, set_value
from seh.contracts import CanonicalSpec, HostId
from seh.init.detect import AppDetection, DetectionResult, ci_check_cmd, ci_fix_cmd, detect
from seh.init.templating import InitError, render_template_text, template_spec_dir
from seh.migration.inventory import detect_v1
from seh.migration.planner import MigrationPlan, plan_migration
from seh.spec_loader import load_spec
from seh.sync import SyncPlan, plan_sync

__all__ = [
    "GITIGNORE_BLOCK",
    "InitError",
    "InitOptions",
    "InitPlan",
    "load_spec_files",
    "plan_init",
]

SPEC_PREFIX = ".harness/spec"
CONFIG_PATH = ".harness/config.toml"
GITIGNORE_BLOCK = (
    "# seh:begin\n.harness/state/\n.harness/artifacts/\n.harness/backups/\n# seh:end\n"
)
_RENDERED_RULES_DIR = "rules/"
_CORE = "instructions/core.md"


@dataclass(frozen=True)
class InitOptions:
    profile: str = "balanced"
    hosts: tuple[HostId, ...] | None = None
    code_intelligence: str | None = None
    memory: str | None = None
    spec_source: Path | None = None


@dataclass(frozen=True)
class InitPlan:
    detection: DetectionResult
    config: Config
    config_toml: str
    spec_files: Mapping[str, bytes]
    migration: MigrationPlan | None
    sync: SyncPlan
    gitignore_block: str


def _primary_app(detection: DetectionResult) -> AppDetection | None:
    return next((a for a in detection.root_apps if a.path == "."), None) or next(
        iter(detection.root_apps), None
    )


def _variables(root: Path, detection: DetectionResult) -> dict[str, str]:
    app = _primary_app(detection)
    protected = sorted({p for a in detection.root_apps for p in a.protected_configs})
    return {
        "project_name": root.resolve().name,
        "ci_check_cmd": (app and ci_check_cmd(app)) or "未検出",
        "ci_fix_cmd": (app and ci_fix_cmd(app)) or "未検出",
        "protected_configs": "\n".join(f"- {p}" for p in protected) or "- （検出なし）",
    }


def _render_spec(source: Path, variables: Mapping[str, str]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(source).as_posix()
        data = path.read_bytes()
        if rel == _CORE or (rel.startswith(_RENDERED_RULES_DIR) and rel.endswith(".md")):
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as error:
                raise InitError(f"{rel}: UTF-8 として読めません") from error
            data = render_template_text(text, variables).encode("utf-8")
        files[f"{SPEC_PREFIX}/{rel}"] = data
    return files


def load_spec_files(spec_files: Mapping[str, bytes]) -> CanonicalSpec:
    """`.harness/spec/...` 形式の内容を一時ディレクトリで読込む（対象 repo には書かない）。"""
    with tempfile.TemporaryDirectory(prefix="seh-init-") as tmp:
        for rel, data in spec_files.items():
            target = Path(tmp) / rel.removeprefix(f"{SPEC_PREFIX}/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return load_spec(Path(tmp))


def _build_config(options: InitOptions) -> Config:
    cfg = defaults(options.profile)
    if options.hosts is not None:
        cfg = set_value(cfg, "hosts.enabled", ",".join(h.value for h in options.hosts))
    if options.code_intelligence is not None:
        cfg = set_value(cfg, "code_intelligence.provider", options.code_intelligence)
    if options.memory is not None:
        cfg = set_value(cfg, "memory.provider", options.memory)
    return cfg


def plan_init(root: Path, options: InitOptions) -> InitPlan:
    root = Path(root)
    if (root / CONFIG_PATH).exists():
        raise InitError("既に導入済みです。seh sync を使ってください")
    source = options.spec_source if options.spec_source is not None else template_spec_dir()
    if source is None:
        raise InitError("配布テンプレートが見つかりません")

    detection = detect(root)
    config = _build_config(options)
    spec_files = _render_spec(source, _variables(root, detection))
    sync = plan_sync(root, config.hosts.enabled, spec=load_spec_files(spec_files))
    migration = plan_migration(root) if detect_v1(root) else None
    return InitPlan(
        detection=detection,
        config=config,
        config_toml=dump_config(config),
        spec_files=spec_files,
        migration=migration,
        sync=sync,
        gitignore_block=GITIGNORE_BLOCK,
    )
