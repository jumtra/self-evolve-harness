from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath

import yaml

from seh.contracts import CanonicalSpec, ChangeAction, PlannedChange, SkillSpec

MANAGED_BEGIN = "<!-- seh:begin -->"
MANAGED_END = "<!-- seh:end -->"
# sync はこの reason の変更をファイル全体ではなく管理ブロックだけの置換として扱う
MANAGED_BLOCK_REASON = "managed-block"

# Codex / AGY / OpenCode が共通に探索する Skill の置き場所（ADR-0005）
SHARED_SKILLS_DIR = ".agents/skills"


def frontmatter_document(meta: Mapping[str, object], body: str) -> str:
    header = yaml.safe_dump(dict(meta), sort_keys=False, allow_unicode=True)
    return f"---\n{header}---\n\n{body.rstrip()}\n"


def managed_block(text: str) -> str:
    return f"{MANAGED_BEGIN}\n{text.rstrip()}\n{MANAGED_END}\n"


def _reference_path(skill_dir: str, relative: str) -> str:
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"reference path must stay inside the skill dir: {relative!r}")
    return f"{skill_dir}/{rel.as_posix()}"


def skill_changes(
    skill: SkillSpec, *, base_dir: str, meta: Mapping[str, object], owner: str
) -> list[PlannedChange]:
    skill_dir = f"{base_dir}/{skill.id}"
    changes = [
        PlannedChange(
            path=f"{skill_dir}/SKILL.md",
            action=ChangeAction.UPDATE,
            content=frontmatter_document(meta, skill.body).encode(),
            reason="skill",
            owner=owner,
        )
    ]
    for relative, text in skill.references.items():
        changes.append(
            PlannedChange(
                path=_reference_path(skill_dir, relative),
                action=ChangeAction.UPDATE,
                content=f"{text.rstrip()}\n".encode(),
                reason="skill-reference",
                owner=owner,
            )
        )
    return changes


def shared_skill_changes(skill: SkillSpec, *, owner: str) -> list[PlannedChange]:
    # 共有パスは複数ホストが読むため、全ホストが受理する最小 frontmatter に限る（ADR-0001）
    meta = {"name": skill.id, "description": skill.description}
    return skill_changes(skill, base_dir=SHARED_SKILLS_DIR, meta=meta, owner=owner)


def agents_md_change(spec: CanonicalSpec, *, owner: str) -> PlannedChange:
    return PlannedChange(
        path="AGENTS.md",
        action=ChangeAction.UPDATE,
        content=managed_block(spec.instructions).encode(),
        reason=MANAGED_BLOCK_REASON,
        owner=owner,
    )
