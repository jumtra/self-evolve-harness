from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from seh.contracts.task import Edge, NodeKind, WorkUnit

_EXTERNAL_PREFIX = "artifact://"


class GraphError(Exception):
    def __init__(self, codes: Iterable[str]) -> None:
        self.codes: tuple[str, ...] = tuple(codes)
        super().__init__(", ".join(self.codes))


def _check_nodes(nodes: tuple[WorkUnit, ...]) -> list[str]:
    codes: list[str] = []
    for node_id, count in Counter(n.node_id for n in nodes).items():
        if count > 1:
            codes.append(f"DUPLICATE_NODE:{node_id}")
    return codes


def _check_dependencies(nodes: tuple[WorkUnit, ...], edges: tuple[Edge, ...]) -> list[str]:
    known = {n.node_id for n in nodes}
    codes = [f"UNKNOWN_EDGE_NODE:{i}" for i in _unknown_edge_nodes(edges, known)]
    for node in nodes:
        declared = set(node.depends_on)
        # 表示順だけの依存を拒否するため、依存集合は入力エッジの元ノード集合と厳密一致させる
        from_edges = {
            e.from_node for e in edges if e.to_node == node.node_id and e.from_node in known
        }
        codes += [f"UNKNOWN_DEPENDENCY:{node.node_id}->{d}" for d in sorted(declared - known)]
        codes += [
            f"UNNECESSARY_DEPENDENCY:{node.node_id}->{d}"
            for d in sorted((declared & known) - from_edges)
        ]
        codes += [f"MISSING_DEPENDENCY:{node.node_id}->{d}" for d in sorted(from_edges - declared)]
    return codes


def _unknown_edge_nodes(edges: tuple[Edge, ...], known: set[str]) -> list[str]:
    unknown = {n for e in edges for n in (e.from_node, e.to_node) if n not in known}
    return sorted(unknown)


def _check_bindings(nodes: tuple[WorkUnit, ...], edges: tuple[Edge, ...]) -> list[str]:
    codes: list[str] = []
    for node in nodes:
        bound = Counter(e.to_input for e in edges if e.to_node == node.node_id)
        for name in sorted(bound):
            if name not in node.inputs:
                codes.append(f"UNKNOWN_INPUT:{node.node_id}.{name}")
            elif bound[name] > 1:
                codes.append(f"DUPLICATE_BINDING:{node.node_id}.{name}")
        for name, value in sorted(node.inputs.items()):
            if name not in bound and not value.startswith(_EXTERNAL_PREFIX):
                codes.append(f"UNBOUND_INPUT:{node.node_id}.{name}")
    return codes


def _check_cycles(nodes: tuple[WorkUnit, ...], edges: tuple[Edge, ...]) -> list[str]:
    known = {n.node_id for n in nodes}
    succ: dict[str, list[str]] = {n: [] for n in sorted(known)}
    for e in sorted(edges, key=lambda x: (x.from_node, x.to_node)):
        if e.from_node in known and e.to_node in known:
            succ[e.from_node].append(e.to_node)

    codes: list[str] = []
    done: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in stack:
            cycle = [*stack[stack.index(node) :], node]
            codes.append("CYCLE:" + "->".join(cycle))
            return
        if node in done:
            return
        for nxt in succ[node]:
            visit(nxt, [*stack, node])
        done.add(node)

    for start in succ:
        visit(start, [])
    return codes


def _check_kinds(nodes: tuple[WorkUnit, ...], edges: tuple[Edge, ...]) -> list[str]:
    codes: list[str] = []
    incoming = {e.to_node for e in edges}
    for n in nodes:
        if n.kind is NodeKind.SPLITTER and n.depends_on:
            codes.append(f"SPLITTER_HAS_DEPENDENCY:{n.node_id}")
        if n.kind is NodeKind.GATE and n.node_id not in incoming:
            codes.append(f"GATE_WITHOUT_INPUT:{n.node_id}")
        if n.kind in (NodeKind.WORKER, NodeKind.CODE) and not n.outputs_schema:
            codes.append(f"MISSING_OUTPUT_SCHEMA:{n.node_id}")
        if n.kind is NodeKind.WORKER and not n.write_allowlist:
            codes.append(f"EMPTY_WRITE_ALLOWLIST:{n.node_id}")
    return codes


@dataclass(frozen=True)
class WorkflowGraph:
    nodes: tuple[WorkUnit, ...]
    edges: tuple[Edge, ...]

    @classmethod
    def build(cls, nodes: Iterable[WorkUnit], edges: Iterable[Edge]) -> WorkflowGraph:
        node_t, edge_t = tuple(nodes), tuple(edges)
        codes = [
            *_check_nodes(node_t),
            *_check_dependencies(node_t, edge_t),
            *_check_bindings(node_t, edge_t),
            *_check_cycles(node_t, edge_t),
            *_check_kinds(node_t, edge_t),
        ]
        if codes:
            raise GraphError(codes)
        return cls(node_t, edge_t)

    def _deps(self, node_id: str) -> frozenset[str]:
        return frozenset(e.from_node for e in self.edges if e.to_node == node_id)

    def topological_layers(self) -> tuple[tuple[str, ...], ...]:
        remaining = {n.node_id for n in self.nodes}
        placed: set[str] = set()
        layers: list[tuple[str, ...]] = []
        while remaining:
            layer = tuple(sorted(n for n in remaining if self._deps(n) <= placed))
            layers.append(layer)
            placed.update(layer)
            remaining.difference_update(layer)
        return tuple(layers)

    def ready(self, completed: Collection[str], running: Collection[str] = ()) -> tuple[str, ...]:
        done, busy = set(completed), set(running)
        return tuple(
            sorted(
                n.node_id
                for n in self.nodes
                if n.node_id not in done and n.node_id not in busy and self._deps(n.node_id) <= done
            )
        )

    def downstream(self, node_id: str) -> frozenset[str]:
        found: set[str] = set()
        frontier = [node_id]
        while frontier:
            current = frontier.pop()
            for e in self.edges:
                if e.from_node == current and e.to_node not in found:
                    found.add(e.to_node)
                    frontier.append(e.to_node)
        return frozenset(found)
