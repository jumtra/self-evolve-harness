from pathlib import Path

from seh.authoring.gate import is_initial_generation
from seh.contracts import HostId
from seh.init.apply import apply_init
from seh.init.planner import InitOptions, plan_init


def test_untouched_spec_file_after_init_is_initial_generation_and_edit_is_not(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = tmp_path / "spec"
    repo.mkdir()
    (source / "instructions").mkdir(parents=True)
    (source / "instructions" / "core.md").write_text("共通方針\n", encoding="utf-8")
    plan = plan_init(repo, InitOptions(hosts=(HostId.CLAUDE,), spec_source=source))
    apply_init(repo, plan, seh_version="2.0.0", cli_versions={})
    spec_path = ".harness/spec/instructions/core.md"

    untouched = is_initial_generation(repo, spec_path)
    (repo / spec_path).write_text("共通方針を変更\n", encoding="utf-8")
    edited = is_initial_generation(repo, spec_path)

    assert untouched is True
    assert edited is False


def test_generated_host_file_is_not_initial_generation_even_if_untouched(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    source = tmp_path / "spec"
    repo.mkdir()
    (source / "instructions").mkdir(parents=True)
    (source / "instructions" / "core.md").write_text("共通方針\n", encoding="utf-8")
    plan = plan_init(repo, InitOptions(hosts=(HostId.CLAUDE,), spec_source=source))
    apply_init(repo, plan, seh_version="2.0.0", cli_versions={})

    result = is_initial_generation(repo, "AGENTS.md")

    assert result is False
