"""ログ・trace・レポートへ出す文字列の秘密マスク。"""

import json
import re

MASK = "[REDACTED]"

# 部分一致だと input_tokens 等の使用量キー（FR-034）まで消えるため、完全一致と接尾辞に絞る
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "refresh_token",
        "id_token",
        "client_secret",
        "private_key",
        "session_token",
        "auth_token",
        "bearer",
    }
)
_SENSITIVE_SUFFIXES = ("_secret", "_password", "_api_key", "_access_token", "_token")

_WHOLE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    # END が欠けた切れ端でも BEGIN 行自体は残さない
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{10,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"),
]

_BEARER = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=\-]+")
_AUTH_HEADER = re.compile(r"(?i)(\bAuthorization\s*:\s*(?:Bearer|Basic|Token)\s+)\S+")
_URL_CREDENTIALS = re.compile(r"(\b[A-Za-z][A-Za-z0-9+.\-]*://[^\s:/@]+:)[^\s@/]+(?=@)")
# キー名は末尾が機密語のものだけ対象にする。input_tokens / token_count は
# 機密語の直後が区切り文字にならないので自然に除外される（使用量キー FR-034 を守る）
_KEY_VALUE = re.compile(
    r"(?i)((?<![A-Za-z0-9])[\"']?[A-Za-z0-9_-]*"
    r"(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|auth)"
    r"[\"']?\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s\"',;]+)"
)


def _mask_value(match: re.Match[str]) -> str:
    value = match.group(2)
    quote = value[0] if value[0] in "\"'" else ""
    return match.group(1) + quote + MASK + quote


def mask_text(text: str) -> str:
    for pattern in _WHOLE_PATTERNS:
        text = pattern.sub(MASK, text)
    text = _AUTH_HEADER.sub(lambda m: m.group(1) + MASK, text)
    text = _BEARER.sub(lambda m: m.group(1) + MASK, text)
    text = _URL_CREDENTIALS.sub(lambda m: m.group(1) + MASK, text)
    return _KEY_VALUE.sub(_mask_value, text)


def mask_jsonl(text: str) -> str:
    """JSONL は行ごとに構造でマスクする。キー名で消せる値がテキスト正規表現の死角にあるため。"""
    lines: list[str] = []
    for line in text.split("\n"):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            lines.append(mask_text(line))
            continue
        lines.append(mask_text(json.dumps(mask_obj(obj), ensure_ascii=False)))
    return "\n".join(lines)


def contains_secret(text: str) -> bool:
    return mask_text(text) != text


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def mask_obj(obj: object) -> object:
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {k: MASK if _is_sensitive_key(k) else mask_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(mask_obj(v) for v in obj)
    return obj
