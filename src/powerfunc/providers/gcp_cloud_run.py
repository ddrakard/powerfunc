from dataclasses import dataclass

from pydantic.dataclasses import dataclass as pydantic_dataclass
from upath import UPath

from powerfunc.command_line import ExpectedException
from powerfunc.compute import (
    ComputeSpecification,
    CpuCount,
    DockerImageUri,
    GpuModel,
    MemorySize,
)
from powerfunc.providers.internal.gcp_shared import GCPJobProvider, bootstrap_command

_SUPPORTED_GPUS = {"t4", "a100", "l4", "v100"}


@dataclass
class GCPCloudRunProvider(GCPJobProvider):
    """Runs functions remotely on GCP Cloud Run Jobs."""

    def _submit_job(
        self,
        job_name: str,
        compute: ComputeSpecification,
        job_spec_path: UPath,
        environment: dict[str, str],
    ) -> None:
        try:
            from google.cloud import run_v2
        except ImportError as e:
            raise ExpectedException(
                "google-cloud-run is not installed. "
                "Install it with: pip install 'powerfunc[gcp]' or uv add 'powerfunc[gcp]'"
            ) from e

        bootstrap = bootstrap_command(job_spec_path)

        env = [run_v2.EnvVar(name=k, value=v) for k, v in environment.items()]

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

        try:
            run_operation = client.run_job(name=f"{parent}/jobs/{job_name}")
            run_operation.result(timeout=compute.timeout)
        finally:
            try:
                client.delete_job(name=f"{parent}/jobs/{job_name}").result()
            except Exception:
                pass


@pydantic_dataclass
class GcpCloudRunCpuSmall(ComputeSpecification):
    """1 vCPU, 2GB RAM, Python 3.12 slim — Cloud Run."""

    cpu: CpuCount = 1.0
    memory: MemorySize = 2048
    image: DockerImageUri = "python:3.12-slim"


@pydantic_dataclass
class GcpCloudRunGpu(ComputeSpecification):
    """4 vCPU, 16GB RAM, L4 GPU — Cloud Run."""

    cpu: CpuCount = 4.0
    memory: MemorySize = 16384
    image: DockerImageUri = "nvidia/cuda:12.1.0-base-ubuntu22.04"
    gpu: GpuModel = "l4"
