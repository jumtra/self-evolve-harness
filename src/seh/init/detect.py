"""対象リポジトリの read-only スタック検出（FR-001）。

ファイル読み取りのみ。サブプロセスは起動しない。コマンドは実在を確認できたものだけ返す。
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from seh.policy import TOOL_CONFIG_GLOBS

IGNORED_DIRS = frozenset({".git", "node_modules", ".venv", "target", "dist", "build", "vendor"})
_HARNESS_ENTRIES = (
    ".claude",
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    ".agents",
    ".codex",
    ".opencode",
    ".harness",
)
_CI_FILES = (
    ".gitlab-ci.yml",
    ".circleci/config.yml",
    "Jenkinsfile",
    "azure-pipelines.yml",
    ".travis.yml",
    "bitbucket-pipelines.yml",
)
_CONVENTIONAL_DIRS = ("apps", "packages", "services")
_NO_TEST = "no test specified"
_MAKEFILES = ("Makefile", "makefile", "GNUmakefile")
_JUSTFILES = ("justfile", ".justfile", "Justfile")

# Commands のフィールド -> 候補タスク名（先頭ほど優先）
_TARGETS: dict[str, tuple[str, ...]] = {
    "test": ("test",),
    "lint": ("lint",),
    "typecheck": ("typecheck", "type-check", "check-types", "tsc"),
    "format_check": (
        "format:check",
        "format-check",
        "fmt-check",
        "fmt:check",
        "format_check",
        "check-format",
    ),
    "format_fix": ("format", "fmt", "format:fix", "format-fix", "fix", "lint:fix"),
    "build": ("build",),
}


@dataclass(frozen=True)
class Commands:
    test: str | None = None
    lint: str | None = None
    format_check: str | None = None
    format_fix: str | None = None
    typecheck: str | None = None
    build: str | None = None


@dataclass(frozen=True)
class AppDetection:
    path: str
    languages: tuple[str, ...]
    package_manager: str | None
    task_runner: str | None
    commands: Commands
    protected_configs: tuple[str, ...]


@dataclass(frozen=True)
class DetectionResult:
    root_apps: tuple[AppDetection, ...]
    ci_files: tuple[str, ...]
    existing_harness: tuple[str, ...]
    existing_symlinks: tuple[str, ...]
    notes: tuple[str, ...]


def ci_check_cmd(app: AppDetection) -> str | None:
    c = app.commands
    parts = [c.lint, c.format_check, c.typecheck, c.test, c.build]
    present = [p for p in parts if p]
    return " && ".join(present) if present else None


def ci_fix_cmd(app: AppDetection) -> str | None:
    return app.commands.format_fix


class _Scan:
    """読み取り失敗を notes に溜めて続行するためのファイルアクセス層。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.notes: list[str] = []

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix() or "."
        except ValueError:
            return str(path)

    def text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            self.notes.append(f"読めないファイル: {self.rel(path)} ({type(e).__name__})")
            return None

    def toml(self, path: Path) -> dict[str, Any]:
        text = self.text(path)
        if text is None:
            return {}
        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            self.notes.append(f"解析できないファイル: {self.rel(path)} (TOML)")
            return {}

    def json(self, path: Path) -> dict[str, Any]:
        text = self.text(path)
        if text is None:
            return {}
        try:
            return _as_dict(json.loads(text))
        except json.JSONDecodeError:
            self.notes.append(f"解析できないファイル: {self.rel(path)} (JSON)")
            return {}

    def yaml(self, path: Path) -> Any:
        text = self.text(path)
        if text is None:
            return None
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError:
            self.notes.append(f"解析できないファイル: {self.rel(path)} (YAML)")
            return None

    def names(self, directory: Path) -> set[str]:
        try:
            return {e.name for e in os.scandir(directory)}
        except OSError as e:
            self.notes.append(f"読めないディレクトリ: {self.rel(directory)} ({type(e).__name__})")
            return set()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dep_name(spec: str) -> str | None:
    m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", spec.strip())
    return m.group(0).lower().replace("_", "-") if m else None


# --- 言語検出 -------------------------------------------------------------------------------


def _languages(scan: _Scan, d: Path, names: set[str]) -> tuple[str, ...]:
    langs: list[str] = []
    if names & {"pyproject.toml", "setup.cfg", "setup.py"} or any(
        fnmatch.fnmatch(n, "requirements*.txt") for n in names
    ):
        langs.append("python")
    if "package.json" in names:
        langs.append("node")
        if any(fnmatch.fnmatch(n, "tsconfig*.json") for n in names):
            langs.append("typescript")
    if "go.mod" in names:
        langs.append("go")
    if "Cargo.toml" in names:
        langs.append("rust")
    if names & {"pom.xml", "build.gradle", "build.gradle.kts"}:
        langs.append("java")
    if any(n.endswith((".csproj", ".sln")) for n in names):
        langs.append("csharp")
    if names & {"CMakeLists.txt", "meson.build"}:
        langs.append("c-cpp")
    if any(n.endswith(".tf") for n in names) or (
        "terraform" in names and any(n.endswith(".tf") for n in scan.names(d / "terraform"))
    ):
        langs.append("terraform")
    return tuple(langs)


# --- Python ---------------------------------------------------------------------------------


def _python_deps(scan: _Scan, d: Path, names: set[str], data: dict[str, Any]) -> set[str]:
    specs: list[str] = []
    project = _as_dict(data.get("project"))
    specs += [s for s in _as_list(project.get("dependencies")) if isinstance(s, str)]
    for group in _as_dict(project.get("optional-dependencies")).values():
        specs += [s for s in _as_list(group) if isinstance(s, str)]
    for group in _as_dict(data.get("dependency-groups")).values():
        specs += [s for s in _as_list(group) if isinstance(s, str)]
    tool = _as_dict(data.get("tool"))
    specs += [
        s for s in _as_list(_as_dict(tool.get("uv")).get("dev-dependencies")) if isinstance(s, str)
    ]
    poetry = _as_dict(tool.get("poetry"))
    specs += list(_as_dict(poetry.get("dependencies")))
    specs += list(_as_dict(poetry.get("dev-dependencies")))
    for group in _as_dict(poetry.get("group")).values():
        specs += list(_as_dict(_as_dict(group).get("dependencies")))
    for name in sorted(n for n in names if fnmatch.fnmatch(n, "requirements*.txt")):
        text = scan.text(d / name)
        if text:
            specs += [
                line
                for line in text.splitlines()
                if line.strip() and not line.startswith(("#", "-"))
            ]
    return {n for n in (_dep_name(s) for s in specs) if n}


def _python_package_manager(names: set[str], data: dict[str, Any]) -> str:
    tool = _as_dict(data.get("tool"))
    if "uv.lock" in names or "uv" in tool:
        return "uv"
    if "poetry.lock" in names or "poetry" in tool:
        return "poetry"
    return "pip"


def _python_commands(scan: _Scan, d: Path, names: set[str], pm: str) -> Commands:
    data = scan.toml(d / "pyproject.toml") if "pyproject.toml" in names else {}
    tool = _as_dict(data.get("tool"))
    deps = _python_deps(scan, d, names, data)
    prefix = {"uv": "uv run ", "poetry": "poetry run "}.get(pm, "")

    has_ruff = "ruff" in tool or bool(names & {"ruff.toml", ".ruff.toml"}) or "ruff" in deps
    has_pyright = "pyright" in tool or "pyrightconfig.json" in names or "pyright" in deps
    has_mypy = "mypy" in tool or bool(names & {"mypy.ini", ".mypy.ini"}) or "mypy" in deps
    has_pytest = (
        any(k.startswith("pytest") for k in tool) or "pytest.ini" in names or "pytest" in deps
    )
    has_flake8 = ".flake8" in names or "flake8" in deps
    has_black = "black" in tool or "black" in deps

    lint = format_check = format_fix = typecheck = test = None
    if has_ruff:
        lint = f"{prefix}ruff check ."
        format_check = f"{prefix}ruff format --check ."
        format_fix = f"{prefix}ruff check --fix . && {prefix}ruff format ."
    else:
        if has_flake8:
            lint = f"{prefix}flake8"
        if has_black:
            format_check = f"{prefix}black --check ."
            format_fix = f"{prefix}black ."
    if has_pyright:
        typecheck = f"{prefix}pyright"
    elif has_mypy:
        typecheck = f"{prefix}mypy ."
    if has_pytest:
        test = f"{prefix}pytest"
    return Commands(
        test=test, lint=lint, format_check=format_check, format_fix=format_fix, typecheck=typecheck
    )


# --- Node -----------------------------------------------------------------------------------


def _node_package_manager(names: set[str], pkg: dict[str, Any]) -> str:
    declared = pkg.get("packageManager")
    if isinstance(declared, str):
        name = declared.split("@", 1)[0]
        if name in ("npm", "pnpm", "yarn", "bun"):
            return name
    if "pnpm-lock.yaml" in names:
        return "pnpm"
    if "yarn.lock" in names:
        return "yarn"
    if names & {"bun.lock", "bun.lockb"}:
        return "bun"
    return "npm"


def _node_render(pm: str) -> Callable[[str], str]:
    if pm == "npm":
        return lambda s: f"npm run {s}"
    if pm == "bun":
        return lambda s: f"bun run {s}"
    return lambda s: f"{pm} {s}"


def _node_typecheck_fallback(pm: str, pkg: dict[str, Any], names: set[str]) -> Commands:
    dev = {**_as_dict(pkg.get("dependencies")), **_as_dict(pkg.get("devDependencies"))}
    if "typescript" not in dev or "tsconfig.json" not in names:
        return Commands()
    runner = {"npm": "npx", "pnpm": "pnpm exec", "yarn": "yarn", "bun": "bunx"}[pm]
    return Commands(typecheck=f"{runner} tsc --noEmit")


# --- タスクランナー -------------------------------------------------------------------------


def _from_targets(available: set[str], render: Callable[[str], str]) -> Commands:
    picked: dict[str, str | None] = {}
    for field, candidates in _TARGETS.items():
        name = next((c for c in candidates if c in available), None)
        picked[field] = render(name) if name else None
    return Commands(**picked)


def _is_empty(c: Commands) -> bool:
    return not any((c.test, c.lint, c.format_check, c.format_fix, c.typecheck, c.build))


def _make_targets(text: str) -> set[str]:
    targets: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"([^\s#:=\t][^:=#]*?):(?!=)", line)
        if not m:
            continue
        for t in m.group(1).split():
            if not t.startswith(".") and "%" not in t:
                targets.add(t)
    return targets


def _just_recipes(text: str) -> set[str]:
    recipes: set[str] = set()
    for line in text.splitlines():
        m = re.match(r"@?([A-Za-z_][A-Za-z0-9_-]*)(?:[ \t]+[^:=]*)?:(?!=)", line)
        if m and m.group(1) != "set":
            recipes.add(m.group(1))
    return recipes


def _moon_tasks(scan: _Scan, root: Path, d: Path) -> set[str]:
    files = [d / "moon.yml"]
    moon_dir = root / ".moon"
    files.append(moon_dir / "tasks.yml")
    tasks_dir = moon_dir / "tasks"
    files += (
        [tasks_dir / n for n in sorted(scan.names(tasks_dir)) if n.endswith((".yml", ".yaml"))]
        if tasks_dir.is_dir()
        else []
    )
    found: set[str] = set()
    for f in files:
        if f.is_file():
            found |= set(_as_dict(_as_dict(scan.yaml(f)).get("tasks")))
    return found


def _runner_commands(
    scan: _Scan, root: Path, d: Path, names: set[str], is_root: bool, pm: str | None
) -> tuple[str | None, Commands]:
    """moon > just > make > npm-scripts の順で、実在コマンドを返す最初のランナーを採用する。"""
    if "moon.yml" in names or (is_root and (root / ".moon").is_dir()):
        scope = ":" if is_root else f"{d.name}:"
        cmds = _from_targets(_moon_tasks(scan, root, d), lambda t: f"moon run {scope}{t}")
        if not _is_empty(cmds):
            return "moon", cmds
    for fname in _JUSTFILES:
        if fname in names:
            text = scan.text(d / fname)
            cmds = _from_targets(_just_recipes(text or ""), lambda t: f"just {t}")
            if not _is_empty(cmds):
                return "just", cmds
            break
    for fname in _MAKEFILES:
        if fname in names:
            text = scan.text(d / fname)
            cmds = _from_targets(_make_targets(text or ""), lambda t: f"make {t}")
            if not _is_empty(cmds):
                return "make", cmds
            break
    if "package.json" in names:
        raw_scripts = _as_dict(scan.json(d / "package.json").get("scripts"))
        # npm init の既定プレースホルダは常に失敗するため実在コマンドとして扱わない
        scripts = {k for k, v in raw_scripts.items() if not (isinstance(v, str) and _NO_TEST in v)}
        cmds = _from_targets(scripts, _node_render(pm or "npm"))
        if not _is_empty(cmds):
            return "npm-scripts", cmds
    return None, Commands()


# --- その他言語の既定コマンド ---------------------------------------------------------------


def _java_commands(scan: _Scan, d: Path, names: set[str]) -> tuple[str, Commands]:
    if "pom.xml" in names:
        build_text = scan.text(d / "pom.xml") or ""
        mvn = "mvn"
        cmds = Commands(test=f"{mvn} test", build=f"{mvn} package")
        if "spotless" in build_text:
            return "maven", Commands(
                test=cmds.test,
                build=cmds.build,
                format_check=f"{mvn} spotless:check",
                format_fix=f"{mvn} spotless:apply",
            )
        if "checkstyle" in build_text:
            return "maven", Commands(
                test=cmds.test, build=cmds.build, lint=f"{mvn} checkstyle:check"
            )
        return "maven", cmds
    gradle = "./gradlew" if "gradlew" in names else "gradle"
    build_name = "build.gradle.kts" if "build.gradle.kts" in names else "build.gradle"
    build_text = scan.text(d / build_name) or ""
    return "gradle", Commands(
        test=f"{gradle} test",
        build=f"{gradle} build",
        lint=f"{gradle} checkstyleMain" if "checkstyle" in build_text else None,
        format_check=f"{gradle} spotlessCheck" if "spotless" in build_text else None,
        format_fix=f"{gradle} spotlessApply" if "spotless" in build_text else None,
    )


def _has_dotnet_tests(scan: _Scan, d: Path) -> bool:
    for current, dirs, files in os.walk(d):
        depth = len(Path(current).relative_to(d).parts)
        dirs[:] = [x for x in dirs if x not in IGNORED_DIRS] if depth < 3 else []
        for f in files:
            if f.endswith(".csproj") and "Microsoft.NET.Test.Sdk" in (
                scan.text(Path(current) / f) or ""
            ):
                return True
    return False


def _language_commands(
    scan: _Scan, d: Path, names: set[str], lang: str, pm: str | None
) -> Commands:
    if lang == "python":
        return _python_commands(scan, d, names, pm or "pip")
    if lang == "node":
        return _node_typecheck_fallback(pm or "npm", scan.json(d / "package.json"), names)
    if lang == "go":
        has_golangci = any(fnmatch.fnmatch(n, ".golangci.*") for n in names)
        return Commands(
            test="go test ./...",
            lint="golangci-lint run" if has_golangci else "go vet ./...",
            format_check='test -z "$(gofmt -l .)"',
            format_fix="gofmt -w .",
            build="go build ./...",
        )
    if lang == "rust":
        return Commands(
            test="cargo test",
            lint="cargo clippy -- -D warnings",
            format_check="cargo fmt --check",
            format_fix="cargo fmt",
            typecheck="cargo check",
            build="cargo build",
        )
    if lang == "java":
        return _java_commands(scan, d, names)[1]
    if lang == "csharp":
        return Commands(
            test="dotnet test" if _has_dotnet_tests(scan, d) else None,
            format_check="dotnet format --verify-no-changes",
            format_fix="dotnet format",
            build="dotnet build",
        )
    if lang == "c-cpp":
        if "CMakeLists.txt" in names:
            text = scan.text(d / "CMakeLists.txt") or ""
            return Commands(
                test="ctest --test-dir build"
                if re.search(r"enable_testing|add_test", text)
                else None,
                build="cmake -S . -B build && cmake --build build",
            )
        return Commands(build="meson setup build --reconfigure && meson compile -C build")
    if lang == "terraform":
        return Commands(
            lint="tflint" if ".tflint.hcl" in names else None,
            format_check="terraform fmt -check -recursive",
            format_fix="terraform fmt -recursive",
            typecheck="terraform validate",
        )
    return Commands()


def _merge(all_cmds: list[Commands]) -> Commands:
    def first(field: str) -> str | None:
        return next((v for c in all_cmds if (v := getattr(c, field))), None)

    return Commands(
        test=first("test"),
        lint=first("lint"),
        format_check=first("format_check"),
        format_fix=first("format_fix"),
        typecheck=first("typecheck"),
        build=first("build"),
    )


def _package_manager(scan: _Scan, d: Path, names: set[str], langs: tuple[str, ...]) -> str | None:
    for lang in langs:
        if lang == "python":
            data = scan.toml(d / "pyproject.toml") if "pyproject.toml" in names else {}
            return _python_package_manager(names, data)
        if lang == "node":
            return _node_package_manager(names, scan.json(d / "package.json"))
        if lang == "rust":
            return "cargo"
        if lang == "go":
            return "go"
        if lang == "java":
            return _java_commands(scan, d, names)[0]
        if lang == "csharp":
            return "dotnet"
    return None


def _protected(names: set[str], prefix: str) -> set[str]:
    return {f"{prefix}{n}" for n in names if any(fnmatch.fnmatch(n, p) for p in TOOL_CONFIG_GLOBS)}


def _detect_app(scan: _Scan, d: Path, is_root: bool, root_names: set[str]) -> AppDetection | None:
    names = scan.names(d)
    langs = _languages(scan, d, names)
    if not langs:
        return None
    # ワークスペースのロックファイルはルートにあるため、メンバーはルートの名前集合も参照する
    pm = _package_manager(scan, d, names if is_root else names | root_names, langs)
    rel = scan.rel(d)
    runner, cmds = _runner_commands(scan, scan.root, d, names, is_root, pm)
    if runner is None:
        per_lang = [_language_commands(scan, d, names, lang, pm) for lang in langs]
        cmds = _merge(per_lang)
        runner = _default_runner(langs, pm, cmds)
    protected = _protected(names, "" if is_root else f"{rel}/")
    if not is_root:
        protected |= _protected(root_names, "")
    return AppDetection(
        path=rel,
        languages=langs,
        package_manager=pm,
        task_runner=runner,
        commands=cmds,
        protected_configs=tuple(sorted(protected)),
    )


def _default_runner(langs: tuple[str, ...], pm: str | None, cmds: Commands) -> str | None:
    if _is_empty(cmds):
        return None
    return pm if pm in ("cargo", "go", "maven", "gradle", "dotnet") else None


# --- monorepo -------------------------------------------------------------------------------


def _expand(root: Path, patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in patterns:
        pat = raw.removeprefix("./").rstrip("/")
        if not pat or pat.startswith(("!", "/")) or ".." in Path(pat).parts:
            continue
        if pat.endswith("**"):
            pat = pat[:-1]
        matches = sorted(root.glob(pat)) if any(c in pat for c in "*?[") else [root / pat]
        for p in matches:
            parts = p.relative_to(root).parts
            if p.is_dir() and not any(x in IGNORED_DIRS for x in parts):
                out.append(p)
    return out


def _str_list(value: Any) -> list[str]:
    return [s for s in _as_list(value) if isinstance(s, str)]


def _workspace_patterns(scan: _Scan, root: Path, names: set[str]) -> tuple[list[str], bool]:
    """(メンバーパターン, root が集約専用か)。"""
    patterns: list[str] = []
    aggregator = False
    if "pnpm-workspace.yaml" in names:
        patterns += _str_list(_as_dict(scan.yaml(root / "pnpm-workspace.yaml")).get("packages"))
        aggregator = True
    if "package.json" in names:
        ws = scan.json(root / "package.json").get("workspaces")
        listed = _str_list(ws) or _str_list(_as_dict(ws).get("packages"))
        if listed or isinstance(ws, (list, dict)):
            patterns += listed
            aggregator = True
    if "Cargo.toml" in names:
        cargo = scan.toml(root / "Cargo.toml")
        if "workspace" in cargo:
            patterns += _str_list(_as_dict(cargo["workspace"]).get("members"))
            aggregator = aggregator or "package" not in cargo
    if "pyproject.toml" in names:
        py = scan.toml(root / "pyproject.toml")
        uv_ws = _as_dict(_as_dict(_as_dict(py.get("tool")).get("uv")).get("workspace"))
        if uv_ws:
            patterns += _str_list(uv_ws.get("members"))
            aggregator = aggregator or "project" not in py
    if (root / ".moon" / "workspace.yml").is_file():
        projects = _as_dict(scan.yaml(root / ".moon" / "workspace.yml")).get("projects")
        if isinstance(projects, list):
            patterns += _str_list(projects)
        elif isinstance(projects, dict):
            patterns += _str_list(projects.get("globs")) + [
                v for v in projects.values() if isinstance(v, str)
            ]
            patterns += [
                v for v in _as_dict(projects.get("sources")).values() if isinstance(v, str)
            ]
    return patterns, aggregator


def _member_dirs(scan: _Scan, root: Path, names: set[str]) -> tuple[list[Path], bool]:
    patterns, aggregator = _workspace_patterns(scan, root, names)
    members = _expand(root, patterns)
    members += _expand(root, [f"{c}/*" for c in _CONVENTIONAL_DIRS])
    unique = sorted({m for m in members if m != root}, key=lambda p: p.as_posix())
    return unique, aggregator


# --- ハーネス資産・CI -----------------------------------------------------------------------


def _harness(scan: _Scan, root: Path, names: set[str]) -> tuple[list[str], list[str]]:
    found: list[str] = []
    symlinks: list[str] = []
    for entry in _HARNESS_ENTRIES:
        p = root / entry
        if not os.path.lexists(p):
            continue
        found.append(entry)
        if p.is_symlink():
            symlinks.append(entry)
        if p.is_dir() and not p.is_symlink():
            for current, dirs, files in os.walk(p):
                depth = len(Path(current).relative_to(p).parts)
                for child in sorted(dirs + files):
                    cp = Path(current) / child
                    if cp.is_symlink():
                        rel = scan.rel(cp)
                        found.append(rel)
                        symlinks.append(rel)
                dirs[:] = [x for x in dirs if x not in IGNORED_DIRS and depth < 2]
    return found, symlinks


def _ci_files(scan: _Scan, root: Path) -> list[str]:
    found: list[str] = []
    workflows = root / ".github" / "workflows"
    if workflows.is_dir():
        found += [
            f".github/workflows/{n}"
            for n in sorted(scan.names(workflows))
            if n.endswith((".yml", ".yaml"))
        ]
    found += [f for f in _CI_FILES if (root / f).is_file()]
    return found


def detect(root: Path) -> DetectionResult:
    root = Path(root)
    scan = _Scan(root)
    root_names = scan.names(root)
    members, aggregator = _member_dirs(scan, root, root_names)

    app_dirs: list[tuple[Path, bool]] = []
    member_apps = [(m, False) for m in members]
    if not (aggregator and any(_languages(scan, m, scan.names(m)) for m in members)):
        app_dirs.append((root, True))
    app_dirs += member_apps

    apps = tuple(
        app
        for d, is_root in app_dirs
        if (app := _detect_app(scan, d, is_root, root_names)) is not None
    )
    if not apps:
        scan.notes.append("言語マニフェストが見つからないためアプリを検出できませんでした")
    harness, symlinks = _harness(scan, root, root_names)
    return DetectionResult(
        root_apps=apps,
        ci_files=tuple(_ci_files(scan, root)),
        existing_harness=tuple(harness),
        existing_symlinks=tuple(symlinks),
        notes=tuple(scan.notes),
    )
