import pytest

from seh.globs import glob_to_regex, match_path, outside_allowlist


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        pytest.param("src/a.py", "src/*.py", True, id="star-matches-same-dir"),
        pytest.param("src/x/a.py", "src/*.py", False, id="star-does-not-cross-slash"),
        pytest.param("src/a.py", "src/**", True, id="doublestar-matches-direct-child"),
        pytest.param("src/x/a.py", "src/**", True, id="doublestar-matches-nested"),
        pytest.param("src/test_a.py", "src/**/test_*.py", True, id="slash-doublestar-zero-dirs"),
        pytest.param("src/x/y/test_a.py", "src/**/test_*.py", True, id="slash-doublestar-many"),
        pytest.param("src/x/a.py", "src/**/test_*.py", False, id="slash-doublestar-name-mismatch"),
        pytest.param("src/a.py", "src/?.py", True, id="question-matches-one-char"),
        pytest.param("src/ab.py", "src/?.py", False, id="question-needs-exactly-one"),
        pytest.param("src//.py", "src/?.py", False, id="question-does-not-match-slash"),
        pytest.param("src/a.py", "src/[ab].py", True, id="class-matches-member"),
        pytest.param("src/c.py", "src/[ab].py", False, id="class-rejects-nonmember"),
        pytest.param("src/a.py", "src/a.py", True, id="literal-exact"),
        pytest.param("src/axpy", "src/a.py", False, id="dot-is-escaped"),
        pytest.param("src/a.py.bak", "src/*.py", False, id="whole-path-must-match"),
    ],
)
def test_match_path_applies_glob_rule(path: str, pattern: str, expected: bool):
    assert match_path(path, pattern) is expected


def test_glob_to_regex_returns_compiled_pattern_matching_whole_path():
    regex = glob_to_regex("docs/**")

    assert regex.fullmatch("docs/a/b.md") is not None


@pytest.mark.parametrize(
    ("paths", "allowlist", "expected"),
    [
        pytest.param(["../x.py"], ["**"], ("../x.py",), id="parent-traversal-always-outside"),
        pytest.param(["a/../x.py"], ["**"], ("a/../x.py",), id="embedded-traversal-outside"),
        pytest.param([".git/config"], ["**"], (".git/config",), id="git-dir-always-outside"),
        pytest.param(["sub/.git/hooks"], ["**"], ("sub/.git/hooks",), id="nested-git-outside"),
        pytest.param(["/etc/passwd"], ["**"], ("/etc/passwd",), id="absolute-always-outside"),
        pytest.param(["a.py"], [], ("a.py",), id="empty-allowlist-all-outside"),
        pytest.param(
            ["src/b.py", "docs/a.md", "src/a.py"],
            ["src/*.py"],
            ("docs/a.md",),
            id="inside-paths-excluded",
        ),
        pytest.param(
            ["z.txt", "a.txt", "z.txt"], ["src/*"], ("a.txt", "z.txt"), id="sorted-and-deduped"
        ),
    ],
)
def test_outside_allowlist_returns_sorted_violations(
    paths: list[str], allowlist: list[str], expected: tuple[str, ...]
):
    assert outside_allowlist(paths, allowlist) == expected
