"""A ``Provider``-typed field holds any provider, and comes and goes through
pydantic and jsonargparse in the same ``class_path``/``init_args`` form."""

import json
from dataclasses import dataclass, field

import pytest
from jsonargparse import ArgumentParser
from pydantic import BaseModel, ValidationError

from powerfunc.compute import ComputeSpecification, Provider, UndefinedProvider
from powerfunc.polymorphic_pydantic_jsonargparse import polymorphic_pydantic_jsonargparse


@dataclass
class Fake(Provider):
    name: str = ""
    tags: list = field(default_factory=list)


class Run(BaseModel):
    compute: ComputeSpecification


CLASS_PATH = f"{Fake.__module__}.{Fake.__qualname__}"
RUN = Run(compute=ComputeSpecification(cpu=2, memory=512, timeout=30, provider=Fake("f", ["x"])))
WRITTEN = {"class_path": CLASS_PATH, "init_args": {"name": "f", "tags": ["x"]}}


def test_pydantic_writes_class_path_and_init_args():
    assert RUN.model_dump()["compute"]["provider"] == WRITTEN


def test_pydantic_reads_back_the_subclass():
    back = Run.model_validate_json(RUN.model_dump_json())
    assert back == RUN
    assert isinstance(back.compute.provider, Fake)


def test_default_provider_survives_the_round_trip():
    run = Run(compute=ComputeSpecification(cpu=1, memory=1, timeout=1))
    assert isinstance(Run.model_validate(run.model_dump()).compute.provider, UndefinedProvider)


def test_jsonargparse_reads_the_pydantic_form_and_writes_it_back():
    parser = ArgumentParser(exit_on_error=False)
    parser.add_class_arguments(Run, "run")
    parsed = parser.parse_object({"run": RUN.model_dump()})
    assert json.loads(parser.dump(parsed, format="json"))["run"]["compute"]["provider"] == WRITTEN
    assert parser.instantiate(parsed)["run"] == RUN


def test_a_class_that_is_not_a_provider_is_refused():
    fields = RUN.model_dump()
    fields["compute"]["provider"]["class_path"] = "pathlib.Path"
    with pytest.raises(ValidationError, match="not a subclass of Provider"):
        Run.model_validate(fields)


@polymorphic_pydantic_jsonargparse
class Shape:
    pass


@dataclass
class Square(Shape):
    side: float = 1.0


class Drawing(BaseModel):
    shape: Shape


def test_the_decorator_makes_any_base_polymorphic():
    written = Drawing(shape=Square(2.0)).model_dump()["shape"]
    assert written == {"class_path": f"{__name__}.Square", "init_args": {"side": 2.0}}
    assert Drawing.model_validate({"shape": written}).shape == Square(2.0)
