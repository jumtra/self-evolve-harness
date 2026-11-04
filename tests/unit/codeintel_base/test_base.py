import pytest

from seh.contracts.common import Result, ResultStatus
from seh.providers.codeintel.base import CodeIntelError, provider_for, resolve_with_fallback
from seh.providers.codeintel.source_fallback import SourceFallbackProvider


def test_stop_mode_keeps_unsupported_for_affected_tests(tmp_path):
    (tmp_path / "core.py").write_text("def compute():\n    return 1\n")
    provider = SourceFallbackProvider(tmp_path)

    result = resolve_with_fallback(provider, provider, "affected_tests", ["core.py"], mode="stop")

    assert result.status is ResultStatus.UNSUPPORTED


def test_stop_mode_does_not_turn_unsupported_into_empty_ok(tmp_path):
    (tmp_path / "core.py").write_text("def compute():\n    return 1\n")

    class UnsupportedPrimary(SourceFallbackProvider):
        def search_symbols(self, query: str) -> Result:
            return Result(ResultStatus.UNSUPPORTED, message="no symbols")

    primary = UnsupportedPrimary(tmp_path)
    fallback = SourceFallbackProvider(tmp_path)

    result = resolve_with_fallback(primary, fallback, "search_symbols", "compute", mode="stop")

    assert result.status is ResultStatus.UNSUPPORTED
    assert result.data is None


def test_source_mode_uses_fallback_when_primary_is_unsupported(tmp_path):
    (tmp_path / "core.py").write_text("def compute():\n    return 1\n")

    class UnsupportedPrimary(SourceFallbackProvider):
        def search_symbols(self, query: str) -> Result:
            return Result(ResultStatus.UNSUPPORTED, message="no symbols")

    primary = UnsupportedPrimary(tmp_path)
    fallback = SourceFallbackProvider(tmp_path)

    result = resolve_with_fallback(primary, fallback, "search_symbols", "compute", mode="source")

    assert result.status is ResultStatus.OK
    assert "fallback:none" in (result.message or "")


def test_source_mode_without_fallback_keeps_unsupported(tmp_path):
    class UnsupportedPrimary(SourceFallbackProvider):
        def search_symbols(self, query: str) -> Result:
            return Result(ResultStatus.UNSUPPORTED, message="no symbols")

    result = resolve_with_fallback(
        UnsupportedPrimary(tmp_path), None, "search_symbols", "x", mode="source"
    )

    assert result.status is ResultStatus.UNSUPPORTED


def test_primary_error_is_not_hidden_by_fallback(tmp_path):
    (tmp_path / "core.py").write_text("def compute():\n    return 1\n")

    class BrokenPrimary(SourceFallbackProvider):
        def search_symbols(self, query: str) -> Result:
            return Result(ResultStatus.ERROR, message="index corrupted")

    primary = BrokenPrimary(tmp_path)
    fallback = SourceFallbackProvider(tmp_path)

    result = resolve_with_fallback(primary, fallback, "search_symbols", "compute", mode="source")

    assert result.status is ResultStatus.ERROR
    assert result.message == "index corrupted"


def test_provider_for_none_returns_source_fallback(tmp_path):
    provider = provider_for("none", tmp_path)

    assert isinstance(provider, SourceFallbackProvider)


def test_provider_for_unimplemented_provider_raises(tmp_path):
    with pytest.raises(CodeIntelError, match="provider not available"):
        provider_for("codegraph", tmp_path)


def test_provider_for_unknown_name_raises(tmp_path):
    with pytest.raises(CodeIntelError):
        provider_for("nope", tmp_path)
