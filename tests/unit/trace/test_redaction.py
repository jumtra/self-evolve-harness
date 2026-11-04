import json
from pathlib import Path

import pytest

from seh.redaction import MASK, contains_secret, mask_obj, mask_text

FIXTURE = Path(__file__).parents[2] / "fixtures" / "security" / "masking_log_case.json"


def test_aws_access_key_is_masked() -> None:
    value = "AKIA" + "A" * 16
    text = f"aws={value} end"

    result = mask_text(text)

    assert value not in result
    assert MASK in result


def test_anthropic_key_is_masked() -> None:
    value = "sk-ant-" + "a" * 40
    text = f"key {value}"

    result = mask_text(text)

    assert value not in result
    assert MASK in result


def test_openai_keys_are_masked() -> None:
    plain = "sk-" + "b" * 24
    project = "sk-proj-" + "c" * 30
    text = f"{plain} and {project}"

    result = mask_text(text)

    assert plain not in result
    assert project not in result


def test_github_tokens_are_masked() -> None:
    classic = "ghp_" + "d" * 36
    fine = "github_pat_" + "e" * 30
    text = f"{classic} {fine}"

    result = mask_text(text)

    assert classic not in result
    assert fine not in result


def test_google_api_key_is_masked() -> None:
    value = "AIza" + "f" * 35
    text = f"k={value}"

    result = mask_text(text)

    assert value not in result


def test_pem_private_key_block_is_masked_entirely() -> None:
    begin = "-----BEGIN " + "RSA PRIVATE KEY-----"
    end = "-----END " + "RSA PRIVATE KEY-----"
    body = "MIIEowIBAAKCAQEA" + "x" * 20
    text = f"before\n{begin}\n{body}\n{end}\nafter"

    result = mask_text(text)

    assert body not in result
    assert begin not in result
    assert "before" in result
    assert "after" in result


def test_bearer_token_is_masked() -> None:
    token = "tok" + "9" * 20
    text = f"Authorization: Bearer {token}"

    result = mask_text(text)

    assert token not in result


def test_key_value_keeps_key_and_masks_value() -> None:
    text = 'password=hunter22 token: abc123xyz api_key="k-value" secret=s3cr3t'

    result = mask_text(text)

    assert "hunter22" not in result
    assert "abc123xyz" not in result
    assert "k-value" not in result
    assert "s3cr3t" not in result
    assert "password=" in result
    assert "api_key=" in result


@pytest.mark.parametrize(
    "text",
    ["skeleton", "task-001", "The quick brown fox jumps over the lazy dog.", "sk-1"],
)
def test_benign_text_is_not_masked(text: str) -> None:
    result = mask_text(text)

    assert result == text
    assert contains_secret(text) is False


def test_contains_secret_detects_secret() -> None:
    text = "x " + "AKIA" + "A" * 16

    assert contains_secret(text) is True


def test_mask_obj_masks_by_key_name_and_recurses() -> None:
    value = "ghp_" + "g" * 36
    obj = {
        "password": "anything",
        "Authorization": "whatever",
        "nested": [{"api_key": "zzz", "note": f"tok {value}"}, ("plain", 3)],
        "count": 5,
    }

    result = mask_obj(obj)

    assert result == {
        "password": MASK,
        "Authorization": MASK,
        "nested": [{"api_key": MASK, "note": f"tok {MASK}"}, ("plain", 3)],
        "count": 5,
    }


def test_fixture_log_template_is_masked() -> None:
    case = json.loads(FIXTURE.read_text(encoding="utf-8"))
    generated: dict[str, str] = {}
    for name, spec in case["secrets"].items():
        tpl = spec["secret_template"]
        if "parts" in tpl:
            generated[name] = "".join(tpl["parts"])
        else:
            generated[name] = tpl["prefix"] + tpl["fill"] * tpl["length"] + tpl.get("suffix", "")
    lines = [line.format(**generated) if "{" in line else line for line in case["log_template"]]

    masked = [mask_text(line) for line in lines]

    for name in case["expect"]["masked_output_contains_none_of"]:
        assert all(generated[name] not in m for m in masked)
    for index in case["expect"]["preserved_lines"]:
        assert masked[index] == lines[index]


def test_mask_obj_keeps_usage_keys() -> None:
    obj = {"input_tokens": 10, "output_tokens": 20, "token_count": 30, "cache_read_tokens": 5}

    result = mask_obj(obj)

    assert result == obj


def test_mask_obj_masks_token_suffix_and_exact_keys() -> None:
    obj = {"access_token": "v1", "github_token": "v2", "Client-Secret": "v3"}

    result = mask_obj(obj)

    assert result == {"access_token": MASK, "github_token": MASK, "Client-Secret": MASK}
