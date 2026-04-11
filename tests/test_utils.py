import asyncio
import dataclasses
from datetime import datetime
from enum import Enum

from breadmind.utils.helpers import generate_short_id, cancel_task_safely, safe_import
from breadmind.utils.serialization import SerializableMixin


def test_generate_short_id_default_length():
    sid = generate_short_id()
    assert len(sid) == 8
    assert sid.isalnum()


def test_generate_short_id_custom_length():
    sid = generate_short_id(12)
    assert len(sid) == 12


async def test_cancel_task_safely_with_none():
    await cancel_task_safely(None)


async def test_cancel_task_safely_with_running_task():
    async def long_running():
        await asyncio.sleep(100)

    task = asyncio.create_task(long_running())
    await cancel_task_safely(task)
    assert task.cancelled()


def test_safe_import_existing_module():
    mod = safe_import("json")
    assert mod is not None


def test_safe_import_missing_module():
    mod = safe_import("nonexistent_module_xyz")
    assert mod is None


class Status(Enum):
    ACTIVE = "active"
    DONE = "done"


@dataclasses.dataclass
class SampleModel(SerializableMixin):
    name: str
    count: int
    status: Status = Status.ACTIVE
    created: datetime | None = None


def test_serializable_to_dict():
    obj = SampleModel(name="test", count=5, status=Status.DONE)
    d = obj.to_dict()
    assert d["name"] == "test"
    assert d["count"] == 5
    assert d["status"] == "done"


def test_serializable_from_dict():
    obj = SampleModel.from_dict({"name": "x", "count": 1, "extra_field": "ignored"})
    assert obj.name == "x"
    assert obj.count == 1


def test_serializable_roundtrip_json():
    obj = SampleModel(name="test", count=3)
    json_str = obj.to_json()
    restored = SampleModel.from_json(json_str)
    assert restored.name == obj.name
    assert restored.count == obj.count
