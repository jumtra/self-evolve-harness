"""配布テンプレートの所在とプレースホルダ置換。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from importlib import resources
from pathlib import Path

__all__ = ["InitError", "render_template_text", "template_spec_dir"]

_PLACEHOLDER = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


class InitError(Exception):
    """init の前提違反（導入済み・テンプレート不備・計画の食い違いなど）。"""


def template_spec_dir() -> Path | None:
    candidate = resources.files("seh") / "templates" / "spec"
    path = Path(str(candidate))
    return path if path.is_dir() else None


def render_template_text(text: str, variables: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if name not in variables:
            raise InitError(f"テンプレートに未知の変数があります: {{{{{name}}}}}")
        return variables[name]

    # 1 パスで置換するため、値に含まれる {{...}} は再展開されない
    return _PLACEHOLDER.sub(replace, text)
