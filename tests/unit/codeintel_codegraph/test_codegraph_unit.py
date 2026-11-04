import json

import pytest

from seh.contracts.common import ResultStatus
from seh.contracts.module import HealthResult
from seh.providers.codeintel import codegraph as cg
from seh.providers.codeintel.base import Impact, Symbol, provider_for
from seh.runtime.process import ProcessResult

HELP_WITH_JSON = "Options:\n  -p, --path <path>\n  -j, --json            Output as JSON\n"
HELP_WITHOUT_JSON = "Options:\n  -p, --path <path>\n"


def proc(stdout: str = "", exit_code: int | None = 0, stderr: str = "") -> ProcessResult:
    return ProcessResult(
        "d", exit_code, stdout.encode(), stderr.encode(), False, False, False, False, 0.0
    )


class FakeCli:
    """argv の先頭サブコマンド(+ --help)で応答を引く。呼び出しは calls に記録する。"""

    def __init__(self, responses: dict[str, ProcessResult]) -> None:
        self.responses = responses
        self.calls: list[tuple[list[str], dict]] = []

    async def __call__(self, argv, *, cwd, env, timeout_seconds, **_):
        self.calls.append((list(argv), {"cwd": cwd, "env": dict(env)}))
        key = f"{argv[1]} --help" if "--help" in argv else argv[1]
        return self.responses[key]

    def argvs(self) -> list[list[str]]:
        return [c[0] for c in self.calls]


@pytest.fixture
def indexed(tmp_path):
    (tmp_path / ".codegraph").mkdir()
    return tmp_path


def install(monkeypatch, responses) -> FakeCli:
    fake = FakeCli(responses)
    monkeypatch.setattr(cg, "run_process", fake)
    return fake


def test_provider_for_returns_codegraph_provider(tmp_path):
    provider = provider_for("codegraph", tmp_path)

    assert isinstance(provider, cg.CodeGraphProvider)
    assert provider.name == "codegraph"


def test_search_symbols_uses_json_when_help_advertises_it(monkeypatch, indexed):
    payload = [
        {"node": {"kind": "function", "name": "helper", "filePath": "util.py", "startLine": 1}},
        {"node": {"kind": "import", "name": "util", "filePath": "main.py", "startLine": 1}},
    ]
    fake = install(
        monkeypatch,
        {"query --help": proc(HELP_WITH_JSON), "query": proc(json.dumps(payload))},
    )

    result = cg.CodeGraphProvider(indexed).search_symbols("helper")

    assert result.status is ResultStatus.OK
    assert result.data == (
        Symbol("util", "unknown", "main.py", 1),
        Symbol("helper", "function", "util.py", 1),
    )
    assert ["codegraph", "query", "--json", "helper"] in fake.argvs()
    assert fake.calls[-1][1]["cwd"] == indexed


def test_search_symbols_parses_text_when_json_unsupported(monkeypatch, indexed):
    text = (
        '\x1b[1m\nSearch Results for "helper":\n\x1b[0m\n'
        "\x1b[36mfunction    \x1b[0m\x1b[37mhelper\x1b[0m\n"
        "\x1b[2m  util.py:1\x1b[0m\n"
        "\x1b[2m  (x)\x1b[0m\n"
    )
    fake = install(
        monkeypatch,
        {"query --help": proc(HELP_WITHOUT_JSON), "query": proc(text)},
    )

    result = cg.CodeGraphProvider(indexed).search_symbols("helper")

    assert result.data == (Symbol("helper", "function", "util.py", 1),)
    assert all("--json" not in argv for argv in fake.argvs())


def test_json_support_is_probed_once_per_subcommand(monkeypatch, indexed):
    fake = install(
        monkeypatch,
        {"query --help": proc(HELP_WITH_JSON), "query": proc("[]")},
    )
    provider = cg.CodeGraphProvider(indexed)

    provider.search_symbols("a")
    provider.search_symbols("b")

    helps = [a for a in fake.argvs() if "--help" in a]
    assert helps == [["codegraph", "query", "--help"]]


def test_search_symbols_empty_result_is_not_found(monkeypatch, indexed):
    install(monkeypatch, {"query --help": proc(HELP_WITH_JSON), "query": proc("[]")})

    result = cg.CodeGraphProvider(indexed).search_symbols("zzz")

    assert result.status is ResultStatus.NOT_FOUND


def test_text_no_results_message_is_not_found(monkeypatch, indexed):
    install(
        monkeypatch,
        {"query --help": proc(HELP_WITHOUT_JSON), "query": proc('ℹ No results found for "zzz"\n')},
    )

    result = cg.CodeGraphProvider(indexed).search_symbols("zzz")

    assert result.status is ResultStatus.NOT_FOUND


def test_unparseable_output_is_error_not_empty_ok(monkeypatch, indexed):
    install(
        monkeypatch,
        {"query --help": proc(HELP_WITH_JSON), "query": proc("<<<garbage>>>")},
    )

    result = cg.CodeGraphProvider(indexed).search_symbols("x")

    assert result.status is ResultStatus.ERROR
    assert result.data is None


def test_unparseable_text_is_error(monkeypatch, indexed):
    install(
        monkeypatch,
        {"query --help": proc(HELP_WITHOUT_JSON), "query": proc("totally unexpected\nlines\n")},
    )

    result = cg.CodeGraphProvider(indexed).search_symbols("x")

    assert result.status is ResultStatus.ERROR


def test_dependencies_unions_callers_and_callees_paths(monkeypatch, indexed):
    callers = {"symbol": "f", "callers": [{"name": "run", "filePath": "./b/main.py"}]}
    callees = {
        "symbol": "f",
        "callees": [{"name": "h", "filePath": "a/util.py"}, {"name": "r", "filePath": "b/main.py"}],
    }
    fake = install(
        monkeypatch,
        {
            "callers --help": proc(HELP_WITH_JSON),
            "callees --help": proc(HELP_WITH_JSON),
            "callers": proc(json.dumps(callers)),
            "callees": proc(json.dumps(callees)),
        },
    )

    result = cg.CodeGraphProvider(indexed).dependencies("f")

    assert result.status is ResultStatus.OK
    assert result.data == ("a/util.py", "b/main.py")
    assert ["codegraph", "callers", "--json", "f"] in fake.argvs()
    assert ["codegraph", "callees", "--json", "f"] in fake.argvs()


def test_dependencies_symbol_not_found_text_is_not_found(monkeypatch, indexed):
    missing = proc('ℹ Symbol "zzz" not found\n')
    install(
        monkeypatch,
        {
            "callers --help": proc(HELP_WITH_JSON),
            "callees --help": proc(HELP_WITH_JSON),
            "callers": missing,
            "callees": missing,
        },
    )

    result = cg.CodeGraphProvider(indexed).dependencies("zzz")

    assert result.status is ResultStatus.NOT_FOUND


AFFECTED = {
    "changedFiles": ["src/app.py"],
    "affectedTests": [
        "tests/test_app.py",
        "pkg/test_x.py",
        "pkg/x_test.py",
        "web/a.test.ts",
        "web/b.spec.ts",
        "svc/c_test.go",
        "tests/helpers/data.json",
        "src/app.py",
    ],
}


def test_affected_tests_keeps_only_test_file_patterns(monkeypatch, indexed):
    fake = install(
        monkeypatch,
        {"affected --help": proc(HELP_WITH_JSON), "affected": proc(json.dumps(AFFECTED))},
    )

    result = cg.CodeGraphProvider(indexed).affected_tests(["src/app.py"])

    assert result.status is ResultStatus.OK
    assert result.data == (
        "pkg/test_x.py",
        "pkg/x_test.py",
        "svc/c_test.go",
        "tests/helpers/data.json",
        "tests/test_app.py",
        "web/a.test.ts",
        "web/b.spec.ts",
    )
    assert ["codegraph", "affected", "--json", "src/app.py"] in fake.argvs()


def test_affected_tests_none_is_not_found(monkeypatch, indexed):
    empty = {"changedFiles": ["a.py"], "affectedTests": []}
    install(
        monkeypatch,
        {"affected --help": proc(HELP_WITH_JSON), "affected": proc(json.dumps(empty))},
    )

    result = cg.CodeGraphProvider(indexed).affected_tests(["a.py"])

    assert result.status is ResultStatus.NOT_FOUND


def test_affected_tests_text_lists_paths(monkeypatch, indexed):
    install(
        monkeypatch,
        {
            "affected --help": proc(HELP_WITHOUT_JSON),
            "affected": proc("tests/test_a.py\nsrc/a.py\n"),
        },
    )

    result = cg.CodeGraphProvider(indexed).affected_tests(["src/a.py"])

    assert result.data == ("tests/test_a.py",)


def test_change_impact_returns_paths_and_empty_symbols(monkeypatch, indexed):
    data = {"changedFiles": ["src/app.py"], "affectedTests": ["tests/test_app.py"]}
    install(
        monkeypatch,
        {"affected --help": proc(HELP_WITH_JSON), "affected": proc(json.dumps(data))},
    )

    result = cg.CodeGraphProvider(indexed).change_impact(["src/app.py"])

    assert result.status is ResultStatus.OK
    assert result.data == Impact(("src/app.py", "tests/test_app.py"), ())


def test_change_impact_without_paths_is_not_found(monkeypatch, indexed):
    install(monkeypatch, {})

    result = cg.CodeGraphProvider(indexed).change_impact([])

    assert result.status is ResultStatus.NOT_FOUND


def test_missing_command_is_error_with_install_hint(monkeypatch, indexed):
    async def boom(argv, **_):
        raise FileNotFoundError("codegraph")

    monkeypatch.setattr(cg, "run_process", boom)

    result = cg.CodeGraphProvider(indexed).search_symbols("x")

    assert result.status is ResultStatus.ERROR
    assert "npm i -g @colbymchenry/codegraph" in (result.message or "")


def test_nonzero_exit_is_error_with_masked_stderr(monkeypatch, indexed):
    secret = "sk-ant-api03-" + "A" * 40
    install(
        monkeypatch,
        {
            "query --help": proc(HELP_WITH_JSON),
            "query": proc("", exit_code=2, stderr=f"boom {secret}"),
        },
    )

    result = cg.CodeGraphProvider(indexed).search_symbols("x")

    assert result.status is ResultStatus.ERROR
    assert "boom" in (result.message or "")
    assert secret not in (result.message or "")


def test_query_without_index_is_index_missing_error(monkeypatch, tmp_path):
    fake = install(monkeypatch, {})

    result = cg.CodeGraphProvider(tmp_path).search_symbols("x")

    assert result.status is ResultStatus.ERROR
    assert "INDEX_MISSING" in (result.message or "")
    assert fake.calls == []


def test_index_runs_init_when_no_codegraph_dir(monkeypatch, tmp_path):
    fake = install(monkeypatch, {"init": proc("done")})

    result = cg.CodeGraphProvider(tmp_path).index(tmp_path)

    assert result.status is ResultStatus.OK
    assert fake.argvs() == [["codegraph", "init", str(tmp_path)]]


def test_index_runs_sync_when_codegraph_dir_exists(monkeypatch, indexed):
    fake = install(monkeypatch, {"sync": proc("done")})

    result = cg.CodeGraphProvider(indexed).index(indexed)

    assert result.status is ResultStatus.OK
    assert fake.argvs() == [["codegraph", "sync", str(indexed)]]


def test_home_override_is_passed_to_env(monkeypatch, tmp_path):
    fake = install(monkeypatch, {"init": proc("")})
    home = tmp_path / "home"

    cg.CodeGraphProvider(tmp_path, home=home).index(tmp_path)

    assert fake.calls[0][1]["env"]["HOME"] == str(home)


def test_healthcheck_reports_version(monkeypatch, tmp_path):
    fake = install(monkeypatch, {"--version": proc("1.4.1\n")})

    result = cg.CodeGraphProvider(tmp_path).healthcheck()

    assert result.status is ResultStatus.OK
    assert isinstance(result.data, HealthResult)
    assert "1.4.1" in result.data.message
    assert fake.argvs() == [["codegraph", "--version"]]


def test_healthcheck_missing_command_is_error(monkeypatch, tmp_path):
    async def boom(argv, **_):
        raise FileNotFoundError("codegraph")

    monkeypatch.setattr(cg, "run_process", boom)

    result = cg.CodeGraphProvider(tmp_path).healthcheck()

    assert result.status is ResultStatus.ERROR
