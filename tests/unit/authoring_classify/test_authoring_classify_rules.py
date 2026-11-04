from seh.authoring.classify import (
    Classification,
    FileChange,
    TargetKind,
    classify_change,
    classify_changes,
    overall_risk,
)
from seh.contracts import AuthoringRisk


def test_typo_only_body_change_in_skill_is_text_only() -> None:
    before = (
        "---\nname: work\ndescription: 開発依頼で使う\n---\n"
        "Run the full test suite before reporting completion to the user.\n"
        "Never claim success without attaching the command output as evidence.\n"
    )
    after = (
        "---\nname: work\ndescription: 開発依頼で使う\n---\n"
        "Run the full test suite befor reporting completion to the user.\n"
        "Never claim success without attaching the command output as evidence.\n"
    )

    result = classify_change(FileChange(".claude/skills/work/SKILL.md", before, after))

    assert result is not None
    assert result.kind is TargetKind.SKILL
    assert result.risk is AuthoringRisk.TEXT_ONLY
    assert result.reasons == ("BODY_TYPO_ONLY",)


def test_whitespace_and_newline_only_change_is_text_only() -> None:
    before = "---\nname: work\n---\nStep one.\nStep two.\n"
    after = "---\nname: work\n---\n\nStep one.\n\n\nStep   two.\n"

    result = classify_change(FileChange(".claude/skills/work/SKILL.md", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.TEXT_ONLY
    assert result.reasons == ("BODY_WHITESPACE_OR_PUNCTUATION_ONLY",)


def test_punctuation_and_fullwidth_change_is_text_only() -> None:
    before = "---\nname: work\n---\nテストを実行してください。ＡＢＣ を確認\n"
    after = "---\nname: work\n---\nテストを実行してください ABC を確認\n"

    result = classify_change(FileChange(".claude/skills/work/SKILL.md", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.TEXT_ONLY


def test_flag_dash_removal_is_not_treated_as_punctuation_noise() -> None:
    before = "---\nname: work\n---\nRun git push --force only when the user asks explicitly.\n"
    after = "---\nname: work\n---\nRun git push force only when the user asks explicitly.\n"

    result = classify_change(FileChange(".claude/skills/work/SKILL.md", before, after))

    assert result is not None
    assert result.risk is not AuthoringRisk.TEXT_ONLY


def test_description_change_is_behavioral() -> None:
    before = "---\nname: work\ndescription: 開発依頼で使う\n---\n本文\n"
    after = "---\nname: work\ndescription: 何でも依頼で使う\n---\n本文\n"

    result = classify_change(FileChange(".claude/skills/work/SKILL.md", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.BEHAVIORAL
    assert "FRONTMATTER_KEY_CHANGED:description" in result.reasons


def test_allowed_tools_addition_is_high_risk() -> None:
    before = "---\nname: work\ndescription: d\n---\n本文\n"
    after = "---\nname: work\ndescription: d\nallowed-tools: Bash(*)\n---\n本文\n"

    result = classify_change(FileChange(".claude/skills/work/SKILL.md", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.HIGH_RISK
    assert "FRONTMATTER_KEY_CHANGED:allowed-tools" in result.reasons


def test_permission_change_with_typo_fix_is_not_text_only() -> None:
    before = (
        "---\nname: w\ntools: Read\n---\n"
        "Run the full test suite before reporting completion to the user.\n"
        "Never claim success without attaching the command output as evidence.\n"
    )
    after = (
        "---\nname: w\ntools: Read, Bash\n---\n"
        "Run the full test suite befor reporting completion to the user.\n"
        "Never claim success without attaching the command output as evidence.\n"
    )

    result = classify_change(FileChange(".claude/agents/w.md", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.HIGH_RISK


def test_meaningful_skill_body_change_is_behavioral() -> None:
    before = "---\nname: work\n---\nRun the tests.\n"
    after = "---\nname: work\n---\nRun the tests and then deploy to production immediately.\n"

    result = classify_change(FileChange(".claude/skills/work/SKILL.md", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.BEHAVIORAL
    assert result.reasons == ("BODY_CHANGED",)


def test_edit_larger_than_twenty_characters_in_long_body_is_behavioral() -> None:
    sentence = "This sentence is a stable filler line for the skill. "
    before = "---\nname: w\n---\n" + sentence * 40 + "\n"
    after = "---\nname: w\n---\n" + sentence * 40 + "Also push to main without review.\n"

    result = classify_change(FileChange(".claude/skills/w/SKILL.md", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.BEHAVIORAL


def test_unparseable_frontmatter_is_high_risk() -> None:
    before = "---\nname: work\n---\n本文\n"
    after = "---\nname: [unclosed\n---\n本文\n"

    result = classify_change(FileChange(".claude/skills/work/SKILL.md", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.HIGH_RISK
    assert result.reasons == ("FRONTMATTER_UNPARSEABLE",)


def test_unterminated_frontmatter_is_high_risk() -> None:
    before = "---\nname: work\n---\n本文\n"
    after = "---\nname: work\n本文\n"

    result = classify_change(FileChange(".claude/skills/work/SKILL.md", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.HIGH_RISK


def test_file_deletion_is_high_risk() -> None:
    result = classify_change(
        FileChange(".claude/skills/work/SKILL.md", "---\nname: work\n---\n本文\n", None)
    )

    assert result is not None
    assert result.risk is AuthoringRisk.HIGH_RISK
    assert result.reasons == ("FILE_DELETED",)


def test_root_claude_md_typo_is_still_high_risk() -> None:
    before = "# Rules\nAlways write tests first for every change in this repository.\n"
    after = "# Rules\nAlways write tests first for every change in this repositry.\n"

    result = classify_change(FileChange("CLAUDE.md", before, after))

    assert result is not None
    assert result.kind is TargetKind.INSTRUCTIONS
    assert result.risk is AuthoringRisk.HIGH_RISK
    assert result.reasons == ("SHARED_INSTRUCTIONS_CHANGED",)


def test_root_agents_md_and_spec_instructions_are_high_risk() -> None:
    agents = classify_change(FileChange("AGENTS.md", "a\n", "b\n"))
    spec = classify_change(FileChange(".harness/spec/instructions/core.md", "a\n", "b\n"))

    assert agents is not None
    assert agents.risk is AuthoringRisk.HIGH_RISK
    assert spec is not None
    assert spec.risk is AuthoringRisk.HIGH_RISK


def test_nested_claude_md_meaningful_change_is_behavioral() -> None:
    before = "# API\nUse REST.\n"
    after = "# API\nUse REST and always call the billing service first.\n"

    result = classify_change(FileChange("docs/api/CLAUDE.md", before, after))

    assert result is not None
    assert result.kind is TargetKind.INSTRUCTIONS
    assert result.risk is AuthoringRisk.BEHAVIORAL


def test_settings_hooks_change_is_high_risk() -> None:
    before = '{"hooks": {}}'
    after = '{"hooks": {"PreToolUse": [{"command": "x"}]}}'

    result = classify_change(FileChange(".claude/settings.json", before, after))

    assert result is not None
    assert result.kind is TargetKind.PERMISSIONS
    assert result.risk is AuthoringRisk.HIGH_RISK
    assert "JSON_KEY_CHANGED:hooks" in result.reasons


def test_settings_permissions_change_is_high_risk() -> None:
    before = '{"permissions": {"allow": ["Read"]}}'
    after = '{"permissions": {"allow": ["Read", "Bash(*)"]}}'

    result = classify_change(FileChange(".claude/settings.json", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.HIGH_RISK


def test_settings_unrelated_key_change_is_behavioral() -> None:
    before = '{"model": "a"}'
    after = '{"model": "b"}'

    result = classify_change(FileChange(".claude/settings.json", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.BEHAVIORAL


def test_settings_unparseable_json_is_high_risk() -> None:
    result = classify_change(FileChange(".claude/settings.json", '{"a": 1}', '{"a": '))

    assert result is not None
    assert result.risk is AuthoringRisk.HIGH_RISK
    assert result.reasons == ("STRUCTURED_UNPARSEABLE",)


def test_rule_paths_change_is_behavioral() -> None:
    before = "---\npaths:\n  - src/**\n---\n規約\n"
    after = "---\npaths:\n  - src/**\n  - tests/**\n---\n規約\n"

    result = classify_change(FileChange(".claude/rules/coding.md", before, after))

    assert result is not None
    assert result.kind is TargetKind.RULE
    assert result.risk is AuthoringRisk.BEHAVIORAL


def test_new_skill_and_rule_files_are_behavioral() -> None:
    skill = classify_change(
        FileChange(".agents/skills/new/SKILL.md", None, "---\nname: new\n---\n本文\n")
    )
    rule = classify_change(FileChange(".agents/rules/r.md", None, "規約\n"))

    assert skill is not None
    assert skill.risk is AuthoringRisk.BEHAVIORAL
    assert skill.reasons == ("NEW_FILE",)
    assert rule is not None
    assert rule.risk is AuthoringRisk.BEHAVIORAL


def test_new_skill_with_allowed_tools_is_high_risk() -> None:
    result = classify_change(
        FileChange(
            ".claude/skills/new/SKILL.md",
            None,
            "---\nname: new\nallowed-tools: Bash(*)\n---\n本文\n",
        )
    )

    assert result is not None
    assert result.risk is AuthoringRisk.HIGH_RISK


def test_new_agent_file_is_high_risk() -> None:
    result = classify_change(
        FileChange(".opencode/agents/reviewer.md", None, "---\ndescription: d\n---\n本文\n")
    )

    assert result is not None
    assert result.kind is TargetKind.AGENT
    assert result.risk is AuthoringRisk.HIGH_RISK
    assert "NEW_AGENT_FILE" in result.reasons


def test_opencode_agent_permission_change_is_high_risk() -> None:
    before = "---\ndescription: d\npermission:\n  bash: deny\n---\n本文\n"
    after = "---\ndescription: d\npermission:\n  bash: allow\n---\n本文\n"

    result = classify_change(FileChange(".opencode/agents/reviewer.md", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.HIGH_RISK


def test_agent_permission_mode_change_is_high_risk() -> None:
    before = "---\nname: a\npermissionMode: default\n---\n本文\n"
    after = "---\nname: a\npermissionMode: bypassPermissions\n---\n本文\n"

    result = classify_change(FileChange(".claude/agents/a.md", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.HIGH_RISK


def test_codex_agent_sandbox_change_is_high_risk() -> None:
    before = 'name = "x"\nsandbox_mode = "read-only"\n'
    after = 'name = "x"\nsandbox_mode = "workspace-write"\n'

    result = classify_change(FileChange(".codex/agents/x.toml", before, after))

    assert result is not None
    assert result.kind is TargetKind.AGENT
    assert result.risk is AuthoringRisk.HIGH_RISK
    assert "TOML_KEY_CHANGED:sandbox_mode" in result.reasons


def test_codex_agent_instruction_change_is_behavioral() -> None:
    before = 'name = "x"\ndeveloper_instructions = "Be brief."\n'
    after = 'name = "x"\ndeveloper_instructions = "Be verbose."\n'

    result = classify_change(FileChange(".codex/agents/x.toml", before, after))

    assert result is not None
    assert result.risk is AuthoringRisk.BEHAVIORAL


def test_codex_rules_and_hooks_and_plugins_are_high_risk() -> None:
    rules = classify_change(FileChange(".codex/rules/default.rules", "a", "b"))
    hooks = classify_change(FileChange(".codex/hooks.json", "{}", '{"x": 1}'))
    agy_hooks = classify_change(FileChange(".agents/hooks.json", "{}", '{"x": 1}'))
    plugin = classify_change(FileChange(".opencode/plugins/guard.ts", "a", "b"))

    assert [c.risk if c else None for c in (rules, hooks, agy_hooks, plugin)] == [
        AuthoringRisk.HIGH_RISK
    ] * 4
    assert plugin is not None
    assert plugin.kind is TargetKind.HOOK


def test_unmonitored_paths_return_none() -> None:
    assert classify_change(FileChange("src/app.py", "a", "b")) is None
    assert classify_change(FileChange("README.md", "a", "b")) is None
    assert classify_change(FileChange(".claude/worktrees/x.md", "a", "b")) is None


def test_prompt_file_change_is_behavioral() -> None:
    result = classify_change(
        FileChange(
            ".harness/prompts/summarize.md", "Summarize briefly.\n", "Summarize in French.\n"
        )
    )

    assert result is not None
    assert result.kind is TargetKind.PROMPT
    assert result.risk is AuthoringRisk.BEHAVIORAL


def test_overall_risk_is_maximum_and_none_for_empty() -> None:
    classes = classify_changes(
        [
            FileChange("src/app.py", "a", "b"),
            FileChange(".claude/rules/r.md", "規約\n", "規約を変更\n"),
            FileChange("CLAUDE.md", "a\n", "b\n"),
        ]
    )

    assert len(classes) == 2
    assert all(isinstance(c, Classification) for c in classes)
    assert overall_risk(classes) is AuthoringRisk.HIGH_RISK
    assert overall_risk([]) is None
