from datetime import UTC, datetime

import pytest

from seh.knowledge import (
    VerifiedConstraint,
    append_constraint,
    constraints_for,
    load_constraints,
    retire_constraint,
)

NOW = datetime(2026, 11, 4, tzinfo=UTC)


def test_append_then_load_roundtrip(tmp_path):
    c = VerifiedConstraint(
        id="c1",
        statement="Do not edit generated files",
        scope_globs=("gen/**",),
        source_record="rec1",
        evidence_refs=("ev1",),
        created_at="2026-11-01T00:00:00+00:00",
        expires_at=None,
        status="active",
    )

    append_constraint(tmp_path, c)

    assert load_constraints(tmp_path, now=NOW) == [c]


def test_append_rejects_duplicate_id(tmp_path):
    c = VerifiedConstraint("c1", "s", ("**",), "r", (), "2026-11-01T00:00:00+00:00", None, "active")
    append_constraint(tmp_path, c)

    with pytest.raises(ValueError):
        append_constraint(tmp_path, c)


def test_append_rejects_secret_statement(tmp_path):
    secret = "pass" + "word=" + "hunter2hunter2"
    c = VerifiedConstraint(
        "c1", secret, ("**",), "r", (), "2026-11-01T00:00:00+00:00", None, "active"
    )

    with pytest.raises(ValueError):
        append_constraint(tmp_path, c)


def test_load_excludes_expired(tmp_path):
    expired = VerifiedConstraint(
        "old", "s", ("**",), "r", (), "2026-01-01T00:00:00+00:00",
        "2026-02-01T00:00:00+00:00", "active",
    )  # fmt: skip
    append_constraint(tmp_path, expired)

    assert load_constraints(tmp_path, now=NOW) == []


def test_retire_hides_by_default_and_include_retired_returns_it(tmp_path):
    c = VerifiedConstraint("c1", "s", ("**",), "r", (), "2026-11-01T00:00:00+00:00", None, "active")
    append_constraint(tmp_path, c)

    retire_constraint(tmp_path, "c1", reason="obsolete")

    assert load_constraints(tmp_path, now=NOW) == []
    retired = load_constraints(tmp_path, include_retired=True, now=NOW)
    assert [x.status for x in retired] == ["retired"]
    assert "obsolete" in (tmp_path / ".harness/knowledge/verified_constraints.jsonl").read_text()


def test_retire_unknown_id_raises(tmp_path):
    with pytest.raises(ValueError):
        retire_constraint(tmp_path, "nope", reason="x")


def test_constraints_for_matches_scope_newest_first(tmp_path):
    older = VerifiedConstraint(
        "a", "old rule", ("src/**",), "r", (), "2026-11-01T00:00:00+00:00", None, "active"
    )
    newer = VerifiedConstraint(
        "b", "new rule", ("src/**",), "r", (), "2026-11-02T00:00:00+00:00", None, "active"
    )
    other = VerifiedConstraint(
        "c", "docs rule", ("docs/**",), "r", (), "2026-11-03T00:00:00+00:00", None, "active"
    )
    for c in (older, newer, other):
        append_constraint(tmp_path, c)

    result = constraints_for(tmp_path, ["src/app.py"], now=NOW)

    assert [c.id for c in result] == ["b", "a"]


def test_constraints_for_respects_item_limit(tmp_path):
    for i in range(3):
        append_constraint(
            tmp_path,
            VerifiedConstraint(
                f"c{i}", "s", ("**",), "r", (), f"2026-11-0{i + 1}T00:00:00+00:00", None, "active"
            ),
        )

    result = constraints_for(tmp_path, ["x.py"], now=NOW, max_items=2)

    assert [c.id for c in result] == ["c2", "c1"]


def test_constraints_for_respects_char_limit(tmp_path):
    for i in range(3):
        append_constraint(
            tmp_path,
            VerifiedConstraint(
                f"c{i}", "x" * 40, ("**",), "r", (), f"2026-11-0{i + 1}T00:00:00+00:00", None,
                "active",
            ),
        )  # fmt: skip

    result = constraints_for(tmp_path, ["x.py"], now=NOW, max_chars=90)

    assert [c.id for c in result] == ["c2", "c1"]


def test_load_ignores_broken_last_line(tmp_path):
    c = VerifiedConstraint("c1", "s", ("**",), "r", (), "2026-11-01T00:00:00+00:00", None, "active")
    append_constraint(tmp_path, c)
    path = tmp_path / ".harness/knowledge/verified_constraints.jsonl"
    path.write_text(path.read_text() + '{"id": "c2", "stat')

    assert load_constraints(tmp_path, now=NOW) == [c]


def test_load_rejects_broken_middle_line(tmp_path):
    c = VerifiedConstraint("c1", "s", ("**",), "r", (), "2026-11-01T00:00:00+00:00", None, "active")
    append_constraint(tmp_path, c)
    path = tmp_path / ".harness/knowledge/verified_constraints.jsonl"
    path.write_text("not json\n" + path.read_text())

    with pytest.raises(ValueError):
        load_constraints(tmp_path, now=NOW)
