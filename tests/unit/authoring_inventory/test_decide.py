import pytest

from seh.authoring.inventory import (
    InventoryItem,
    Placement,
    Proposal,
    decide,
    similarity,
)

WORK_SKILL = InventoryItem(
    kind="skill",
    name="work",
    source=".claude/skills/work/SKILL.md",
    description="実装依頼を処理する",
)
TESTS_RUN_TOOL = InventoryItem(
    kind="tool",
    name="tests.run",
    source="seh tools",
    description="許可されたコマンドでテストを実行し結果を返す",
)
REVIEWER_AGENT = InventoryItem(
    kind="agent",
    name="reviewer",
    source=".claude/agents/reviewer.md",
    description="変更差分をレビューして指摘を返す独立レビュー担当",
)


def test_one_off_proposal_is_not_needed() -> None:
    proposal = Proposal(
        id="rename-once",
        description="今回だけ変数名を一括で変える",
        trigger_examples=("変数名を変えて",),
        repeated=False,
        deterministic=False,
        always_needed=False,
        needs_isolation=False,
        branching_or_parallel=False,
    )

    decision = decide(proposal, [])

    assert decision.placement is Placement.NOT_NEEDED
    assert "ONE_OFF" in decision.reasons


def test_deterministic_work_goes_to_tool() -> None:
    proposal = Proposal(
        id="count-lines",
        description="ファイルの行数を数える",
        trigger_examples=("行数を数えて",),
        repeated=True,
        deterministic=True,
        always_needed=False,
        needs_isolation=False,
        branching_or_parallel=False,
    )

    decision = decide(proposal, [])

    assert decision.placement is Placement.TOOL
    assert "DETERMINISTIC_WORK" in decision.reasons


def test_always_needed_convention_goes_to_rule() -> None:
    proposal = Proposal(
        id="commit-style",
        description="コミットメッセージは動詞始まりにする",
        trigger_examples=("コミットして",),
        repeated=True,
        deterministic=False,
        always_needed=True,
        needs_isolation=False,
        branching_or_parallel=False,
    )

    decision = decide(proposal, [])

    assert decision.placement is Placement.RULE
    assert "ALWAYS_NEEDED_CONVENTION" in decision.reasons


def test_isolation_without_similar_agent_proposes_agent() -> None:
    proposal = Proposal(
        id="secret-auditor",
        description="資格情報の漏えいを権限分離して監査する",
        trigger_examples=("秘密情報を監査して",),
        repeated=True,
        deterministic=False,
        always_needed=False,
        needs_isolation=True,
        branching_or_parallel=False,
    )

    decision = decide(proposal, [REVIEWER_AGENT])

    assert decision.placement is Placement.AGENT


def test_isolation_with_similar_agent_modifies_existing() -> None:
    proposal = Proposal(
        id="reviewer",
        description="変更差分をレビューして指摘を返す",
        trigger_examples=("差分をレビューして",),
        repeated=True,
        deterministic=False,
        always_needed=False,
        needs_isolation=True,
        branching_or_parallel=False,
    )

    decision = decide(proposal, [REVIEWER_AGENT])

    assert decision.placement is Placement.MODIFY_EXISTING
    assert "file:.claude/agents/reviewer.md" in decision.evidence_refs


def test_branching_work_goes_to_runtime() -> None:
    proposal = Proposal(
        id="retry-pipeline",
        description="失敗したら再試行しつつ並列でビルドする",
        trigger_examples=("並列ビルド",),
        repeated=True,
        deterministic=False,
        always_needed=False,
        needs_isolation=False,
        branching_or_parallel=True,
    )

    decision = decide(proposal, [])

    assert decision.placement is Placement.RUNTIME
    assert "USE_WORKFLOW_RUNTIME" in decision.reasons


def test_similar_skill_is_modified_instead_of_adding_new_one() -> None:
    # A01: 既存 work と似た提案は新規 Skill を増やさない
    proposal = Proposal(
        id="implement-request",
        description="実装依頼を処理する",
        trigger_examples=("実装依頼を処理して",),
        repeated=True,
        deterministic=False,
        always_needed=False,
        needs_isolation=False,
        branching_or_parallel=False,
    )

    decision = decide(proposal, [WORK_SKILL, TESTS_RUN_TOOL])

    assert decision.placement is Placement.MODIFY_EXISTING
    assert decision.matches[0].item.name == "work"
    assert "file:.claude/skills/work/SKILL.md" in decision.evidence_refs


def test_existing_tool_makes_new_skill_not_needed() -> None:
    proposal = Proposal(
        id="run-tests",
        description="許可されたコマンドでテストを実行し結果を返す",
        trigger_examples=("テストを実行する",),
        repeated=True,
        deterministic=False,
        always_needed=False,
        needs_isolation=False,
        branching_or_parallel=False,
    )

    decision = decide(proposal, [WORK_SKILL, TESTS_RUN_TOOL])

    assert decision.placement is Placement.NOT_NEEDED
    assert "EXISTING_ALTERNATIVE:tool:tests.run" in decision.reasons
    assert "tool:tests.run" in decision.evidence_refs


def test_existing_mcp_is_reported_as_alternative() -> None:
    proposal = Proposal(
        id="github",
        description="GitHub の Issue を検索する",
        trigger_examples=("Issue を検索",),
        repeated=True,
        deterministic=False,
        always_needed=False,
        needs_isolation=False,
        branching_or_parallel=False,
    )
    mcp = InventoryItem(kind="mcp", name="github", source=".mcp.json", description="")

    decision = decide(proposal, [mcp])

    assert decision.placement is Placement.NOT_NEEDED
    assert "EXISTING_ALTERNATIVE:mcp:github" in decision.reasons
    assert "mcp:github" in decision.evidence_refs


def test_unrelated_inventory_allows_new_skill() -> None:
    proposal = Proposal(
        id="release-notes",
        description="リリースノートを章立てして下書きする",
        trigger_examples=("リリースノートを作って",),
        repeated=True,
        deterministic=False,
        always_needed=False,
        needs_isolation=False,
        branching_or_parallel=False,
    )

    decision = decide(proposal, [WORK_SKILL, TESTS_RUN_TOOL, REVIEWER_AGENT])

    assert decision.placement is Placement.NEW_SKILL


def test_rules_apply_in_order_one_off_wins_over_deterministic() -> None:
    proposal = Proposal(
        id="x",
        description="一度だけ計算する",
        trigger_examples=(),
        repeated=False,
        deterministic=True,
        always_needed=True,
        needs_isolation=True,
        branching_or_parallel=True,
    )

    decision = decide(proposal, [])

    assert decision.placement is Placement.NOT_NEEDED


def test_matches_are_top5_descending_and_positive_only() -> None:
    proposal = Proposal(
        id="alpha",
        description="alpha beta gamma",
        trigger_examples=(),
        repeated=True,
        deterministic=False,
        always_needed=False,
        needs_isolation=False,
        branching_or_parallel=False,
    )
    inventory = [
        InventoryItem(kind="skill", name=f"s{i}", source=f"p{i}", description="alpha " + "x " * i)
        for i in range(8)
    ] + [InventoryItem(kind="skill", name="zzz", source="pz", description="qqq")]

    decision = decide(proposal, inventory)

    scores = [m.score for m in decision.matches]
    assert len(scores) == 5
    assert scores == sorted(scores, reverse=True)
    assert all(s > 0 for s in scores)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("テストを実行して結果を返す", "テストを実行し結果を返す"),
        ("実装依頼を処理する", "実装依頼を処理する"),
    ],
    ids=["synonymous-short-sentences", "identical"],
)
def test_japanese_similarity_high_for_equivalent_sentences(left: str, right: str) -> None:
    assert similarity(left, right) >= 0.5


def test_japanese_similarity_low_for_unrelated_sentences() -> None:
    assert similarity("テストを実行して結果を返す", "リリースノートを下書きする") < 0.2


def test_english_similarity_uses_words() -> None:
    assert similarity("Run the Tests!", "run tests") == pytest.approx(2 / 3)
