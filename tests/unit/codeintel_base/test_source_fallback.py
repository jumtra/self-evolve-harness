import pytest

from seh.contracts.common import ResultStatus
from seh.providers.codeintel import source_fallback
from seh.providers.codeintel.base import Impact, Symbol
from seh.providers.codeintel.source_fallback import SourceFallbackProvider


def test_search_symbols_finds_python_function_class_and_method(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "def helper():\n    pass\n\n\nclass Greeter:\n    def hello(self):\n        pass\n\n\n"
        "async def fetch():\n    pass\n"
    )
    provider = SourceFallbackProvider(tmp_path)

    function = provider.search_symbols("helper")
    klass = provider.search_symbols("Greeter")
    method = provider.search_symbols("hello")
    coroutine = provider.search_symbols("fetch")

    assert function.data == (Symbol("helper", "function", "pkg/mod.py", 1),)
    assert klass.data == (Symbol("Greeter", "class", "pkg/mod.py", 5),)
    assert method.data == (Symbol("hello", "method", "pkg/mod.py", 6),)
    assert coroutine.data == (Symbol("fetch", "function", "pkg/mod.py", 10),)


@pytest.mark.parametrize("rg_available", [True, False])
def test_search_symbols_finds_js_and_go_functions_with_or_without_rg(
    tmp_path, monkeypatch, rg_available
):
    (tmp_path / "app.js").write_text("const x = 1;\nfunction render() {}\n")
    (tmp_path / "main.go").write_text("package main\n\nfunc render() {}\n")
    if not rg_available:
        monkeypatch.setattr(source_fallback.shutil, "which", lambda _name: None)
    provider = SourceFallbackProvider(tmp_path)

    result = provider.search_symbols("render")

    assert result.status is ResultStatus.OK
    assert result.data == (
        Symbol("render", "function", "app.js", 2),
        Symbol("render", "function", "main.go", 3),
    )


def test_search_symbols_returns_not_found_when_nothing_matches(tmp_path):
    (tmp_path / "a.py").write_text("def other():\n    pass\n")
    provider = SourceFallbackProvider(tmp_path)

    result = provider.search_symbols("missing")

    assert result.status is ResultStatus.NOT_FOUND


def test_dependencies_lists_referencing_files_except_definition(tmp_path):
    (tmp_path / "core.py").write_text("def compute():\n    return 1\n")
    (tmp_path / "user.py").write_text("from core import compute\n\nvalue = compute()\n")
    (tmp_path / "other.py").write_text("computed = 2\n")
    provider = SourceFallbackProvider(tmp_path)

    result = provider.dependencies("compute")

    assert result.status is ResultStatus.OK
    assert result.data == ("user.py",)


def test_dependencies_returns_not_found_without_references(tmp_path):
    (tmp_path / "core.py").write_text("def lonely():\n    return 1\n")
    provider = SourceFallbackProvider(tmp_path)

    result = provider.dependencies("lonely")

    assert result.status is ResultStatus.NOT_FOUND


def test_change_impact_returns_changed_file_and_referencing_files(tmp_path):
    (tmp_path / "core.py").write_text("def compute():\n    return 1\n\n\nclass Engine:\n    pass\n")
    (tmp_path / "user.py").write_text("from core import compute\n")
    (tmp_path / "web.js").write_text("// uses Engine\n")
    (tmp_path / "unrelated.py").write_text("x = 1\n")
    provider = SourceFallbackProvider(tmp_path)

    result = provider.change_impact(["core.py"])

    assert result.status is ResultStatus.OK
    assert result.data == Impact(
        paths=("core.py", "user.py", "web.js"), symbols=("Engine", "compute")
    )


def test_affected_tests_is_unsupported_without_name_guessing(tmp_path):
    (tmp_path / "core.py").write_text("def compute():\n    return 1\n")
    (tmp_path / "test_core.py").write_text("from core import compute\n")
    provider = SourceFallbackProvider(tmp_path)

    result = provider.affected_tests(["core.py"])

    assert result.status is ResultStatus.UNSUPPORTED
    assert result.data is None
    assert "名前規則での推定はしない" in (result.message or "")


def test_excluded_directories_are_not_searched(tmp_path):
    for name in (".git", ".venv", "node_modules", "dist", "build", ".harness"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "hidden.py").write_text("def secret():\n    pass\n")
        (tmp_path / name / "hidden.js").write_text("function secret() {}\n")
    (tmp_path / "real.py").write_text("x = secret\n")
    provider = SourceFallbackProvider(tmp_path)

    search = provider.search_symbols("secret")
    deps = provider.dependencies("secret")

    assert search.status is ResultStatus.NOT_FOUND
    assert deps.data == ("real.py",)


def test_operations_do_not_modify_files(tmp_path):
    (tmp_path / "core.py").write_text("def compute():\n    return 1\n")
    (tmp_path / "web.js").write_text("function compute() {}\n")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    provider = SourceFallbackProvider(tmp_path)

    provider.index(tmp_path)
    provider.search_symbols("compute")
    provider.dependencies("compute")
    provider.change_impact(["core.py"])
    provider.affected_tests(["core.py"])
    provider.healthcheck()

    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_healthcheck_reports_rg_availability(tmp_path, monkeypatch):
    monkeypatch.setattr(source_fallback.shutil, "which", lambda _name: None)
    provider = SourceFallbackProvider(tmp_path)

    result = provider.healthcheck()

    assert result.status is ResultStatus.OK
    assert "rg" in (result.message or "")
