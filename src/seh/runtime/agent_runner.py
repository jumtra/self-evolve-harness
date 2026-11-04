"""ホスト名から Runner を引く登録簿。Core はベンダー固有フラグを持たない。"""

from __future__ import annotations

from seh.contracts import CliAgentRunner


class RunnerRegistry:
    def __init__(self) -> None:
        self._runners: dict[str, CliAgentRunner] = {}

    def register(self, runner: CliAgentRunner) -> None:
        self._runners[runner.host] = runner

    def get(self, host: str) -> CliAgentRunner:
        return self._runners[host]
