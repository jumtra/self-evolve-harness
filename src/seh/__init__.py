from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("self-evolve-harness")
except PackageNotFoundError:
    __version__ = "0+unknown"
