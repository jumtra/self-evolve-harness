import pytest

from seh.authoring.lint import has_errors, lint_spec
from seh.contracts import (
    AgentSpec,
    CanonicalSpec,
    DiagnosticLevel,
    RuleSpec,
    SkillSpec,
)

GOOD_BODY = """## Goal
目的を書く。

## Inputs
入力を書く。

## Boundaries
やらないこと。

## Output
出力形式。

## Feedback
検証方法。
"""


def test_valid_skill_has_no_diagnostics() -> None:
    spec = CanonicalSpec(
        instructions="共通方針",
        skills=(
            SkillSpec(id="deploy-app", description="Use when deploying the app", body=GOOD_BODY),
        ),
        agents=(),
        rules=(),
    )

    diags = lint_spec(spec)

    assert diags == []
    assert has_errors(diags) is False


def test_japanese_headings_satisfy_contract() -> None:
    body = "## 目的\na\n\n## 入力\nb\n\n## やらないこと\nc\n\n## 出力\nd\n\n## 検証\ne\n"
    spec = CanonicalSpec(
        instructions="",
        skills=(SkillSpec(id="deploy-app", description="デプロイ時に使う", body=body),),
        agents=(),
        rules=(),
    )

    assert lint_spec(spec) == []


@pytest.mark.parametrize(
    ("missing", "body"),
    [
        ("goal", "## Inputs\na\n## Boundaries\nb\n## Output\nc\n## Feedback\nd\n"),
        ("inputs", "## Goal\na\n## Boundaries\nb\n## Output\nc\n## Feedback\nd\n"),
        ("boundaries", "## Goal\na\n## Inputs\nb\n## Output\nc\n## Feedback\nd\n"),
        ("output", "## Goal\na\n## Inputs\nb\n## Boundaries\nc\n## Feedback\nd\n"),
        ("feedback", "## Goal\na\n## Inputs\nb\n## Boundaries\nc\n## Output\nd\n"),
    ],
    ids=["goal", "inputs", "boundaries", "output", "feedback"],
)
def test_missing_contract_section_is_error(missing: str, body: str) -> None:
    spec = CanonicalSpec(
        instructions="",
        skills=(SkillSpec(id="deploy-app", description="Use when deploying", body=body),),
        agents=(),
        rules=(),
    )

    diags = lint_spec(spec)

    assert [d.code for d in diags] == [f"SKILL_CONTRACT_MISSING:{missing}"]
    assert diags[0].level == DiagnosticLevel.ERROR
    assert has_errors(diags) is True


def test_description_without_trigger_is_warning() -> None:
    spec = CanonicalSpec(
        instructions="",
        skills=(SkillSpec(id="deploy-app", description="Deploys the app", body=GOOD_BODY),),
        agents=(),
        rules=(),
    )

    diags = lint_spec(spec)

    assert [(d.level, d.code) for d in diags] == [
        (DiagnosticLevel.WARN, "SKILL_DESCRIPTION_NO_TRIGGER")
    ]
    assert has_errors(diags) is False


@pytest.mark.parametrize(
    "tools",
    ["Bash", "Bash(*)", "Read Write", "Read, Bash"],
    ids=["bare-bash", "bash-star", "bare-write", "bash-in-list"],
)
def test_broad_tool_permission_is_error(tools: str) -> None:
    skill = SkillSpec(
        id="deploy-app",
        description="Use when deploying",
        body=GOOD_BODY,
        claude_frontmatter={"allowed-tools": tools},
    )
    spec = CanonicalSpec(instructions="", skills=(skill,), agents=(), rules=())

    diags = lint_spec(spec)

    assert [d.code for d in diags] == ["SKILL_BROAD_TOOL_PERMISSION"]
    assert diags[0].level == DiagnosticLevel.ERROR


def test_narrow_tool_permission_is_allowed() -> None:
    skill = SkillSpec(
        id="deploy-app",
        description="Use when deploying",
        body=GOOD_BODY,
        claude_frontmatter={"allowed-tools": ["Read", "Bash(git status:*)"]},
    )
    spec = CanonicalSpec(instructions="", skills=(skill,), agents=(), rules=())

    assert lint_spec(spec) == []


def test_unknown_claude_frontmatter_key_is_error() -> None:
    skill = SkillSpec(
        id="deploy-app",
        description="Use when deploying",
        body=GOOD_BODY,
        claude_frontmatter={"bogus-key": 1},
    )
    spec = CanonicalSpec(instructions="", skills=(skill,), agents=(), rules=())

    diags = lint_spec(spec)

    assert [d.code for d in diags] == ["SKILL_UNKNOWN_FRONTMATTER_KEY"]
    assert diags[0].level == DiagnosticLevel.ERROR


def test_duplicate_ids_case_insensitive_is_error() -> None:
    spec = CanonicalSpec(
        instructions="",
        skills=(SkillSpec(id="reviewer", description="Use when reviewing", body=GOOD_BODY),),
        agents=(
            AgentSpec(id="Reviewer", description="d", instructions="x", tools=(), read_only=True),
        ),
        rules=(),
    )

    diags = lint_spec(spec)

    assert [d.code for d in diags] == ["DUPLICATE_ID"]


def test_builtin_name_collision_is_error() -> None:
    spec = CanonicalSpec(
        instructions="",
        skills=(SkillSpec(id="review", description="Use when reviewing", body=GOOD_BODY),),
        agents=(),
        rules=(),
    )

    diags = lint_spec(spec)

    assert [d.code for d in diags] == ["BUILTIN_NAME_COLLISION"]


def test_long_instructions_is_warning() -> None:
    spec = CanonicalSpec(instructions="あ" * 4001, skills=(), agents=(), rules=())

    diags = lint_spec(spec)

    assert [(d.level, d.code) for d in diags] == [(DiagnosticLevel.WARN, "INSTRUCTIONS_TOO_LONG")]


def test_procedure_duplicated_from_skill_into_instructions_is_error() -> None:
    paragraph = (
        "デプロイ手順として、まずビルドを実行し、次にステージング環境へ配布し、"
        "スモークテストを確認してから本番へ昇格させる。失敗した場合は直前のリリースへロールバックし、原因を記録する。"
    )
    spec = CanonicalSpec(
        instructions=f"共通方針\n\n{paragraph}\n",
        skills=(
            SkillSpec(
                id="deploy-app",
                description="Use when deploying",
                body=GOOD_BODY + "\n" + paragraph + "\n",
            ),
        ),
        agents=(),
        rules=(),
    )

    diags = lint_spec(spec)

    assert [(d.level, d.code) for d in diags] == [
        (DiagnosticLevel.ERROR, "DUPLICATED_PROCEDURE:deploy-app")
    ]
    assert "参照" in diags[0].message


def test_procedure_duplicated_from_rule_into_instructions_is_error() -> None:
    paragraph = "x" * 40 + " " + "y" * 60
    spec = CanonicalSpec(
        instructions=paragraph,
        skills=(),
        agents=(),
        rules=(RuleSpec(id="style", description="d", body=f"前置き\n\n{paragraph}", always=True),),
    )

    diags = lint_spec(spec)

    assert [d.code for d in diags] == ["DUPLICATED_PROCEDURE:style"]


def test_short_shared_paragraph_is_not_duplicate() -> None:
    spec = CanonicalSpec(
        instructions="短い段落",
        skills=(
            SkillSpec(
                id="deploy-app", description="Use when deploying", body=GOOD_BODY + "\n短い段落\n"
            ),
        ),
        agents=(),
        rules=(),
    )

    assert lint_spec(spec) == []


def test_long_numbered_procedure_in_instructions_is_warning() -> None:
    steps = "\n".join(f"{i}. 手順{i}" for i in range(1, 17))
    spec = CanonicalSpec(instructions=steps, skills=(), agents=(), rules=())

    diags = lint_spec(spec)

    assert [(d.level, d.code) for d in diags] == [
        (DiagnosticLevel.WARN, "LONG_PROCEDURE_IN_INSTRUCTIONS")
    ]


def test_read_only_agent_with_write_tool_is_error() -> None:
    agent = AgentSpec(
        id="auditor",
        description="d",
        instructions="監査する",
        tools=("Read", "Edit"),
        read_only=True,
    )
    spec = CanonicalSpec(instructions="", skills=(), agents=(agent,), rules=())

    diags = lint_spec(spec)

    assert [d.code for d in diags] == ["READ_ONLY_AGENT_HAS_WRITE_TOOL"]
    assert diags[0].level == DiagnosticLevel.ERROR


def test_agent_with_empty_instructions_is_error() -> None:
    agent = AgentSpec(
        id="auditor", description="d", instructions="  ", tools=("Read",), read_only=True
    )
    spec = CanonicalSpec(instructions="", skills=(), agents=(agent,), rules=())

    diags = lint_spec(spec)

    assert [(d.level, d.code) for d in diags] == [
        (DiagnosticLevel.ERROR, "AGENT_INSTRUCTIONS_EMPTY")
    ]


def test_rule_without_scope_is_warning() -> None:
    rule = RuleSpec(id="style", description="d", body="本文", globs=(), always=False)
    spec = CanonicalSpec(instructions="", skills=(), agents=(), rules=(rule,))

    diags = lint_spec(spec)

    assert [(d.level, d.code) for d in diags] == [(DiagnosticLevel.WARN, "RULE_WITHOUT_SCOPE")]


def test_rule_with_globs_is_clean() -> None:
    rule = RuleSpec(id="style", description="d", body="本文", globs=("src/**",), always=False)
    spec = CanonicalSpec(instructions="", skills=(), agents=(), rules=(rule,))

    assert lint_spec(spec) == []
