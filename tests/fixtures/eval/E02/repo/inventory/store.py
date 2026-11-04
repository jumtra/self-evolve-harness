from inventory.models import Item


class Store:
    def __init__(self):
        self._items = []

    def add(self, item: Item) -> None:
        self._items.append(item)

    def items(self):
        return list(self._items)
