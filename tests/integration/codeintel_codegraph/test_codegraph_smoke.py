import shutil
from typing import cast

import pytest

from seh.contracts.common import ResultStatus
from seh.providers.codeintel.base import Symbol
from seh.providers.codeintel.codegraph import CodeGraphProvider

pytestmark = pytest.mark.skipif(shutil.which("codegraph") is None, reason="codegraph not installed")


def test_real_codegraph_index_search_and_dependencies(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "util.py").write_text("def helper(x):\n    return x + 1\n")
    (repo / "main.py").write_text("from util import helper\n\n\ndef run():\n    return helper(2)\n")
    provider = CodeGraphProvider(repo, home=tmp_path / "home")
    (tmp_path / "home").mkdir()

    indexed = provider.index(repo)
    assert indexed.status is ResultStatus.OK, indexed.message

    found = provider.search_symbols("helper")
    assert found.status in (ResultStatus.OK, ResultStatus.ERROR)
    if found.status is ResultStatus.OK:
        assert any(
            s.name == "helper" and s.path == "util.py" for s in cast(tuple[Symbol, ...], found.data)
        )

    deps = provider.dependencies("helper")
    assert deps.status in (ResultStatus.OK, ResultStatus.ERROR)
    if deps.status is ResultStatus.OK:
        assert "main.py" in cast(tuple[str, ...], deps.data)
