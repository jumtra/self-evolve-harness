from providers.codegraph import CodeGraphProvider
from providers.graphify import GraphifyProvider
from providers.none_provider import NoneProvider

_PROVIDERS = {"none": NoneProvider, "codegraph": CodeGraphProvider, "graphify": GraphifyProvider}


def get(name):
    return _PROVIDERS[name]()
