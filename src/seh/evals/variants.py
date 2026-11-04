"""比較対象の Variant 定義（設計 02 §7.1 の V0〜V5）。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"

# エージェントの最終応答が従う出力契約（output_instructions に渡す）
OUTPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "summary": {"type": "string"},
        "changed_files": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "summary"],
}

SOURCE_PRIORITY_SECTION = (
    "# 情報源の優先順位\n\n"
    "矛盾する情報があるときは次の順で信頼する。\n\n"
    "1. リポジトリのテスト\n"
    "2. 既存コード\n"
    "3. README"
)


@dataclass(frozen=True)
class Variant:
    id: str
    name: str
    prompt_template: str
    output_contract: bool
    tool_delegation: bool
    # 1 回の trial でエージェントを実行する最大回数（1 = 修正なし）
    repair_attempts: int
    source_priority: bool


def _variant(
    id_: str,
    name: str,
    template: str,
    *,
    contract: bool = False,
    priority: bool = False,
    tools: bool = False,
    attempts: int = 1,
) -> Variant:
    return Variant(id_, name, template, contract, tools, attempts, priority)


VARIANTS: Mapping[str, Variant] = {
    v.id: v
    for v in (
        _variant("V0", "baseline", "task_v1.md"),
        _variant("V1", "prompt_cleanup", "task_v2.md"),
        _variant("V2", "output_contract", "task_v2.md", contract=True),
        _variant("V3", "source_priority", "task_v2.md", contract=True, priority=True),
        _variant("V4", "tool_delegation", "task_v2.md", contract=True, priority=True, tools=True),
        _variant(
            "V5",
            "repair_loop",
            "task_v2.md",
            contract=True,
            priority=True,
            tools=True,
            attempts=3,
        ),
    )
}


def load_template(variant: Variant) -> str:
    return (PROMPTS_DIR / variant.prompt_template).read_text(encoding="utf-8")


def prompt_digest(variant: Variant) -> str:
    """Variant が実際に渡す静的プロンプト構成の sha256（FR-025: Prompt の版）。"""
    parts = {
        "template": load_template(variant),
        "output_contract": variant.output_contract,
        "source_priority": SOURCE_PRIORITY_SECTION if variant.source_priority else None,
        "tool_delegation": variant.tool_delegation,
    }
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()
