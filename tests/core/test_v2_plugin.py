import pytest
from breadmind.core.plugin import PluginLoader, PluginManifest
from breadmind.core.v2_container import Container
from breadmind.core.v2_events import EventBus


@pytest.fixture
def loader():
    return PluginLoader(container=Container(), events=EventBus())


def test_manifest_creation():
    m = PluginManifest(name="test-plugin", version="1.0.0", provides=["GreeterProtocol"], depends_on=[])
    assert m.name == "test-plugin"


def test_register_plugin(loader):
    class FakePlugin:
        manifest = PluginManifest(name="fake", version="0.1", provides=[], depends_on=[])
        async def setup(self, container, events): pass
        async def teardown(self): pass

    loader.register(FakePlugin())
    assert "fake" in loader.list_plugins()


def test_register_duplicate_raises(loader):
    class FakePlugin:
        manifest = PluginManifest(name="dupe", version="0.1", provides=[], depends_on=[])
        async def setup(self, container, events): pass
        async def teardown(self): pass

    loader.register(FakePlugin())
    with pytest.raises(ValueError, match="already registered"):
        loader.register(FakePlugin())


@pytest.mark.asyncio
async def test_setup_all(loader):
    setup_called = []

    class TestPlugin:
        manifest = PluginManifest(name="test", version="0.1", provides=[], depends_on=[])
        async def setup(self, container, events):
            setup_called.append(True)
        async def teardown(self): pass

    loader.register(TestPlugin())
    await loader.setup_all()
    assert len(setup_called) == 1


@pytest.mark.asyncio
async def test_teardown_all(loader):
    torn_down = []

    class TestPlugin:
        manifest = PluginManifest(name="td", version="0.1", provides=[], depends_on=[])
        async def setup(self, container, events): pass
        async def teardown(self):
            torn_down.append(True)

    loader.register(TestPlugin())
    await loader.setup_all()
    await loader.teardown_all()
    assert len(torn_down) == 1


@pytest.mark.asyncio
async def test_dependency_order(loader):
    order = []

    class PluginA:
        manifest = PluginManifest(name="A", version="0.1", provides=["A"], depends_on=[])
        async def setup(self, container, events):
            order.append("A")
        async def teardown(self): pass

    class PluginB:
        manifest = PluginManifest(name="B", version="0.1", provides=["B"], depends_on=["A"])
        async def setup(self, container, events):
            order.append("B")
        async def teardown(self): pass

    loader.register(PluginB())
    loader.register(PluginA())
    await loader.setup_all()
    assert order == ["A", "B"]
