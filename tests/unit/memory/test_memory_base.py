import dataclasses

import pytest

from seh.config import MemoryConfig
from seh.contracts.module import MemoryRecord
from seh.providers.memory.base import memory_provider_for, slugify, validate_record
from seh.providers.memory.engram import EngramMemoryProvider
from seh.providers.memory.files import FileMemoryProvider


def test_slugify_keeps_ascii_and_drops_japanese():
    assert slugify("Reply in Japanese!") == "reply_in_japanese"
    assert slugify("日本語 only") == "only"


def test_slugify_hashes_when_nothing_remains():
    slug = slugify("日本語")

    assert len(slug) == 8
    assert slug == slugify("日本語")


def test_validate_record_rejects_unknown_type_and_empty_title():
    valid = MemoryRecord(id="x", type="user", title="t", body="b")
    unknown_type = dataclasses.replace(valid, **{"type": "other"})
    with pytest.raises(ValueError):
        validate_record(unknown_type)
    with pytest.raises(ValueError):
        validate_record(MemoryRecord(id="x", type="user", title="  ", body="b"))


class _Cfg:
    def __init__(self, memory):
        self.memory = memory


def test_provider_for_switches_by_config(tmp_path):
    file_provider = memory_provider_for(_Cfg(MemoryConfig("file")), tmp_path)
    engram_provider = memory_provider_for(_Cfg(MemoryConfig("engram")), tmp_path)

    assert isinstance(file_provider, FileMemoryProvider)
    assert isinstance(engram_provider, EngramMemoryProvider)
