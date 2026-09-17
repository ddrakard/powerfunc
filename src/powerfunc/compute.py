import dataclasses
from typing import TYPE_CHECKING, Annotated, Any, TypeAlias

from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass

from powerfunc.command_line import ExpectedException
from powerfunc.polymorphic_pydantic_jsonargparse import polymorphic_pydantic_jsonargparse

Timeout: TypeAlias = Annotated[float, Field(gt=0, description="Maximum job duration in seconds")]
CpuCount: TypeAlias = Annotated[float, Field(gt=0, description="Number of vCPUs")]
MemorySize: TypeAlias = Annotated[int, Field(gt=0, description="RAM in MB")]
DockerImageUri: TypeAlias = Annotated[str, Field(description="Container image URI")]
GpuModel: TypeAlias = Annotated[
    str | None, Field(description="GPU model name, as the provider names it (e.g. 'l4', 'a100')")
]

UV_PROJECT_SETUP = "uv sync --locked && . .venv/bin/activate"
"""Setup command for a codebase that is a uv project."""

_PIXI_URL = "https://pixi.sh/install.sh"
PIXI_PROJECT_SETUP = (
    'export PATH="$HOME/.pixi/bin:$PATH"; { command -v pixi >/dev/null 2>&1 || '
    "{ command -v curl >/dev/null 2>&1 && curl -fsSL "
    + _PIXI_URL
    + " || wget -qO- "
    + _PIXI_URL
    + "; }"
    ' | PIXI_HOME="$HOME/.pixi" sh; } && pixi install --locked && eval "$(pixi shell-hook)"'
)
"""Setup command for a codebase that is a pixi project."""

_PIP_VENV = "python -m venv .venv && . .venv/bin/activate"
PIP_PYPROJECT_SETUP = _PIP_VENV + " && pip install -q ."
"""Setup command for a codebase that is a pip-installable project (``pyproject.toml``)."""
PIP_REQUIREMENTS_TXT_SETUP = _PIP_VENV + " && pip install -q -r requirements.txt"
"""Setup command for a codebase with a pip ``requirements.txt``."""

if TYPE_CHECKING:
    from powerfunc.decorator import PowerFunc


@polymorphic_pydantic_jsonargparse
class Provider:
    """Base compute provider. Subclass and implement call()."""

    def call(self, function: "PowerFunc", arguments: dict, compute: "ComputeSpecification") -> Any:
        """Run ``function._run_without_parsing(**arguments)`` on the compute, returning its result.

        ``function`` is the powerfunc function itself, named in the job by module and qualname.
        ``arguments`` have already been parsed and merged with the configuration
        files, so the compute does neither; there, ``_run_without_parsing`` opens
        the files given for parameters and writes the result to ``output_path``.
        """
        raise NotImplementedError


class UndefinedProvider(Provider):
    """Sentinel — raises ExpectedException when called if no provider has been configured."""

    def call(self, function, arguments, compute):
        raise ExpectedException(
            "No provider configured. Set compute.provider in powerfunc.yaml or pass compute="
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
