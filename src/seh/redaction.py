"""ログ・trace・レポートへ出す文字列の秘密マスク。"""

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
]

_BEARER = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=\-]+")
_KEY_VALUE = re.compile(
    r"(?i)(\b(?:password|passwd|token|api_key|apikey|secret)\b\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s\"',;]+)"
)


def mask_text(text: str) -> str:
    for pattern in _WHOLE_PATTERNS:
        text = pattern.sub(MASK, text)
    text = _BEARER.sub(lambda m: m.group(1) + MASK, text)
    return _KEY_VALUE.sub(lambda m: m.group(1) + MASK, text)


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
