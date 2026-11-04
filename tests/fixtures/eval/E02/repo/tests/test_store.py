from inventory.models import Item
from inventory.store import Store


def test_total_value_sums_price_times_qty():
    store = Store()
    store.add(Item("a", 10, 2))
    store.add(Item("b", 5, 1))
    assert store.total_value() == 25


def test_total_value_of_empty_store_is_zero():
    assert Store().total_value() == 0
