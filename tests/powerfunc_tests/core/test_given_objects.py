"""A Python call's arguments reach the function as they were given.

No argument parser stands between a Python caller and the function: an object
the caller made (an instance of their own class, an immutable mapping, a
callable) is passed on as it is, and only a path given for a readable type is
read. The command line is where jsonargparse parses.
"""

from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType

import pytest

from powerfunc import powerfunc
from powerfunc.command_line import ExpectedException
from powerfunc.compute import ComputeSpecification, Provider


class Target:
    def __init__(self, value: float):
        self.value = value


@powerfunc
def total(targets: Sequence[Mapping[str, float]], *, scale: float = 1.0) -> float:
    return scale * sum(sum(target.values()) for target in targets)


@powerfunc
def apply(function: Callable[[int], int], value: int) -> int:
    return function(value)


@powerfunc
def describe(target: Target, *, label: str) -> str:
    return f"{label}={target.value}"


def test_immutable_mappings_pass_through_unchanged():
    targets = [MappingProxyType({"a": 1.0, "b": 2.0}), MappingProxyType({"a": 3.0})]
    assert total(targets, scale=2.0) == 12.0


class Frozen(dict):
    def __setitem__(self, key, value):
        raise TypeError("frozen")


def test_a_dict_subclass_is_not_written_to():
    assert total([Frozen({"a": 1.0})], scale=2.0) == 2.0


def test_callables_pass_through():
    assert apply(lambda x: x + 1, 2) == 3


def test_own_objects_pass_through():
    assert describe(Target(1.5), label="x") == "x=1.5"


def test_a_missing_argument_is_reported():
    with pytest.raises(ExpectedException, match="label"):
        describe(Target(1.5))  # type: ignore[call-arg]


class Recording(Provider):
    def call(self, function, arguments, spec):
        return function, arguments


def test_a_compute_object_is_used_as_given():
    provider = Recording()
    spec = ComputeSpecification(timeout=1.0, cpu=1.0, memory=1, provider=provider)
    target = Target(2.0)
    function, arguments = describe(target, label="x", compute=spec)
    assert function.__name__ == "describe"
    assert arguments["target"] is target
    assert arguments["label"] == "x"


DEFAULT_TARGET = Target(0.5)


@powerfunc
def describe_default(*, label: str, target: Target = DEFAULT_TARGET) -> str:
    return f"{label}={target.value}"


def test_a_default_that_is_an_object_is_used_as_it_is():
    assert describe_default(label="x") == "x=0.5"
