from __future__ import annotations

import pytest

from seh.contracts.task import Edge, NodeKind, RiskRank, WorkUnit
from seh.runtime.graph import GraphError, WorkflowGraph


def test_valid_dag_layers_ready_and_downstream() -> None:
    nodes = (
        WorkUnit("s", NodeKind.SPLITTER, (), {}, "schema://s", (), (), RiskRank.R0),
        WorkUnit("w1", NodeKind.WORKER, ("s",), {"t": ""}, "schema://w", ("a/",), (), RiskRank.R1),
        WorkUnit("w2", NodeKind.WORKER, ("s",), {"t": ""}, "schema://w", ("b/",), (), RiskRank.R1),
        WorkUnit("w3", NodeKind.WORKER, ("s",), {"t": ""}, "schema://w", ("c/",), (), RiskRank.R1),
        WorkUnit(
            "c",
            NodeKind.CODE,
            ("w1", "w2", "w3"),
            {"a": "", "b": "", "c": ""},
            "schema://c",
            (),
            (),
            RiskRank.R0,
        ),
        WorkUnit("g", NodeKind.GATE, ("c",), {"r": ""}, None, (), (), RiskRank.R0),
    )
    edges = (
        Edge("s", "out", "w1", "t"),
        Edge("s", "out", "w2", "t"),
        Edge("s", "out", "w3", "t"),
        Edge("w1", "out", "c", "a"),
        Edge("w2", "out", "c", "b"),
        Edge("w3", "out", "c", "c"),
        Edge("c", "out", "g", "r"),
    )

    graph = WorkflowGraph.build(nodes, edges)

    assert graph.topological_layers() == (("s",), ("w1", "w2", "w3"), ("c",), ("g",))
    assert graph.ready(set()) == ("s",)
    assert graph.ready({"s"}, running={"w2"}) == ("w1", "w3")
    assert graph.ready({"s", "w1", "w2", "w3"}) == ("c",)
    assert graph.downstream("w2") == frozenset({"c", "g"})
    assert graph.downstream("g") == frozenset()


def test_downstream_of_failed_node_excludes_independent_successes() -> None:
    nodes = (
        WorkUnit("a", NodeKind.WORKER, (), {}, "schema://w", ("a/",), (), RiskRank.R1),
        WorkUnit("b", NodeKind.WORKER, (), {}, "schema://w", ("b/",), (), RiskRank.R1),
        WorkUnit("c", NodeKind.WORKER, ("a",), {"x": ""}, "schema://w", ("c/",), (), RiskRank.R1),
        WorkUnit("d", NodeKind.WORKER, ("b",), {"x": ""}, "schema://w", ("d/",), (), RiskRank.R1),
    )
    edges = (Edge("a", "out", "c", "x"), Edge("b", "out", "d", "x"))

    graph = WorkflowGraph.build(nodes, edges)

    assert graph.downstream("a") == frozenset({"c"})
    assert "b" not in graph.downstream("a")
    assert "d" not in graph.downstream("a")


def test_layers_are_independent_of_input_order() -> None:
    a = WorkUnit("a", NodeKind.WORKER, (), {}, "schema://w", ("a/",), (), RiskRank.R1)
    b = WorkUnit("b", NodeKind.WORKER, (), {}, "schema://w", ("b/",), (), RiskRank.R1)
    c = WorkUnit(
        "c", NodeKind.CODE, ("a", "b"), {"x": "", "y": ""}, "schema://c", (), (), RiskRank.R0
    )
    e1 = Edge("a", "out", "c", "x")
    e2 = Edge("b", "out", "c", "y")

    forward = WorkflowGraph.build((a, b, c), (e1, e2))
    shuffled = WorkflowGraph.build((c, b, a), (e2, e1))

    assert forward.topological_layers() == shuffled.topological_layers() == (("a", "b"), ("c",))


def test_external_artifact_reference_binds_input_without_edge() -> None:
    nodes = (
        WorkUnit(
            "w",
            NodeKind.WORKER,
            (),
            {"src": "artifact://input/spec"},
            "schema://w",
            ("a/",),
            (),
            RiskRank.R1,
        ),
    )

    graph = WorkflowGraph.build(nodes, ())

    assert graph.topological_layers() == (("w",),)


def test_code_node_may_have_empty_write_allowlist() -> None:
    nodes = (WorkUnit("c", NodeKind.CODE, (), {}, "schema://c", (), (), RiskRank.R0),)

    graph = WorkflowGraph.build(nodes, ())

    assert graph.nodes == nodes


@pytest.mark.parametrize(
    ("nodes", "edges", "expected"),
    [
        pytest.param(
            (
                WorkUnit("a", NodeKind.CODE, (), {}, "s", (), (), RiskRank.R0),
                WorkUnit("a", NodeKind.CODE, (), {}, "s", (), (), RiskRank.R0),
            ),
            (),
            "DUPLICATE_NODE:a",
            id="duplicate-node",
        ),
        pytest.param(
            (WorkUnit("a", NodeKind.CODE, ("x",), {}, "s", (), (), RiskRank.R0),),
            (),
            "UNKNOWN_DEPENDENCY:a->x",
            id="unknown-dependency",
        ),
        pytest.param(
            (WorkUnit("a", NodeKind.CODE, (), {}, "s", (), (), RiskRank.R0),),
            (Edge("a", "out", "zz", "i"),),
            "UNKNOWN_EDGE_NODE:zz",
            id="unknown-edge-node",
        ),
        pytest.param(
            (WorkUnit("a", NodeKind.CODE, (), {"i": ""}, "s", (), (), RiskRank.R0),),
            (),
            "UNBOUND_INPUT:a.i",
            id="unbound-input",
        ),
        pytest.param(
            (
                WorkUnit("a", NodeKind.CODE, (), {}, "s", (), (), RiskRank.R0),
                WorkUnit("b", NodeKind.CODE, ("a",), {}, "s", (), (), RiskRank.R0),
            ),
            (Edge("a", "out", "b", "nope"),),
            "UNKNOWN_INPUT:b.nope",
            id="unknown-input",
        ),
        pytest.param(
            (
                WorkUnit("a", NodeKind.CODE, (), {}, "s", (), (), RiskRank.R0),
                WorkUnit("b", NodeKind.CODE, (), {}, "s", (), (), RiskRank.R0),
                WorkUnit("c", NodeKind.CODE, ("a", "b"), {"i": ""}, "s", (), (), RiskRank.R0),
            ),
            (Edge("a", "out", "c", "i"), Edge("b", "out", "c", "i")),
            "DUPLICATE_BINDING:c.i",
            id="duplicate-binding",
        ),
        pytest.param(
            (
                WorkUnit("a", NodeKind.CODE, (), {}, "s", (), (), RiskRank.R0),
                WorkUnit("b", NodeKind.CODE, ("a",), {}, "s", (), (), RiskRank.R0),
            ),
            (),
            "UNNECESSARY_DEPENDENCY:b->a",
            id="unnecessary-dependency",
        ),
        pytest.param(
            (
                WorkUnit("a", NodeKind.CODE, (), {}, "s", (), (), RiskRank.R0),
                WorkUnit("b", NodeKind.CODE, (), {"i": ""}, "s", (), (), RiskRank.R0),
            ),
            (Edge("a", "out", "b", "i"),),
            "MISSING_DEPENDENCY:b->a",
            id="missing-dependency",
        ),
        pytest.param(
            (
                WorkUnit("a", NodeKind.CODE, ("b",), {"i": ""}, "s", (), (), RiskRank.R0),
                WorkUnit("b", NodeKind.CODE, ("a",), {"i": ""}, "s", (), (), RiskRank.R0),
            ),
            (Edge("b", "out", "a", "i"), Edge("a", "out", "b", "i")),
            "CYCLE:a->b->a",
            id="cycle",
        ),
        pytest.param(
            (
                WorkUnit("a", NodeKind.CODE, (), {}, "s", (), (), RiskRank.R0),
                WorkUnit("s", NodeKind.SPLITTER, ("a",), {"i": ""}, "s", (), (), RiskRank.R0),
            ),
            (Edge("a", "out", "s", "i"),),
            "SPLITTER_HAS_DEPENDENCY:s",
            id="splitter-has-dependency",
        ),
        pytest.param(
            (WorkUnit("g", NodeKind.GATE, (), {}, None, (), (), RiskRank.R0),),
            (),
            "GATE_WITHOUT_INPUT:g",
            id="gate-without-input",
        ),
        pytest.param(
            (WorkUnit("c", NodeKind.CODE, (), {}, None, (), (), RiskRank.R0),),
            (),
            "MISSING_OUTPUT_SCHEMA:c",
            id="missing-output-schema-code",
        ),
        pytest.param(
            (WorkUnit("w", NodeKind.WORKER, (), {}, None, ("a/",), (), RiskRank.R1),),
            (),
            "MISSING_OUTPUT_SCHEMA:w",
            id="missing-output-schema-worker",
        ),
        pytest.param(
            (WorkUnit("w", NodeKind.WORKER, (), {}, "s", (), (), RiskRank.R1),),
            (),
            "EMPTY_WRITE_ALLOWLIST:w",
            id="empty-write-allowlist",
        ),
    ],
)
def test_build_rejects_invalid_graph_with_code(
    nodes: tuple[WorkUnit, ...], edges: tuple[Edge, ...], expected: str
) -> None:
    with pytest.raises(GraphError) as excinfo:
        WorkflowGraph.build(nodes, edges)

    assert expected in excinfo.value.codes


def test_build_reports_all_errors_at_once() -> None:
    nodes = (
        WorkUnit("w", NodeKind.WORKER, ("ghost",), {"i": ""}, None, (), (), RiskRank.R1),
        WorkUnit("g", NodeKind.GATE, (), {}, None, (), (), RiskRank.R0),
    )

    with pytest.raises(GraphError) as excinfo:
        WorkflowGraph.build(nodes, ())

    assert set(excinfo.value.codes) >= {
        "UNKNOWN_DEPENDENCY:w->ghost",
        "UNBOUND_INPUT:w.i",
        "MISSING_OUTPUT_SCHEMA:w",
        "EMPTY_WRITE_ALLOWLIST:w",
        "GATE_WITHOUT_INPUT:g",
    }
