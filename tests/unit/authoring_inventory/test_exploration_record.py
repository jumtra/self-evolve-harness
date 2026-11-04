from pathlib import Path

from seh.authoring.inventory import (
    InventoryDecision,
    InventoryItem,
    Match,
    Placement,
    exploration_record,
)


def test_exploration_record_has_authoring_record_shape(tmp_path: Path) -> None:
    item = InventoryItem(
        kind="skill", name="work", source=".claude/skills/work/SKILL.md", description="d"
    )
    decision = InventoryDecision(
        placement=Placement.MODIFY_EXISTING,
        matches=(Match(item=item, score=0.8),),
        reasons=("EXISTING_ALTERNATIVE:skill:work",),
        evidence_refs=("file:.claude/skills/work/SKILL.md",),
    )

    record = exploration_record(decision, tmp_path)

    assert record == {
        "related_existing_modules": [".claude/skills/work/SKILL.md"],
        "reuse_decision": "modify_existing",
        "evidence_refs": ["file:.claude/skills/work/SKILL.md"],
    }
