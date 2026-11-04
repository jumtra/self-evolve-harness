import pytest
from shipping import fee


@pytest.mark.parametrize("weight, expected", [
    (1, 300), (500, 300), (501, 500), (1000, 500), (1001, 800),
    (2000, 800), (2001, 900), (3000, 900), (3001, 1000),
])
def test_fee_at_boundaries(weight, expected):
    assert fee(weight) == expected


@pytest.mark.parametrize("weight", [0, -1])
def test_non_positive_weight_is_rejected(weight):
    with pytest.raises(ValueError):
        fee(weight)
