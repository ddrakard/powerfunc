from dataclasses import dataclass, field
from typing import Any, Callable

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

try:
    import modal

    @dataclass
    class ModalProvider(Provider):
        """Runs functions remotely on Modal."""

        pip_packages: tuple[str, ...] = ()

        def call(self, function: Callable, arguments: dict, compute: ComputeSpecification) -> Any:
            image = modal.Image.debian_slim()
            if compute.image:
                image = modal.Image.from_registry(compute.image)
            if self.pip_packages:
                image = image.pip_install(*self.pip_packages)
            app = modal.App(name=f"powerfunc-{function.__name__}")

            @app.function(
                image=image,
                cpu=compute.cpu,
                memory=compute.memory,
                gpu=compute.gpu,
                serialized=True,
            )
            def runner(fn: Callable, args: dict) -> Any:
                return fn(**args)

            output_path = arguments.pop("output_path", None)

            with app.run():
                result = runner.remote(function, arguments)

            if output_path is not None:
                from powerfunc.conversions import write

                write(result, output_path)
                return output_path

            return result

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
