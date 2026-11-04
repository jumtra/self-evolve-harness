from seh.contracts.common import Result, ResultStatus
from seh.init.detect import AppDetection, Commands, DetectionResult
from seh.knowledge import generate_domain_md, read_section, search_domain, sections
from seh.providers.codeintel.base import Symbol
from seh.providers.codeintel.source_fallback import SourceFallbackProvider


class _FakeProvider(SourceFallbackProvider):
    def __init__(self, result: Result) -> None:
        self._result = result

    def search_symbols(self, query: str) -> Result:
        return self._result


def _detection() -> DetectionResult:
    app = AppDetection(
        path=".",
        languages=("python",),
        package_manager="uv",
        task_runner=None,
        commands=Commands(),
        protected_configs=(),
    )
    return DetectionResult(
        root_apps=(app,), ci_files=(), existing_harness=(), existing_symlinks=(), notes=()
    )


def test_generate_without_code_intel_has_all_sections_and_no_symbols(tmp_path):
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "deep").mkdir()

    text = generate_domain_md(tmp_path, _detection())

    assert text.startswith("<!-- 常時読込しない。seh の knowledge API で必要な節だけ取得する -->")
    assert sections(text) == [
        "## プロジェクト概要",
        "## ディレクトリの使い分け",
        "## 主要概念",
        "## データフロー",
        "## Gotchas",
    ]
    assert "python" in text and "uv" in text
    assert "src/pkg" in text
    assert "src/pkg/deep" not in text


def test_generate_does_not_guess_directory_roles(tmp_path):
    (tmp_path / "src").mkdir()

    text = generate_domain_md(tmp_path, _detection())

    assert "| src | （未記入） |" in text


def test_generate_reports_unsupported_code_intel(tmp_path):
    provider = _FakeProvider(Result(ResultStatus.UNSUPPORTED))

    text = generate_domain_md(tmp_path, _detection(), code_intel=provider)

    assert "取得できませんでした（UNSUPPORTED）" in text


def test_generate_lists_symbols_when_code_intel_ok(tmp_path):
    provider = _FakeProvider(
        Result(ResultStatus.OK, (Symbol("compute", "function", "core.py", 3),))
    )

    text = generate_domain_md(tmp_path, _detection(), code_intel=provider)

    assert "## 主要シンボル" in text
    assert "compute" in text and "core.py:3" in text


def test_generate_is_deterministic(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "a").mkdir()

    first = generate_domain_md(tmp_path, _detection())
    second = generate_domain_md(tmp_path, _detection())

    assert first == second


def test_read_section_returns_only_that_section(tmp_path):
    path = tmp_path / ".harness" / "knowledge" / "domain.md"
    path.parent.mkdir(parents=True)
    path.write_text("# T\n\n## A\nalpha\n\n## B\nbeta\n")

    result = read_section(tmp_path, "A")

    assert result is not None
    assert "alpha" in result
    assert "beta" not in result


def test_read_section_returns_none_for_unknown_heading(tmp_path):
    path = tmp_path / ".harness" / "knowledge" / "domain.md"
    path.parent.mkdir(parents=True)
    path.write_text("# T\n\n## A\nalpha\n")

    assert read_section(tmp_path, "Z") is None


def test_read_section_returns_none_when_file_missing(tmp_path):
    assert read_section(tmp_path, "A") is None


def test_search_domain_returns_only_matching_sections(tmp_path):
    path = tmp_path / ".harness" / "knowledge" / "domain.md"
    path.parent.mkdir(parents=True)
    path.write_text("# T\n\n## A\nalpha needle\n\n## B\nbeta\n")

    hits = search_domain(tmp_path, "needle")

    assert [h for h, _ in hits] == ["A"]


def test_search_domain_truncates_to_max_chars(tmp_path):
    path = tmp_path / ".harness" / "knowledge" / "domain.md"
    path.parent.mkdir(parents=True)
    path.write_text("# T\n\n## A\n" + "needle " * 100 + "\n\n## B\n" + "needle " * 100 + "\n")

    hits = search_domain(tmp_path, "needle", max_chars=50)

    assert sum(len(excerpt) for _, excerpt in hits) <= 50
