import hashlib
import json
import pathlib
import shutil

import migrate as m

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORK = "dot_claude/skills/work/SKILL.md.fixture"
REVIEW = "dot_claude/skills/review/SKILL.md.fixture"


def snapshot(base):
    return {
        str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(pathlib.Path(base).rglob("*"))
        if p.is_file() and ".seh-backup" not in p.parts
    }


def prepare(tmp_path):
    target = tmp_path / "project"
    shutil.copytree(ROOT / "v1_sample", target)
    manifest = json.loads((ROOT / "v1_manifest.json").read_text())
    return target, ROOT / "v2_templates", manifest


def test_managed_skill_is_replaced_by_v2_template(tmp_path):
    target, templates, manifest = prepare(tmp_path)
    m.migrate(target, templates, manifest)
    assert (target / WORK).read_text() == (templates / WORK).read_text()


def test_unmanaged_same_name_skill_is_preserved(tmp_path):
    target, templates, manifest = prepare(tmp_path)
    before = snapshot(target)
    m.migrate(target, templates, manifest)
    after = snapshot(target)
    assert after[REVIEW] == before[REVIEW]
    assert after["notes/team.md"] == before["notes/team.md"]


def test_rollback_restores_every_file(tmp_path):
    target, templates, manifest = prepare(tmp_path)
    before = snapshot(target)
    m.migrate(target, templates, manifest)
    m.rollback(target)
    assert snapshot(target) == before
