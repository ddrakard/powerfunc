import dataclasses
from typing import TYPE_CHECKING, Annotated, Any, Optional, TypeAlias

from pydantic import Field, GetCoreSchemaHandler
from pydantic.dataclasses import dataclass as pydantic_dataclass
from pydantic_core import core_schema

from powerfunc.command_line import ExpectedException

Timeout: TypeAlias = Annotated[float, Field(gt=0, description="Maximum job duration in seconds")]
CpuCount: TypeAlias = Annotated[float, Field(gt=0, description="Number of vCPUs")]
MemorySize: TypeAlias = Annotated[int, Field(gt=0, description="RAM in MB")]
DockerImageUri: TypeAlias = Annotated[str, Field(description="Container image URI")]
GpuModel: TypeAlias = Annotated[Optional[str], Field(description="GPU model name")]

if TYPE_CHECKING:
    from powerfunc.decorator import PowerFunc


class Provider:
    """Base compute provider. Subclass and implement call()."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.is_instance_schema(cls)

    def call(self, function: "PowerFunc", arguments: dict, spec: "ComputeSpecification") -> Any:
        """Run ``function._run_without_parsing(**arguments)`` on the compute, returning its result.

        ``function`` is the powerfunc function itself, picklable by its name.
        ``arguments`` have already been parsed and merged with the configuration
        files, so the compute does neither; there, ``_run_without_parsing`` opens
        the files given for parameters and writes the result to ``output_path``.
        """
        raise NotImplementedError


class UndefinedProvider(Provider):
    """Sentinel — raises ExpectedException when called if no provider has been configured."""

    def call(self, function, arguments, spec):
        raise ExpectedException(
            "No provider configured. Set compute.provider in configuration/powerfunc.yaml"
        )


@pydantic_dataclass
class ComputeSpecification:
    """Specifies compute resources for remote execution."""

    timeout: Timeout
    cpu: CpuCount
    memory: MemorySize
    image: DockerImageUri = ""
    provider: Provider = dataclasses.field(default_factory=UndefinedProvider)
    gpu: GpuModel = None


@pydantic_dataclass
class CpuSmall(ComputeSpecification):
    """1 vCPU, 2GB RAM, Python 3.12 slim."""

    cpu: CpuCount = 1.0
    memory: MemorySize = 2048
    image: DockerImageUri = "python:3.12-slim"


user_identifier: Optional[str] = None
"""Optional prefix added to remote artifact names, useful for identifying your jobs
in a shared storage bucket."""
