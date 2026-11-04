import pytest

from seh.init.templating import InitError, render_template_text, template_spec_dir


def test_replaces_known_variables() -> None:
    text = "# {{project_name}}\nCI: {{ci_check_cmd}}\n"

    rendered = render_template_text(text, {"project_name": "demo", "ci_check_cmd": "make ci"})

    assert rendered == "# demo\nCI: make ci\n"


def test_unknown_variable_raises_init_error() -> None:
    with pytest.raises(InitError, match="unknown_var"):
        render_template_text("{{unknown_var}}", {"project_name": "demo"})


def test_value_is_inserted_verbatim_and_not_expanded_again() -> None:
    rendered = render_template_text(
        "{{ci_fix_cmd}}", {"ci_fix_cmd": "echo '{{project_name}}'", "project_name": "demo"}
    )

    assert rendered == "echo '{{project_name}}'"


def test_template_spec_dir_is_none_or_existing_directory() -> None:
    found = template_spec_dir()

    assert found is None or found.is_dir()
