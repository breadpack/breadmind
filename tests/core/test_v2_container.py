import pytest
from typing import Protocol, runtime_checkable
from breadmind.core.v2_container import Container


@runtime_checkable
class GreeterProtocol(Protocol):
    def greet(self, name: str) -> str: ...

class EnglishGreeter:
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"

class KoreanGreeter:
    def greet(self, name: str) -> str:
        return f"안녕, {name}!"

@runtime_checkable
class ServiceProtocol(Protocol):
    def do_work(self) -> str: ...

class ServiceWithDep:
    def __init__(self, greeter: GreeterProtocol):
        self._greeter = greeter
    def do_work(self) -> str:
        return self._greeter.greet("world")

def test_register_and_resolve():
    c = Container()
    c.register(GreeterProtocol, EnglishGreeter())
    greeter = c.resolve(GreeterProtocol)
    assert greeter.greet("test") == "Hello, test!"

def test_resolve_unregistered_raises():
    c = Container()
    with pytest.raises(KeyError):
        c.resolve(GreeterProtocol)

def test_override_registration():
    c = Container()
    c.register(GreeterProtocol, EnglishGreeter())
    c.register(GreeterProtocol, KoreanGreeter())
    greeter = c.resolve(GreeterProtocol)
    assert greeter.greet("test") == "안녕, test!"

def test_register_factory():
    c = Container()
    c.register(GreeterProtocol, EnglishGreeter())
    c.register_factory(ServiceProtocol, lambda cont: ServiceWithDep(cont.resolve(GreeterProtocol)))
    svc = c.resolve(ServiceProtocol)
    assert svc.do_work() == "Hello, world!"

def test_has():
    c = Container()
    assert c.has(GreeterProtocol) is False
    c.register(GreeterProtocol, EnglishGreeter())
    assert c.has(GreeterProtocol) is True

def test_factory_caches_instance():
    c = Container()
    call_count = 0
    def factory(cont):
        nonlocal call_count
        call_count += 1
        return EnglishGreeter()
    c.register_factory(GreeterProtocol, factory)
    c.resolve(GreeterProtocol)
    c.resolve(GreeterProtocol)
    assert call_count == 1  # Factory called only once, cached after
