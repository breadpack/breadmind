import pytest

from breadmind.core.events import EventBus


@pytest.fixture
def fresh_bus():
    return EventBus()
