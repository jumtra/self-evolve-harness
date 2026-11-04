import hashlib
from pathlib import Path

from seh.contracts import HostId
from seh.init.apply import apply_init
from seh.init.planner import InitOptions, plan_init
from seh.ownership import OwnershipManifest
from seh.spec_loader import load_spec
from seh.sync import apply_sync, plan_sync


def test_apply_init_records_spec_files_as_init_generated_and_sync_keeps_them(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = tmp_path / "spec"
    repo.mkdir()
    (source / "instructions").mkdir(parents=True)
    (source / "instructions" / "core.md").write_text("共通方針\n", encoding="utf-8")
    plan = plan_init(repo, InitOptions(hosts=(HostId.CLAUDE,), spec_source=source))

    apply_init(repo, plan, seh_version="2.0.0", cli_versions={})
    after_init = OwnershipManifest.load(repo).get(".harness/spec/instructions/core.md")
    resync = plan_sync(repo, [HostId.CLAUDE], spec=load_spec(repo / ".harness" / "spec"))
    apply_sync(repo, resync, seh_version="2.0.0", cli_versions={})
    after_sync = OwnershipManifest.load(repo).get(".harness/spec/instructions/core.md")

    expected_sha = hashlib.sha256(b"\xe5\x85\xb1\xe9\x80\x9a\xe6\x96\xb9\xe9\x87\x9d\n").hexdigest()
    assert after_init is not None, "init が spec を ownership に記録していない"
    assert after_init.generator == "init"
    assert after_init.sha256 == expected_sha
    assert after_sync == after_init, "sync の manifest 更新で init 記録が変わった／消えた"
