import pytest

from providers import registry

NAMES = ["none", "codegraph", "graphify"]


@pytest.mark.parametrize("name", NAMES)
def test_every_provider_exposes_the_same_api(name):
    provider = registry.get(name)
    assert callable(provider.find_symbol) and callable(provider.callers)


def test_none_provider_reports_unsupported_for_callers():
    assert registry.get("none").callers("x")["status"] == "UNSUPPORTED"


def test_graphify_callers_is_unsupported_not_an_exception():
    assert registry.get("graphify").callers("x")["status"] == "UNSUPPORTED"


def test_codegraph_callers_is_ok():
    assert registry.get("codegraph").callers("x")["status"] == "OK"
