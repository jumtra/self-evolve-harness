import json

from seh.contracts.common import ResultStatus
from seh.contracts.module import HealthResult
from seh.providers.codeintel import graphify
from seh.providers.codeintel.base import Impact, Symbol, provider_for
from seh.runtime.process import ProcessResult


def test_index_runs_full_build_first_with_llm_backend_disabled(tmp_path, monkeypatch):
    calls = []

    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        calls.append((list(argv), cwd, dict(env)))
        return ProcessResult("d", 0, b"", b"", False, False, False, False, 0.1)

    monkeypatch.setattr(graphify, "run_process", fake_run_process)
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: "/usr/bin/graphify")
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.index(tmp_path)

    assert result.status is ResultStatus.OK
    assert calls[0][0] == ["graphify", ".", "--no-viz"]
    assert calls[0][1] == tmp_path
    assert calls[0][2]["GRAPHIFY_BACKEND"] == "none"


def test_index_updates_incrementally_when_graph_exists(tmp_path, monkeypatch):
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "graph.json").write_text("{}")
    calls = []

    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        calls.append(list(argv))
        return ProcessResult("d", 0, b"", b"", False, False, False, False, 0.1)

    monkeypatch.setattr(graphify, "run_process", fake_run_process)
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: "/usr/bin/graphify")
    provider = graphify.GraphifyProvider(tmp_path)

    provider.index(tmp_path)

    assert calls == [["graphify", ".", "--update", "--no-viz"]]


def test_search_symbols_parses_text_lines_on_exit_0(tmp_path, monkeypatch):
    calls = []

    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        calls.append(list(argv))
        out = b"compute (function) src/core.py:12\nGreeter (class) src/g.py:3\n"
        return ProcessResult("d", 0, out, b"", False, False, False, False, 0.1)

    monkeypatch.setattr(graphify, "run_process", fake_run_process)
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: "/usr/bin/graphify")
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.search_symbols("compute")

    assert calls == [["graphify", "query", "compute"]]
    assert result.status is ResultStatus.OK
    assert result.data == (
        Symbol("compute", "function", "src/core.py", 12),
        Symbol("Greeter", "class", "src/g.py", 3),
    )


def test_search_symbols_parses_json_on_exit_0(tmp_path, monkeypatch):
    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        out = json.dumps([{"name": "run", "kind": "method", "path": "a.py", "line": 7}]).encode()
        return ProcessResult("d", 0, out, b"", False, False, False, False, 0.1)

    monkeypatch.setattr(graphify, "run_process", fake_run_process)
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: "/usr/bin/graphify")
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.search_symbols("run")

    assert result.data == (Symbol("run", "method", "a.py", 7),)


def test_search_symbols_ambiguous_exit_3_is_error_with_candidates(tmp_path, monkeypatch):
    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        out = b"candidates: a.run, b.run\n"
        return ProcessResult("d", 3, out, b"", False, False, False, False, 0.1)

    monkeypatch.setattr(graphify, "run_process", fake_run_process)
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: "/usr/bin/graphify")
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.search_symbols("run")

    assert result.status is ResultStatus.ERROR
    assert result.message is not None
    assert "AMBIGUOUS" in result.message
    assert "a.run, b.run" in result.message


def test_search_symbols_exit_4_is_not_found(tmp_path, monkeypatch):
    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        return ProcessResult("d", 4, b"", b"", False, False, False, False, 0.1)

    monkeypatch.setattr(graphify, "run_process", fake_run_process)
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: "/usr/bin/graphify")
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.search_symbols("missing")

    assert result.status is ResultStatus.NOT_FOUND


def test_search_symbols_unparsable_output_is_error_not_empty_ok(tmp_path, monkeypatch):
    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        return ProcessResult("d", 0, b"some prose answer\n", b"", False, False, False, False, 0.1)

    monkeypatch.setattr(graphify, "run_process", fake_run_process)
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: "/usr/bin/graphify")
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.search_symbols("x")

    assert result.status is ResultStatus.ERROR


def test_dependencies_returns_related_files_from_explain(tmp_path, monkeypatch):
    calls = []

    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        calls.append(list(argv))
        out = b"- src/a.py\n- src/b.py\n"
        return ProcessResult("d", 0, out, b"", False, False, False, False, 0.1)

    monkeypatch.setattr(graphify, "run_process", fake_run_process)
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: "/usr/bin/graphify")
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.dependencies("compute")

    assert calls == [["graphify", "explain", "compute"]]
    assert result.status is ResultStatus.OK
    assert result.data == ("src/a.py", "src/b.py")


def test_dependencies_exit_4_is_not_found(tmp_path, monkeypatch):
    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        return ProcessResult("d", 4, b"", b"", False, False, False, False, 0.1)

    monkeypatch.setattr(graphify, "run_process", fake_run_process)
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: "/usr/bin/graphify")
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.dependencies("missing")

    assert result.status is ResultStatus.NOT_FOUND


def test_change_impact_collects_files_connected_by_edges(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    graph = {
        "schema_version": "1",
        "nodes": [
            {"id": "n1", "file": "src/a.py"},
            {"id": "n2", "file": "src/b.py"},
            {"id": "n3", "file": "src/c.py"},
            {"id": "n4", "file": "src/unrelated.py"},
        ],
        "edges": [{"source": "n2", "target": "n1"}, {"source": "n1", "target": "n3"}],
    }
    (tmp_path / "graphify-out" / "graph.json").write_text(json.dumps(graph))
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.change_impact(["src/a.py"])

    assert result.status is ResultStatus.OK
    assert result.data == Impact(("src/a.py", "src/b.py", "src/c.py"), ())


def test_change_impact_accepts_links_key_and_integer_schema_version(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    graph = {
        "schema_version": 1,
        "nodes": [{"id": "n1", "source_file": "a.py"}, {"id": "n2", "path": "b.py"}],
        "links": [{"source": "n1", "target": "n2"}],
    }
    (tmp_path / "graphify-out" / "graph.json").write_text(json.dumps(graph))
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.change_impact(["a.py"])

    assert result.data == Impact(("a.py", "b.py"), ())


def test_change_impact_rejects_unexpected_schema_version(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    graph = {"schema_version": "2", "nodes": [], "edges": []}
    (tmp_path / "graphify-out" / "graph.json").write_text(json.dumps(graph))
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.change_impact(["a.py"])

    assert result.status is ResultStatus.ERROR
    assert result.message is not None
    assert "UNSUPPORTED_GRAPH_SCHEMA" in result.message


def test_change_impact_without_graph_json_is_index_missing(tmp_path):
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.change_impact(["a.py"])

    assert result.status is ResultStatus.ERROR
    assert result.message is not None
    assert "INDEX_MISSING" in result.message


def test_change_impact_with_unknown_keys_is_error(tmp_path):
    (tmp_path / "graphify-out").mkdir()
    graph = {"schema_version": "1", "vertices": [{"name": "x"}], "relations": []}
    (tmp_path / "graphify-out" / "graph.json").write_text(json.dumps(graph))
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.change_impact(["a.py"])

    assert result.status is ResultStatus.ERROR


def test_affected_tests_is_unsupported(tmp_path):
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.affected_tests(["a.py"])

    assert result.status is ResultStatus.UNSUPPORTED


def test_healthcheck_without_command_explains_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: None)
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.healthcheck()

    assert isinstance(result.data, HealthResult)
    assert result.data.ok is False
    assert "uv tool install graphifyy" in result.data.message
    assert "自動インストールしません" in result.data.message


def test_operations_without_command_return_error_with_install_message(tmp_path, monkeypatch):
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: None)
    provider = graphify.GraphifyProvider(tmp_path)

    results = [
        provider.index(tmp_path),
        provider.search_symbols("x"),
        provider.dependencies("x"),
    ]

    for result in results:
        assert result.status is ResultStatus.ERROR
        assert result.message is not None
        assert "uv tool install graphifyy" in result.message


def test_healthcheck_with_command_runs_version(tmp_path, monkeypatch):
    calls = []

    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        calls.append(list(argv))
        return ProcessResult("d", 0, b"graphify 1.0\n", b"", False, False, False, False, 0.1)

    monkeypatch.setattr(graphify, "run_process", fake_run_process)
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: "/usr/bin/graphify")
    provider = graphify.GraphifyProvider(tmp_path)

    result = provider.healthcheck()

    assert calls == [["graphify", "--version"]]
    assert result.status is ResultStatus.OK
    assert isinstance(result.data, HealthResult)
    assert result.data.ok is True


def test_install_command_is_never_called(tmp_path, monkeypatch):
    calls = []

    async def fake_run_process(argv, *, cwd, env, timeout_seconds, **kwargs):
        calls.append(list(argv))
        return ProcessResult("d", 0, b"a (function) a.py:1\n", b"", False, False, False, False, 0.1)

    monkeypatch.setattr(graphify, "run_process", fake_run_process)
    monkeypatch.setattr(graphify.shutil, "which", lambda cmd: "/usr/bin/graphify")
    provider = graphify.GraphifyProvider(tmp_path)

    provider.healthcheck()
    provider.index(tmp_path)
    provider.search_symbols("a")
    provider.dependencies("a")

    assert calls
    assert all("install" not in argv for argv in calls)


def test_provider_for_graphify_returns_graphify_provider(tmp_path):
    provider = provider_for("graphify", tmp_path)

    assert isinstance(provider, graphify.GraphifyProvider)
