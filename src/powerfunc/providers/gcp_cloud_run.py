import collections.abc
import contextlib
import importlib
import inspect
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
from powerfunc.compute import (
    ComputeSpecification,
    CpuCount,
    DockerImageUri,
    GpuModel,
    MemorySize,
    Provider,
    user_identifier,
)

_SUPPORTED_GPUS = {"t4", "a100", "l4", "v100"}
_MAX_JOB_NAME_LENGTH = 63  # GCP resource name limit (Cloud Run and Batch)


def _bootstrap_command(job_spec_path: "AnyPath", error_gcs_path: str = "") -> str:
    """Shell command run in the remote container to install powerfunc and execute the job.

    Uses `uv <https://docs.astral.sh/uv/>`_ as the universal package manager.
    The bootstrap first ensures ``uv`` is available via a fallback chain (check
    existing → curl → wget → pip → apt-get install curl), then uses
    ``uv run`` which handles everything in one shot: creates an ephemeral
    environment, downloads Python if needed, installs dependencies, and runs.

    Requires at least one of: ``curl``, ``wget``, ``pip``, or
    ``apt-get`` (to install ``curl``).

    If *error_gcs_path* is provided, on failure the **entire** output
    (including the install step) is uploaded to GCS via ``gsutil``, ``curl``,
    or Python ``urllib``.
    """
    # Extend PATH so that uv, Cloud SDK, and system tools are all reachable.
    path_prefix = (
        'export PATH="$HOME/.local/bin:/usr/local/bin:/snap/google-cloud-sdk/current/bin:$PATH"; '
    )
    # Universal uv acquisition: try each method until one works.
    _uv_url = "https://astral.sh/uv/install.sh"
    get_uv = (
        "{ command -v uv >/dev/null 2>&1 || "
        "{ command -v curl >/dev/null 2>&1 && curl -LsSf " + _uv_url + " | sh; } || "
        "{ command -v wget >/dev/null 2>&1 && wget -qO- " + _uv_url + " | sh; } || "
        "{ command -v pip >/dev/null 2>&1 && pip install uv -q; } || "
        "{ apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq curl >/dev/null 2>&1 "
        "&& curl -LsSf " + _uv_url + " | sh; }; }"
    )
    # uv run handles everything: ephemeral env, Python download, install, execute.
    run_cmd = (
        f'uv run --with powerfunc --with "pydantic>=2" '
        f"python -m powerfunc.providers.gcp_cloud_run {job_spec_path}"
    )
    main_cmd = get_uv + " && " + run_cmd
    if error_gcs_path:
        import urllib.parse

        gcs_no_prefix = error_gcs_path.replace("gs://", "", 1)
        bucket, _, obj_name = gcs_no_prefix.partition("/")
        encoded_name = urllib.parse.quote(obj_name, safe="")
        upload_url = (
            f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}"
            f"/o?uploadType=media&name={encoded_name}"
        )
        py_upload = (
            "import json,urllib.request,sys;"
            "t=json.loads(urllib.request.urlopen(urllib.request.Request("
            '"http://metadata.google.internal/computeMetadata/v1/instance/'
            'service-accounts/default/token",'
            'headers={"Metadata-Flavor":"Google"})).read())["access_token"];'
            'd=open("/tmp/pf_out.txt","rb").read();'
            "urllib.request.urlopen(urllib.request.Request(sys.argv[1],"
            'data=d,method="POST",'
            'headers={"Authorization":"Bearer "+t,'
            '"Content-Type":"application/octet-stream"}))'
        )

        # curl-based upload using GCE metadata server token (no Python needed).
        curl_upload = (
            'PF_TOKEN=$(curl -sf -H "Metadata-Flavor: Google" '
            '"http://metadata.google.internal/computeMetadata/v1/instance/'
            'service-accounts/default/token" '
            '| grep -o \'"access_token":"[^"]*"\' | cut -d\'"\' -f4) && '
            'curl -sf -H "Authorization: Bearer $PF_TOKEN" '
            '-H "Content-Type: application/octet-stream" '
            f"--data-binary @/tmp/pf_out.txt '{upload_url}'"
        )

        return (
            path_prefix + f"({main_cmd}) > /tmp/pf_out.txt 2>&1; "
            "PF_RC=$?; cat /tmp/pf_out.txt; "
            "if [ $PF_RC -ne 0 ]; then "
            f"gsutil cp /tmp/pf_out.txt {error_gcs_path} 2>/dev/null || "
            f"{curl_upload} 2>/dev/null || "
            f"python3 -c '{py_upload}' '{upload_url}' 2>/dev/null || "
            f"python -c '{py_upload}' '{upload_url}' 2>/dev/null || "
            "true; fi; exit $PF_RC"
        )
    return path_prefix + main_cmd


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
class GCPCloudRunProvider(Provider):
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

    def _zip_codebase(
        self, extra_prefixes: Optional[list[str]] = None
    ) -> tuple[Optional[bytes], Optional[pathlib.Path]]:
        """Zip all git-tracked files from the repo, if one can be found.

        When *extra_prefixes* are given (e.g. ``["tests"]``), files under
        those directories are also added **without** the prefix so that
        modules importable via ``pythonpath`` locally are also importable
        on the remote after a plain ``sys.path.insert(0, workdir)``.

        Returns ``(zip_bytes, repo_root)`` or ``(None, None)``.
        """
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
            return None, None
        repo_root = pathlib.Path(result.stdout.strip())
        files = subprocess.check_output(["git", "ls-files"], cwd=repo_root).decode().splitlines()
        prefixes = [p.rstrip("/") + "/" for p in (extra_prefixes or [])]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in files:
                zf.write(repo_root / file, arcname=file)
                for pfx in prefixes:
                    if file.startswith(pfx):
                        zf.write(repo_root / file, arcname=file[len(pfx) :])
        return buffer.getvalue(), repo_root

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
                "Install it with: pip install 'powerfunc[gcp]' or uv add 'powerfunc[gcp]'"
            ) from e

        bootstrap = _bootstrap_command(job_spec_path)

        env = [run_v2.EnvVar(name=k, value=v) for k, v in self.environment_variables.items()]

        resources = {"cpu": str(compute.cpu), "memory": f"{compute.memory}Mi"}
        node_selector = None
        if compute.gpu:
            if compute.gpu not in _SUPPORTED_GPUS:
                raise ExpectedException(
                    f"Unsupported GPU: {compute.gpu!r}. Supported: {sorted(_SUPPORTED_GPUS)}"
                )
            resources["nvidia.com/gpu"] = "1"
            node_selector = run_v2.NodeSelector(accelerator=f"nvidia-{compute.gpu}")

        task_template = run_v2.TaskTemplate(
            containers=[
                run_v2.Container(
                    image=compute.image,
                    command=["sh", "-c"],
                    args=[bootstrap],
                    env=env,
                    resources=run_v2.ResourceRequirements(limits=resources),
                )
            ],
            node_selector=node_selector,
        )
        # Only valid when a GPU is requested; setting it otherwise makes Cloud Run
        # reject the job ("GPU type or GPU requirements must be set when GPU
        # redundancy is set").
        if compute.gpu:
            task_template.gpu_zonal_redundancy_disabled = True

        job = run_v2.Job(template=run_v2.ExecutionTemplate(template=task_template))

        client = run_v2.JobsClient()
        parent = f"projects/{self.project}/locations/{self.region}"
        operation = client.create_job(parent=parent, job=job, job_id=job_name)
        operation.result()

        run_operation = client.run_job(name=f"{parent}/jobs/{job_name}")
        run_operation.result(timeout=compute.timeout)

        try:
            client.delete_job(name=f"{parent}/jobs/{job_name}").result()
        except Exception:
            pass

    @staticmethod
    def _extra_sys_paths(function: Callable, repo_root: Optional[pathlib.Path]) -> list[str]:
        """Relative directories that must be added to sys.path on the remote.

        Compares the function's source file to its module name to discover
        path prefixes (like ``tests/``) that the local environment has on
        sys.path but wouldn't exist on the remote after a bare zip extract.
        """
        if repo_root is None:
            return []
        try:
            src = pathlib.Path(inspect.getfile(function)).resolve()
            rel = src.relative_to(repo_root)
        except (TypeError, ValueError):
            return []
        # Expected file suffix from module name: powerfunc_tests/gcp/gcp_jobs.py
        module_parts = function.__module__.split(".")
        module_tail = pathlib.Path(*module_parts).with_suffix(".py")
        rel_str = str(rel)
        tail_str = str(module_tail)
        if rel_str.endswith(tail_str):
            prefix = rel_str[: -len(tail_str)].rstrip("/").rstrip(os.sep)
            if prefix:
                return [prefix]
        return []

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
        codebase, repo_root = self._zip_codebase()
        extra_prefixes = self._extra_sys_paths(function, repo_root)
        if extra_prefixes:
            codebase, repo_root = self._zip_codebase(extra_prefixes=extra_prefixes)

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
class GcpCloudRunCpuSmall(ComputeSpecification):
    """1 vCPU, 2GB RAM, Python 3.12 slim — for GCP Cloud Run."""

    cpu: CpuCount = 1.0
    memory: MemorySize = 2048
    image: DockerImageUri = "python:3.12-slim"


@pydantic_dataclass
class GcpCloudRunGpu(ComputeSpecification):
    """4 vCPU, 16GB RAM, L4 GPU — for GCP Cloud Run."""

    cpu: CpuCount = 4.0
    memory: MemorySize = 16384
    image: DockerImageUri = "nvidia/cuda:12.1.0-base-ubuntu22.04"
    gpu: GpuModel = "l4"


if __name__ == "__main__":
    import traceback as _tb

    job_spec_path = AnyPath(sys.argv[1])
    spec = json.loads(job_spec_path.read_bytes().decode())

    try:
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
    except BaseException as exc:
        # Write the error to a sibling path so the caller can retrieve it.
        error_info = f"{type(exc).__name__}: {exc}\n{_tb.format_exc()}"
        try:
            AnyPath(spec["output_path"] + "__error").write_bytes(error_info.encode())
        except Exception:
            pass
        raise
