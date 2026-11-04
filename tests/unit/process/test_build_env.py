from seh.runtime.process import DEFAULT_ENV_ALLOWLIST, build_env


def test_build_env_keeps_only_allowlisted_keys():
    source = {"PATH": "/bin", "HOME": "/h", "OTHER": "x"}

    env = build_env(DEFAULT_ENV_ALLOWLIST, source)

    assert env == {"PATH": "/bin", "HOME": "/h"}


def test_build_env_always_drops_claude_code_keys():
    source = {"PATH": "/bin", "CLAUDECODE": "1", "CLAUDE_CODE_FOO": "x"}

    env = build_env(["PATH", "CLAUDECODE", "CLAUDE_CODE_FOO"], source, {"CLAUDE_CODE_BAR": "y"})

    assert env == {"PATH": "/bin"}


def test_build_env_extra_overrides_source():
    source = {"PATH": "/bin"}

    env = build_env(["PATH"], source, {"PATH": "/custom", "NEW": "1"})

    assert env == {"PATH": "/custom", "NEW": "1"}
