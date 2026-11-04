from inventory.models import Item
from inventory.store import Store


def build_store() -> Store:
    store = Store()
    store.add(Item("pen", 100, 3))
    store.add(Item("book", 500, 2))
    return store


def main(argv):
    if argv == ["list"]:
        for item in build_store().items():
            print(item.name)
        return 0
    return 2
