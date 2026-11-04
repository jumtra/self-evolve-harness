import pytest

from verdict import final_verdict


@pytest.mark.parametrize("checker, self_eval, expected", [
    ("FAIL", "PASS", "FAIL"),
    ("FAIL", "FAIL", "FAIL"),
    ("PASS", "PASS", "PASS"),
    ("PASS", "FAIL", "PASS"),
    ("FAIL", "UNKNOWN", "FAIL"),
])
def test_checker_alone_decides_final_verdict(checker, self_eval, expected):
    assert final_verdict(checker, self_eval) == expected
