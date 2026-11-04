from seh.authoring.eval import skill_invoked


def test_claude_skill_tool_use_for_target_is_true() -> None:
    events = [
        {"type": "system", "subtype": "init"},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "調べます"},
                    {"type": "tool_use", "name": "Skill", "input": {"skill": "work"}},
                ]
            },
        },
        {"type": "result", "subtype": "success"},
    ]

    assert skill_invoked("claude", events, "work") is True


def test_claude_skill_name_may_use_command_or_name_key_and_plugin_prefix() -> None:
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "name": "Skill", "input": {"command": "pl:work"}}]
            },
        },
        {"type": "result"},
    ]

    assert skill_invoked("claude", events, "work") is True


def test_claude_without_any_tool_use_but_with_result_is_false() -> None:
    events = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "晴れです"}]}},
        {"type": "result", "subtype": "success"},
    ]

    assert skill_invoked("claude", events, "work") is False


def test_claude_skill_tool_use_for_other_skill_is_false() -> None:
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Skill", "input": {"skill": "harness-init"}}
                ]
            },
        },
        {"type": "result"},
    ]

    assert skill_invoked("claude", events, "work") is False


def test_claude_without_terminal_result_is_undetermined() -> None:
    events = [{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}]

    assert skill_invoked("claude", events, "work") is None


def test_other_hosts_are_unverified_and_never_guessed() -> None:
    events = [
        {"type": "assistant", "message": {"content": []}},
        {"type": "result"},
    ]

    assert skill_invoked("codex", events, "work") is None
    assert skill_invoked("opencode", events, "work") is None
    assert skill_invoked("antigravity", events, "work") is None
