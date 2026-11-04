import json
import pathlib

from app import greet

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_greet_includes_name():
    assert greet("Ann") == "Hello, Ann!"


def test_protected_policy_file_exists():
    data = json.loads((ROOT / "policy" / "protected.json").read_text())
    assert "policy/protected.json" in data["protected"]
