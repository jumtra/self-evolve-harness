import inspect
import json
import pathlib

import report

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_public_signature_matches_snapshot():
    snapshot = json.loads((ROOT / "api_snapshot.json").read_text())
    assert str(inspect.signature(report.render)) == snapshot["render"]


def test_render_output_is_unchanged():
    rows = [{"name": "apple", "qty": 3}, {"name": "a-very-long-name", "qty": -2}]
    expected = "\n".join([
        "NAME          QTY",
        "-----------------",
        "apple           3",
        "a-very-long~    0",
        "-----------------",
        "TOTAL           3",
    ])
    assert report.render(rows) == expected


def test_row_formatting_is_extracted():
    assert hasattr(report, "_format_row")


def test_render_body_is_short():
    body = inspect.getsource(report.render).splitlines()
    assert len(body) < 15
