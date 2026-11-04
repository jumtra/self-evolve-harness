from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    name: str
    price: int
    qty: int
