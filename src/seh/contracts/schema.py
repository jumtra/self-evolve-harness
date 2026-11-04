from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any, cast

from jsonschema import Draft202012Validator


class SchemaError(ValueError):
    pass


@cache
def _load(name: str) -> str:
    try:
        return resources.files("seh.schemas").joinpath(f"{name}.json").read_text("utf-8")
    except FileNotFoundError as e:
        raise SchemaError(f"unknown schema: {name}") from e


def load_schema(name: str) -> dict[str, object]:
    return json.loads(_load(name))


def validate(name: str, data: object) -> None:
    validator = Draft202012Validator(load_schema(name))
    errors = sorted(validator.iter_errors(cast("Any", data)), key=lambda e: list(e.absolute_path))
    if errors:
        details = "; ".join(
            f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors
        )
        raise SchemaError(f"{name}: {details}")
