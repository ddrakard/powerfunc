from dataclasses import dataclass, field
from typing import Any

from pydantic.dataclasses import dataclass as pydantic_dataclass

from powerfunc.command_line import ExpectedException
from powerfunc.compute import (
    ComputeSpecification,
    CpuCount,
    DockerImageUri,
    GpuModel,
    MemorySize,
    Provider,
)
from powerfunc.decorator import PowerFunc

try:
    import modal

    @dataclass
    class ModalProvider(Provider):
        """Runs functions remotely on Modal."""

        pip_packages: tuple[str, ...] = ()

        def image(self, compute: ComputeSpecification) -> modal.Image:
            """The image the function runs in: ``compute.image`` or Debian slim, with
            ``pip_packages`` installed. Override to build one another way, e.g. from a
            conda environment, or with the local codebase added."""
            image = modal.Image.debian_slim()
            if compute.image:
                image = modal.Image.from_registry(compute.image)
            if self.pip_packages:
                image = image.pip_install(*self.pip_packages)
            return image

        def secrets(self) -> list[modal.Secret]:
            """Modal secrets to expose to the function as environment variables."""
            return []

        def call(self, function: PowerFunc, arguments: dict, compute: ComputeSpecification) -> Any:
            app = modal.App(name=f"powerfunc-{function.__name__}")

            @app.function(
                image=self.image(compute),
                cpu=compute.cpu,
                memory=compute.memory,
                gpu=compute.gpu,
                timeout=int(compute.timeout),
                secrets=self.secrets(),
                serialized=True,
            )
            def runner(fn: PowerFunc, args: dict) -> Any:
                return fn._run_without_parsing(**args)

            with app.run():
                return runner.remote(function, arguments)

    @pydantic_dataclass
    class ModalCpuSmall(ComputeSpecification):
        """1 vCPU, 1GB RAM — for Modal."""

        cpu: CpuCount = 1.0
        memory: MemorySize = 1024
        image: DockerImageUri = ""
        provider: Provider = field(default_factory=ModalProvider)

    @pydantic_dataclass
    class ModalGpuA100(ComputeSpecification):
        """8 vCPU, 80GB RAM, A100 GPU — for Modal."""

        cpu: CpuCount = 8.0
        memory: MemorySize = 81920
        image: DockerImageUri = "pytorch/pytorch:2.2.0-cuda12.1-cudnn8-devel"
        gpu: GpuModel = "a100"
        provider: Provider = field(default_factory=ModalProvider)


except ImportError as e:
    raise ExpectedException(
        "modal is not installed. "
        "Install with: pip install 'powerfunc[modal]' or uv add 'powerfunc[modal]'"
    ) from e
