import pytest


@pytest.fixture
def safety_config():
    return {
        "blacklist": {
            "test": ["dangerous_action"]
        },
        "require_approval": ["needs_approval"]
    }
