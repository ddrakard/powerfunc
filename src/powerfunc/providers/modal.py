"""Modal provider.

The job's three stages (see :mod:`powerfunc.providers.internal.generic_setup_entrypoint`) run
as on other providers, in the container: the codebase is a Modal mount (files sent at container
start, only those Modal has not already seen, no image layer built) onto the image's working
directory, over whatever the image has there; a small runner then writes the job spec and
arguments to the container and runs ``setup_command`` followed by ``python -m
powerfunc.providers.internal.generic_execute_entrypoint`` in one shell there, so the ``python``
the setup command leaves on ``PATH`` runs the function. The image's working directory is
learned from Modal by resolving the image (a build, if not cached) before the call.

The container's stdout and stderr (the setup command's and the function's) are written to the
local stdout and stderr as they arrive; Modal's own terminal display is not used, as it is one
per process and cannot serve concurrent runs (see
:mod:`powerfunc.providers.internal.modal_output`).
"""

import pathlib
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import cloudpickle as pickle
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
from powerfunc.providers.internal.codebase_transfer import repository_root
from powerfunc.providers.internal.job_specification import function_identifier, job_spec
from powerfunc.providers.internal.secret_directories import (
    KEY_VARIABLE,
    encrypt_secret_directories,
)

DEFAULT_WORKING_DIRECTORY = "/root"


try:
    import modal
    import modal_proto.api_pb2

    from powerfunc.providers.internal.modal_output import forward_remote_output

    def working_directory(image: modal.Image, app_name: str) -> str:
        """The image's ``WORKDIR``, where Modal starts its containers, or Modal's default
        when it sets none. Learned by resolving the image (a build, if not cached) in an app
        run that registers a function on it but calls nothing, so starts no container."""
        app = modal.App(name=app_name)
        app.function(image=image, serialized=True, name="resolve_image")(lambda: None)
        forward_remote_output()
        with app.run():
            metadata = image._get_metadata()  # pyright: ignore[reportPrivateUsage]
        if isinstance(metadata, modal_proto.api_pb2.ImageMetadata) and metadata.workdir:
            return metadata.workdir
        return DEFAULT_WORKING_DIRECTORY

    def add_codebase(
        image: modal.Image,
        root: pathlib.Path,
        remote_path: str,
        exclude_directories: Sequence[str] = (),
    ) -> modal.Image:
        """The repository mounted at ``remote_path`` in the container (over whatever the image
        has there), minus ``.git``, the ``exclude_directories`` and whatever git ignores
        (ignored directories are listed, and pruned, whole)."""
        ignored = subprocess.check_output(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"],
            cwd=root,
            text=True,
        ).splitlines()
        ignore = modal.FilePatternMatcher(
            ".git", *(entry.strip("/") for entry in [*ignored, *exclude_directories])
        )
        return image.add_local_dir(root, remote_path, copy=False, ignore=ignore)

    @dataclass
    class ModalProvider(Provider):
        """Runs functions remotely on Modal.

        ``setup_command`` is a shell command run in the sent codebase when the container
        starts, on every call, which must leave a python with powerfunc installed first on
        PATH; empty if the image has one (the usual case: the codebase is sent as a mount, so
        editing it costs no image build).

        ``environment_variables`` are those of the running function; ``secret_directories``
        (relative to the codebase's git root) are sent encrypted rather than in the image: for
        credentials and other files git ignores.
        """

        setup_command: str = ""
        environment_variables: dict[str, str] = field(default_factory=dict)
        secret_directories: list[str] = field(default_factory=list)

        def _base_image(self, compute: ComputeSpecification) -> modal.Image:
            """``compute.image`` from a registry, or Modal's Debian slim."""
            if compute.image:
                return modal.Image.from_registry(compute.image)
            return modal.Image.debian_slim()

        def call(self, function: PowerFunc, arguments: dict, compute: ComputeSpecification) -> Any:
            function_id = function_identifier(function)
            codebase = repository_root(function)
            secrets = encrypt_secret_directories(codebase, self.secret_directories)
            environment = dict(self.environment_variables)
            if secrets is not None:
                environment[KEY_VARIABLE] = secrets[1]
            app_name = f"powerfunc-{function.__name__}"
            image = self._base_image(compute)
            directory = working_directory(image, app_name)
            if codebase is not None:
                image = add_codebase(image, codebase, directory, self.secret_directories)
            app = modal.App(name=app_name)

            def runner(
                spec: dict[str, Any],
                arguments: dict[str, bytes],
                secrets: bytes | None,
                codebase: str | None,
            ) -> bytes:
                """Runs in the container, in the image's own Python, using only the standard
                library: pickled by value, powerfunc need not be importable there. ``spec`` is
                the job spec with argument and output paths relative to a directory made here;
                ``secrets`` the encrypted secret directories, if any; ``codebase`` the mounted
                codebase, if one was sent, where ``spec["setup_command"]`` then the execute
                stage run in one shell (as :mod:`generic_setup_entrypoint` does)."""
                import json
                import pathlib
                import shlex
                import subprocess
                import tempfile

                directory = pathlib.Path(tempfile.mkdtemp())
                for name, value in arguments.items():
                    (directory / spec["argument_paths"][name]).write_bytes(value)
                spec = {
                    **spec,
                    "output_path": str(directory / spec["output_path"]),
                    "argument_paths": {
                        name: str(directory / path) for name, path in spec["argument_paths"].items()
                    },
                }
                if secrets is not None:
                    (directory / "secrets").write_bytes(secrets)
                    spec["secret_directories_path"] = str(directory / "secrets")
                (directory / "job_spec.json").write_text(json.dumps(spec))
                execute = (
                    "exec python -m powerfunc.providers.internal.generic_execute_entrypoint "
                    + shlex.quote(str(directory / "job_spec.json"))
                )
                if codebase:
                    execute += " " + shlex.quote(codebase)
                setup_command = spec["setup_command"]
                script = f"{setup_command} && {execute}" if setup_command else execute
                result = subprocess.run(["sh", "-c", script], cwd=codebase)
                error_path = pathlib.Path(spec["output_path"] + "__error")
                if error_path.exists():
                    raise RuntimeError(error_path.read_text())
                if result.returncode != 0:
                    raise RuntimeError(
                        f"setup_command or python exited with code {result.returncode}"
                    )
                return pathlib.Path(spec["output_path"]).read_bytes()

            remote = app.function(
                image=image,
                cpu=compute.cpu,
                memory=compute.memory,
                gpu=compute.gpu,
                timeout=int(compute.timeout),
                secrets=[modal.Secret.from_dict(environment)],
                serialized=True,
            )(runner)
            pickled = {name: pickle.dumps(value) for name, value in arguments.items()}
            forward_remote_output()
            with app.run():
                spec = job_spec(
                    function_id,
                    "output",
                    {name: f"argument_{name}" for name in arguments},
                    setup_command=self.setup_command.strip(),
                )
                output = remote.remote(
                    spec,
                    pickled,
                    None if secrets is None else secrets[0],
                    None if codebase is None else directory,
                )
            return pickle.loads(output)

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
