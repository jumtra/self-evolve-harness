import json

import pytest

from seh.redaction import MASK, contains_secret, mask_jsonl, mask_obj, mask_text


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
    [
        "skeleton",
        "task-001",
        "The quick brown fox jumps over the lazy dog.",
        "sk-1",
        '{"tokens": 12}',
        "input_tokens=5",
        "token_count=3",
        "max_tokens: 100",
    ],
    ids=[
        "skeleton",
        "task-id",
        "prose",
        "short-sk",
        "tokens-json-number",
        "input-tokens-usage",
        "token-count",
        "max-tokens",
    ],
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


def test_mask_obj_keeps_usage_keys() -> None:
    obj = {"input_tokens": 10, "output_tokens": 20, "token_count": 30, "cache_read_tokens": 5}

    result = mask_obj(obj)

    assert result == obj


def test_mask_obj_masks_token_suffix_and_exact_keys() -> None:
    obj = {"access_token": "v1", "github_token": "v2", "Client-Secret": "v3"}

    result = mask_obj(obj)

    assert result == {"access_token": MASK, "github_token": MASK, "Client-Secret": MASK}


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("GITHUB_TO" + "KEN=" + "abc123", "abc123"),
        ("DB_PASS" + "WORD=" + "hunter2", "hunter2"),
        ("AWS_SECRET_ACCESS_" + "KEY=" + "wJalrXUtnFEMI", "wJalrXUtnFEMI"),
        ('{"pass' + 'word": "hunter2"}', "hunter2"),
        ('{"api_' + 'key": "abc12345"}', "abc12345"),
        ("postgres://u:" + "p4ss" + "@h/db", "p4ss"),
        ("Authorization: Ba" + "sic " + "dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("Authorization: Tok" + "en " + "abcdef123456", "abcdef123456"),
        ("x-api-" + "key: " + "abcd1234efgh", "abcd1234efgh"),
        ("sk_" + "live_" + "a" * 24, "a" * 24),
        ("sk_" + "test_" + "b" * 24, "b" * 24),
        ("xox" + "b-" + "1234567890-abcdefghij", "1234567890-abcdefghij"),
        (
            "eyJ" + "a" * 10 + ".eyJ" + "b" * 10 + "." + "c" * 10,
            "eyJ" + "a" * 10 + ".eyJ" + "b" * 10 + "." + "c" * 10,
        ),
    ],
    ids=[
        "env-github-token",
        "env-db-password",
        "env-aws-secret-access-key",
        "json-password",
        "json-api-key",
        "url-credentials",
        "auth-basic",
        "auth-token-scheme",
        "x-api-key-header",
        "stripe-live",
        "stripe-test",
        "slack-bot",
        "jwt",
    ],
)
def test_secret_kind_is_masked(text: str, secret: str) -> None:
    result = mask_text(text)

    assert secret not in result
    assert MASK in result


def test_json_password_keeps_key_and_masks_only_value() -> None:
    text = '{"pass' + 'word": "hunter2", "user": "alice"}'

    result = mask_text(text)

    assert result == '{"password": "' + MASK + '", "user": "alice"}'


def test_url_credentials_keep_scheme_user_and_host() -> None:
    text = "postgres://u:" + "p4ss" + "@h/db"

    result = mask_text(text)

    assert result == "postgres://u:" + MASK + "@h/db"


def test_mask_jsonl_masks_by_key_inside_json_line() -> None:
    line = json.dumps({"pass" + "word": "hunter2", "n": 1})

    result = mask_jsonl(line)

    assert json.loads(result) == {"password": MASK, "n": 1}


def test_mask_jsonl_masks_unparseable_line_as_text() -> None:
    text = "not json\nDB_PASS" + "WORD=" + "hunter2"

    result = mask_jsonl(text)

    assert result == "not json\nDB_PASS" + "WORD=" + MASK


def test_mask_jsonl_preserves_non_ascii_text() -> None:
    line = json.dumps({"text": "日本語"}, ensure_ascii=False)

    result = mask_jsonl(line)

    assert result == line
