import datetime
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

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
from powerfunc.providers.internal.gcp_batch_auto_location import (
    candidate_regions,
    format_events,
    has_exhaustion_event,
    read_batch_logs,
)
from powerfunc.providers.internal.gcp_shared import GCPJobProvider, bootstrap_command

if TYPE_CHECKING:
    from google.cloud import batch_v1

# GPU model name -> GCP Batch accelerator type.
_GPU_ACCELERATOR_TYPES = {
    "t4": "nvidia-tesla-t4",
    "v100": "nvidia-tesla-v100",
    "a100": "nvidia-tesla-a100",
    "l4": "nvidia-l4",
}

_TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED"})
_POLL_INTERVAL_SECONDS = 3
_QUEUED_TIMEOUT_SECONDS = 20


@dataclass
class GCPBatchProvider(GCPJobProvider):
    """Runs functions remotely on GCP Batch.

    ``machine_type`` is optional — Batch picks a machine from the
    requested CPU/memory when it is not set. Set ``spot=True`` for spot (preemptible) VMs.

    When ``region`` is set to ``"auto"``, the provider queries GCP for all regions
    that support the requested GPU and machine type, then tries each in order.
    If a region's capacity is exhausted (detected via Batch status events), the job
    is cancelled and retried in the next available region.
    """

    machine_type: Optional[str] = None
    spot: bool = False

    def _build_job(
        self,
        compute: ComputeSpecification,
        job_spec_path: UPath,
        environment: dict[str, str],
        error_gcs_path: str = "",
    ) -> "batch_v1.Job":
        from google.cloud import batch_v1

        container = batch_v1.Runnable.Container(
            image_uri=compute.image,
            entrypoint="/bin/sh",
            commands=["-c", bootstrap_command(job_spec_path, error_gcs_path)],
        )
        task_spec = batch_v1.TaskSpec(
            runnables=[batch_v1.Runnable(container=container)],
            compute_resource=batch_v1.ComputeResource(
                cpu_milli=int(compute.cpu * 1000),
                memory_mib=int(compute.memory),
            ),
            max_run_duration=datetime.timedelta(seconds=compute.timeout),
        )
        if environment:
            task_spec.environment = batch_v1.Environment(variables=environment)

        instance_policy = batch_v1.AllocationPolicy.InstancePolicy()
        if self.machine_type:
            instance_policy.machine_type = self.machine_type
        if self.spot:
            instance_policy.provisioning_model = batch_v1.AllocationPolicy.ProvisioningModel.SPOT
        if compute.gpu:
            accelerator_type = _GPU_ACCELERATOR_TYPES.get(compute.gpu)
            if accelerator_type is None:
                raise ExpectedException(
                    f"Unsupported GPU: {compute.gpu!r}. Supported: {sorted(_GPU_ACCELERATOR_TYPES)}"
                )
            instance_policy.accelerators = [
                batch_v1.AllocationPolicy.Accelerator(type_=accelerator_type, count=1)
            ]
        # install_gpu_drivers installs the NVIDIA *kernel driver* on the host
        # VM (required for GPU access).  CUDA container images provide the
        # toolkit/runtime, not the kernel driver — the two are complementary.
        install_gpu_drivers = bool(compute.gpu)
        instances = batch_v1.AllocationPolicy.InstancePolicyOrTemplate(
            policy=instance_policy,
            install_gpu_drivers=install_gpu_drivers,
        )

        return batch_v1.Job(
            task_groups=[batch_v1.TaskGroup(task_spec=task_spec, task_count=1)],
            allocation_policy=batch_v1.AllocationPolicy(instances=[instances]),
            logs_policy=batch_v1.LogsPolicy(
                destination=batch_v1.LogsPolicy.Destination.CLOUD_LOGGING
            ),
        )

    def _submit_job(
        self,
        job_name: str,
        compute: ComputeSpecification,
        job_spec_path: UPath,
        environment: dict[str, str],
    ):
        if self.region == "auto":
            self._submit_job_auto(job_name, compute, job_spec_path, environment)
        else:
            self._submit_job_to_region(job_name, compute, job_spec_path, environment, self.region)

    def _submit_job_auto(
        self,
        job_name: str,
        compute: ComputeSpecification,
        job_spec_path: UPath,
        environment: dict[str, str],
    ):
        """Submit with automatic region selection and failover on exhaustion."""
        accelerator_name = None
        if compute.gpu:
            accelerator_name = _GPU_ACCELERATOR_TYPES.get(compute.gpu)
            if accelerator_name is None:
                raise ExpectedException(
                    f"Unsupported GPU: {compute.gpu!r}. Supported: {sorted(_GPU_ACCELERATOR_TYPES)}"
                )

        if accelerator_name:
            regions = candidate_regions(self.project, accelerator_name, self.machine_type)
        else:
            # Without a GPU requirement, we can't meaningfully auto-select.
            raise ExpectedException(
                "region='auto' requires a GPU in the ComputeSpecification. "
                "For CPU-only jobs, specify a region explicitly."
            )

        if not regions:
            raise ExpectedException(
                f"No regions found with accelerator {accelerator_name!r}"
                + (f" and machine type {self.machine_type!r}" if self.machine_type else "")
                + f" in project {self.project!r}."
            )

        exhausted_regions: list[str] = []
        for region in regions:
            try:
                self._submit_job_to_region(
                    job_name,
                    compute,
                    job_spec_path,
                    environment,
                    region,
                    early_exhaustion_detection=True,
                )
                return  # Success
            except _RegionExhaustedException:
                exhausted_regions.append(region)
                # Generate a new job name for the next attempt (Batch requires unique names).
                ts = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
                job_name = f"pf-{ts}-{abs(hash(region)) % 1000000:06d}--output"
                continue

        raise ExpectedException(
            f"All candidate regions exhausted for GPU {compute.gpu!r}: "
            f"{exhausted_regions}. No capacity available."
        )

    def _submit_job_to_region(
        self,
        job_name: str,
        compute: ComputeSpecification,
        job_spec_path: UPath,
        environment: dict[str, str],
        region: str,
        early_exhaustion_detection: bool = False,
    ):
        """Submit a job to a specific region and poll until completion."""
        import json as _json

        from google.cloud import batch_v1

        # Construct error capture path from the job spec's output_path.
        error_gcs_path = ""
        try:
            _spec = _json.loads(job_spec_path.read_bytes().decode())
            error_gcs_path = _spec["output_path"] + "__error"
        except Exception:
            pass

        job = self._build_job(compute, job_spec_path, environment, error_gcs_path=error_gcs_path)
        client = batch_v1.BatchServiceClient()
        parent = f"projects/{self.project}/locations/{region}"
        created = client.create_job(parent=parent, job=job, job_id=job_name)

        # The job is deleted on every exit path (success, failure, timeout, interrupt),
        # otherwise a still-running job keeps its VM, and any GPU quota, occupied.
        try:
            job_status = self._poll(
                client, created.name, job_name, compute, region, early_exhaustion_detection
            )
        finally:
            try:
                client.delete_job(name=created.name)
            except Exception:
                pass

        state = job_status.state.name
        if state == "FAILED":
            events_summary = format_events(job_status.status_events)
            remote_output = ""
            if error_gcs_path:
                for _ in range(10):
                    time.sleep(2)
                    try:
                        remote_output = (
                            "\nRemote output:\n" + UPath(error_gcs_path).read_bytes().decode()
                        )
                        break
                    except Exception as read_exc:
                        remote_output = f"\n(Error blob read failed: {read_exc})"
            # Fall back to Cloud Logging for the container's stdout/stderr.
            if "(Error blob read failed" in remote_output:
                cloud_logs = read_batch_logs(self.project, region, created.name)
                remote_output += cloud_logs
            raise ExpectedException(
                f"GCP Batch job {job_name!r} failed in region {region!r}."
                f"{events_summary}{remote_output}"
            )

    @staticmethod
    def _poll(
        client: "batch_v1.BatchServiceClient",
        name: str,
        job_name: str,
        compute: ComputeSpecification,
        region: str,
        early_exhaustion_detection: bool,
    ) -> "batch_v1.JobStatus":
        """Poll until the job reaches a terminal state, raising on stalls and timeouts."""
        deadline = time.monotonic() + compute.timeout
        submitted_at = time.monotonic()
        while True:
            job_status = client.get_job(name=name).status
            state = job_status.state.name
            if state in _TERMINAL_STATES:
                return job_status

            exhausted = has_exhaustion_event(job_status.status_events)
            queued_too_long = (
                state == "QUEUED" and time.monotonic() - submitted_at > _QUEUED_TIMEOUT_SECONDS
            )
            timed_out = time.monotonic() > deadline
            if not (exhausted or queued_too_long or timed_out):
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue

            if early_exhaustion_detection:
                raise _RegionExhaustedException(region)
            events_summary = format_events(job_status.status_events)
            if exhausted:
                problem = "cannot get a VM (capacity or quota)"
            elif queued_too_long:
                problem = f"still QUEUED after {_QUEUED_TIMEOUT_SECONDS}s"
            else:
                problem = f"did not complete within {compute.timeout:.0f}s (last state: {state!r})"
            raise ExpectedException(
                f"GCP Batch job {job_name!r} {problem} in region {region!r}.{events_summary}"
            )


class _RegionExhaustedException(Exception):
    """Internal signal: a region's GPU capacity is exhausted."""

    def __init__(self, region: str):
        self.region = region
        super().__init__(f"Region {region!r} capacity exhausted")


@pydantic_dataclass
class GcpBatchCpuSmall(ComputeSpecification):
    """1 vCPU, 2GB RAM, Python 3.12 slim — Batch."""

    cpu: CpuCount = 1.0
    memory: MemorySize = 2048
    image: DockerImageUri = "python:3.12-slim"


@pydantic_dataclass
class GcpBatchGpu(ComputeSpecification):
    """4 vCPU, 16GB RAM, L4 GPU — Batch."""

    cpu: CpuCount = 4.0
    memory: MemorySize = 16384
    image: DockerImageUri = "nvidia/cuda:12.1.0-base-ubuntu22.04"
    gpu: GpuModel = "l4"
