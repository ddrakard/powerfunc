import collections.abc
import contextlib
import importlib
import io
import json
import os
import pathlib
import random
import subprocess
import sys
import tempfile
import time
import warnings
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import cloudpickle as pickle
from cloudpathlib import AnyPath
from pydantic.dataclasses import dataclass as pydantic_dataclass

import __main__
from powerfunc.command_line import ExpectedException
from powerfunc.compute import ComputeSpecification, Provider, user_identifier

_SUPPORTED_GPUS = {"t4", "a100", "l4", "v100"}
_MAX_JOB_NAME_LENGTH = 63  # Cloud Run Jobs name limit


def _generate_names(names: collections.abc.Collection[str]) -> dict[str, str]:
    """Generate unique qualified names for artifact storage.

    Returns a mapping from original to generated name. Prefixes with user_identifier if set,
    to identify jobs in a shared bucket.
    """
    prefix_parts = []
    if user_identifier:
        prefix_parts.append(str(user_identifier))
    prefix_parts.append(time.strftime("%Y%m%d_%H%M%S"))
    prefix_parts.append(str(random.randint(0, 999999)).zfill(6))
    prefix = "_".join(prefix_parts)
    return {name: f"{prefix}_{name}" for name in names}


@dataclass
class GCPProvider(Provider):
    """Runs functions remotely on GCP Cloud Run Jobs."""

    project: str
    region: str
    temporary_bucket_path: str
    environment_variables: dict[str, str] = field(default_factory=dict)

    def _generate_paths(self, names: collections.abc.Collection[str]) -> dict[str, AnyPath]:
        # "powerfunc" prefix ensures we don't pollute the user's directory
        # if they pass a bucket root as temporary_bucket_path
        base = AnyPath(self.temporary_bucket_path) / "powerfunc"
        return {name: base / generated for name, generated in _generate_names(names).items()}

    def _zip_codebase(self) -> Optional[bytes]:
        """Zip all git-tracked files from the repo, if one can be found."""
        entry = getattr(__main__, "__file__", None)
        start = pathlib.Path(entry).resolve().parent if entry else pathlib.Path.cwd()
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            warnings.warn(
                "No git repository found. Assuming the function is from an installed package "
                "and no codebase will be sent to the remote container.",
                stacklevel=2,
            )
            return None
        repo_root = pathlib.Path(result.stdout.strip())
        files = subprocess.check_output(["git", "ls-files"], cwd=repo_root).decode().splitlines()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in files:
                zf.write(repo_root / file, arcname=file)
        return buffer.getvalue()

    def _submit_job(
        self,
        job_name: str,
        compute: ComputeSpecification,
        job_spec_path: AnyPath,
    ) -> None:
        try:
            from google.cloud import run_v2
        except ImportError as e:
            raise ExpectedException(
                "google-cloud-run is not installed. "
                "Install it with: pip install powerfunc[gcp] or uv add powerfunc[gcp]"
            ) from e

        bootstrap = (
            f"pip install uv -q && "
            f"uv pip install powerfunc --system -q && "
            f"python -m powerfunc.providers.gcp {job_spec_path}"
        )

        env = [run_v2.EnvVar(name=k, value=v) for k, v in self.environment_variables.items()]

        resources = {"cpu": str(compute.cpu), "memory": f"{compute.memory}Mi"}
        if compute.gpu:
            if compute.gpu not in _SUPPORTED_GPUS:
                raise ExpectedException(
                    f"Unsupported GPU: {compute.gpu!r}. Supported: {sorted(_SUPPORTED_GPUS)}"
                )
            resources["nvidia.com/gpu"] = "1"
            resources["cloud.google.com/gke-accelerator"] = f"nvidia-{compute.gpu}"

        job = run_v2.Job(
            template=run_v2.ExecutionTemplate(
                template=run_v2.TaskTemplate(
                    containers=[
                        run_v2.Container(
                            image=compute.image,
                            command=["sh", "-c"],
                            args=[bootstrap],
                            env=env,
                            resources=run_v2.ResourceRequirements(limits=resources),
                        )
                    ]
                )
            )
        )

        client = run_v2.JobsClient()
        parent = f"projects/{self.project}/locations/{self.region}"
        operation = client.create_job(parent=parent, job=job, job_id=job_name)
        operation.result()

        run_operation = client.run_job(name=f"{parent}/jobs/{job_name}")
        run_operation.result()

        try:
            client.delete_job(name=f"{parent}/jobs/{job_name}").result()
        except Exception:
            pass

    def call(self, function: Callable, arguments: dict, compute: ComputeSpecification) -> Any:
        if function.__module__ == "__main__":
            spec = getattr(__main__, "__spec__", None)
            if spec is None:
                raise ExpectedException(
                    "Run your script with 'python -m my_script' instead of "
                    "'python my_script.py' to enable remote execution."
                )
            module_name = spec.name
        else:
            module_name = function.__module__
        function_id = f"{module_name}:{function.__qualname__}"
        codebase = self._zip_codebase()

        artifact_names = ["_output", "_job_spec"] + [f"_argument_{k}" for k in arguments]
        if codebase is not None:
            artifact_names = ["_codebase", *artifact_names]
        paths = self._generate_paths(artifact_names)

        try:
            if codebase is not None:
                paths["_codebase"].write_bytes(codebase)

            for name, value in arguments.items():
                paths[f"_argument_{name}"].write_bytes(pickle.dumps(value))

            spec = {
                "function": function_id,
                "output_path": str(paths["_output"]),
                "argument_paths": {name: str(paths[f"_argument_{name}"]) for name in arguments},
            }
            if codebase is not None:
                spec["codebase_path"] = str(paths["_codebase"])
            paths["_job_spec"].write_bytes(json.dumps(spec).encode())

            job_name = ("pf-" + paths["_output"].name.replace("_", "-"))[:_MAX_JOB_NAME_LENGTH]
            self._submit_job(job_name, compute, paths["_job_spec"])

            result = pickle.loads(paths["_output"].read_bytes())
        finally:
            for path in paths.values():
                try:
                    path.unlink()
                except Exception:
                    pass

        return result


@pydantic_dataclass
class GcpCpuSmall(ComputeSpecification):
    """1 vCPU, 2GB RAM, Python 3.12 slim — for GCP."""

    cpu: float = 1.0
    memory: int = 2048
    image: str = "python:3.12-slim"


@pydantic_dataclass
class GcpGpu(ComputeSpecification):
    """4 vCPU, 16GB RAM, L4 GPU — for GCP."""

    cpu: float = 4.0
    memory: int = 16384
    image: str = "gcr.io/deeplearning-platform-release/base-cu121"
    gpu: str = "l4"


GCP_CPU_SMALL = GcpCpuSmall()
GCP_GPU = GcpGpu()


if __name__ == "__main__":
    job_spec_path = AnyPath(sys.argv[1])
    spec = json.loads(job_spec_path.read_bytes().decode())

    kwargs = {
        name: pickle.loads(AnyPath(path).read_bytes())
        for name, path in spec["argument_paths"].items()
    }

    with contextlib.ExitStack() as stack:
        if "codebase_path" in spec:
            # POWERFUNC_CODEBASE_OVERLAY_DIR: extract synced files on top of an existing
            # source tree (e.g. a monorepo with editable installs at known paths).
            # Without it, the default isolated-temp-dir + sys.path behaviour is used.
            overlay_dir = os.environ.get("POWERFUNC_CODEBASE_OVERLAY_DIR")
            zf_bytes = AnyPath(spec["codebase_path"]).read_bytes()
            if overlay_dir:
                with zipfile.ZipFile(io.BytesIO(zf_bytes)) as zf:
                    zf.extractall(overlay_dir)
            else:
                workdir = stack.enter_context(tempfile.TemporaryDirectory())
                with zipfile.ZipFile(io.BytesIO(zf_bytes)) as zf:
                    zf.extractall(workdir)
                sys.path.insert(0, workdir)

        module_path, qualname = spec["function"].split(":", 1)
        func: Any = importlib.import_module(module_path)
        for part in qualname.split("."):
            func = getattr(func, part)
        result = func(**kwargs)

    AnyPath(spec["output_path"]).write_bytes(pickle.dumps(result))
