import pytest
from stats import mean
from textutil import shout


def test_mean_of_three_values():
    assert mean([1, 2, 3]) == 2


def test_mean_of_single_value():
    assert mean([5]) == 5


def test_mean_of_empty_raises():
    with pytest.raises(ValueError):
        mean([])


def test_shout_is_unaffected():
    assert shout("a") == "A!"
