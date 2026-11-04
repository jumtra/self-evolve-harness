"""公式 CLI の存在・バージョン・必須フラグを --version / --help だけで調べる。"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from seh.contracts import CapabilityLevel, RuntimeCapabilityReport
from seh.runtime.process import DEFAULT_ENV_ALLOWLIST, build_env, run_process

_VERSION = re.compile(r"\d+(?:\.\d+)+[\w.+-]*")


@dataclass(frozen=True)
class ProbeSpec:
    command: str
    required_flags: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    version_args: tuple[str, ...] = ("--version",)
    help_args: tuple[str, ...] = ("--help",)


def _has_flag(help_text: str, flag: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", help_text) is not None


async def _run(spec: ProbeSpec, args: tuple[str, ...], timeout: float) -> str:
    result = await run_process(
        (spec.command, *args),
        cwd=Path.cwd(),
        env=build_env(DEFAULT_ENV_ALLOWLIST, os.environ),
        timeout_seconds=timeout,
    )
    return (result.stdout + b"\n" + result.stderr).decode(errors="replace")


async def _collect(spec: ProbeSpec, timeout: float) -> tuple[str, str]:
    # セッション起動を伴わない 2 コマンドのみ（policy_blocked でも安全）
    version_out = await _run(spec, spec.version_args, timeout)
    help_out = await _run(spec, spec.help_args, timeout)
    return version_out, help_out


def probe_cli(
    host: str,
    spec: ProbeSpec,
    *,
    policy_blocked: bool = False,
    timeout_seconds: float = 10,
) -> RuntimeCapabilityReport:
    if shutil.which(spec.command) is None:
        return RuntimeCapabilityReport(
            host=host,
            installed=False,
            version=None,
            authenticated=None,
            capabilities={name: CapabilityLevel.UNSUPPORTED for name in spec.required_flags},
            policy_blocked=policy_blocked,
            notes=("CLI not found on PATH",),
        )
    version_out, help_out = asyncio.run(_collect(spec, timeout_seconds))
    match = _VERSION.search(version_out)
    capabilities = {
        name: (
            CapabilityLevel.NATIVE
            if all(_has_flag(help_out, flag) for flag in flags)
            else CapabilityLevel.UNSUPPORTED
        )
        for name, flags in spec.required_flags.items()
    }
    return RuntimeCapabilityReport(
        host=host,
        installed=True,
        version=match.group(0) if match else None,
        authenticated=None,
        capabilities=capabilities,
        policy_blocked=policy_blocked,
        notes=(),
    )
