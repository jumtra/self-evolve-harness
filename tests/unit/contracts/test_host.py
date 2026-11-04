import pytest

from seh.contracts import SkillSpec


def test_skill_spec_valid_kebab_id_is_accepted():
    skill = SkillSpec(id="code-review-2", description="レビューする", body="# body")

    assert skill.id == "code-review-2"


@pytest.mark.parametrize(
    "bad_id",
    [
        pytest.param("", id="empty"),
        pytest.param("Code-Review", id="uppercase"),
        pytest.param("code_review", id="underscore"),
        pytest.param("-code", id="leading_hyphen"),
        pytest.param("code-", id="trailing_hyphen"),
        pytest.param("code--review", id="double_hyphen"),
        pytest.param("a" * 65, id="over_64_chars"),
    ],
)
def test_skill_spec_invalid_id_raises_value_error(bad_id):
    with pytest.raises(ValueError):
        SkillSpec(id=bad_id, description="d", body="b")


def test_skill_spec_64_char_id_is_accepted():
    skill = SkillSpec(id="a" * 64, description="d", body="b")

    assert len(skill.id) == 64


@pytest.mark.parametrize(
    "bad_description",
    [
        pytest.param("", id="empty"),
        pytest.param("x" * 1025, id="over_1024_chars"),
    ],
)
def test_skill_spec_invalid_description_raises_value_error(bad_description):
    with pytest.raises(ValueError):
        SkillSpec(id="ok", description=bad_description, body="b")


def test_skill_spec_1024_char_description_is_accepted():
    skill = SkillSpec(id="ok", description="x" * 1024, body="b")

    assert len(skill.description) == 1024
