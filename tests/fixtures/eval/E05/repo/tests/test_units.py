import importlib

import pytest

CASES = {
    "unit_a": (4, 5),
    "unit_b": (4, 8),
    "unit_c": (4, 16),
    "unit_d": (4, -4),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_unit_returns_expected_value(name):
    given, expected = CASES[name]
    assert importlib.import_module(f"units.{name}").run(given) == expected
