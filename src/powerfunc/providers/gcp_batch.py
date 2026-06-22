import datetime
import time
from dataclasses import dataclass
from typing import Any, Optional

from cloudpathlib import AnyPath
from pydantic.dataclasses import dataclass as pydantic_dataclass

from powerfunc.command_line import ExpectedException
from powerfunc.compute import ComputeSpecification, CpuCount, DockerImageUri, GpuModel, MemorySize
from powerfunc.providers.gcp_cloud_run import GCPCloudRunProvider, _bootstrap_command

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

# Regions likely to have the most GPU capacity — tried first in auto mode.
_BIG_REGIONS = (
    "us-central1",
    "us-east1",
    "us-west1",
    "europe-west1",
    "europe-west4",
    "asia-east1",
)

# Status event substrings that indicate zone/region capacity exhaustion.
_EXHAUSTION_SIGNALS = (
    "RESOURCE_POOL_EXHAUSTED",
    "STOCKOUT",
    "was not found",
    "not available",
)


def _find_candidate_regions(
    project: str,
    accelerator_name: str,
    machine_type: Optional[str],
) -> list[str]:
    """Query GCP for regions where both the accelerator and machine type exist.

    Returns a list of region strings (e.g. ["us-central1", "europe-west4"]).
    """
    try:
        from google.cloud.compute_v1 import AcceleratorTypesClient, MachineTypesClient
    except ImportError as e:
        raise ExpectedException(
            "google-cloud-compute is not installed. "
            "Install it with: pip install 'powerfunc[gcp]' or uv add 'powerfunc[gcp]'"
        ) from e

    # Find zones that have the requested accelerator.
    accel_client = AcceleratorTypesClient()
    accel_zones: set[str] = set()
    for zone_scope, scoped_list in accel_client.aggregated_list(project=project):
        if not zone_scope.startswith("zones/"):
            continue
        zone = zone_scope.removeprefix("zones/")
        for accel in scoped_list.accelerator_types or []:
            if accel.name == accelerator_name:
                accel_zones.add(zone)
                break

    if not accel_zones:
        return []

    # If machine_type is set, intersect with zones that have it.
    if machine_type:
        machine_family = machine_type.rsplit("-", 1)[0] if "-" in machine_type else machine_type
        mt_client = MachineTypesClient()
        mt_zones: set[str] = set()
        for zone_scope, scoped_list in mt_client.aggregated_list(project=project):
            if not zone_scope.startswith("zones/"):
                continue
            zone = zone_scope.removeprefix("zones/")
            for mt in scoped_list.machine_types or []:
                if mt.name == machine_type or mt.name.startswith(machine_family):
                    mt_zones.add(zone)
                    break
        accel_zones &= mt_zones

    # Extract unique regions from the zone names.
    regions: list[str] = sorted({z.rsplit("-", 1)[0] for z in accel_zones})
    return regions


def _has_exhaustion_event(status_events: Any) -> bool:
    """Check if any status event indicates zone/region capacity exhaustion."""
    for event in status_events or []:
        desc = getattr(event, "description", "") or ""
        if any(signal in desc for signal in _EXHAUSTION_SIGNALS):
            return True
    return False


def _format_events(status_events: Any) -> str:
    """Format the last few status events for error messages."""
    try:
        events = list(status_events or [])
        if events:
            lines = [f"  - [{e.type_}] {e.description}" for e in events[-5:]]
            return "\nRecent status events:\n" + "\n".join(lines)
    except Exception:
        pass
    return ""


def _read_batch_logs(project: str, region: str, job_name: str) -> str:
    """Read container stdout/stderr from Cloud Logging for a Batch job.

    Returns a formatted string with the log entries, or an error note.
    Uses the Cloud Logging REST API with google-auth — no extra dependencies.
    Polls the Logging API for up to 15s until entries appear.
    """
    try:
        import json as _json
        import urllib.request

        import google.auth
        import google.auth.transport.requests

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(google.auth.transport.requests.Request())

        # GCP Batch logs use resource.labels.job_id (the job name).
        # Extract the short job name from the fully-qualified resource path.
        short_name = job_name.rsplit("/", 1)[-1] if "/" in job_name else job_name
        filter_str = (
            f'resource.type="batch.googleapis.com/Job" resource.labels.job_id="{short_name}"'
        )
        body = _json.dumps(
            {
                "resourceNames": [f"projects/{project}"],
                "filter": filter_str,
                "orderBy": "timestamp asc",
                "pageSize": 200,
            }
        ).encode()
        req = urllib.request.Request(
            "https://logging.googleapis.com/v2/entries:list",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            },
        )
        prev_count = -1
        entries = []
        for _ in range(10):
            time.sleep(3)
            resp = urllib.request.urlopen(req, timeout=10)
            data = _json.loads(resp.read())
            entries = data.get("entries", [])
            if len(entries) > 0 and len(entries) == prev_count:
                break
            prev_count = len(entries)
        if not entries:
            return (
                f"\n(No Cloud Logging entries found for job_id={short_name} in project={project})"
            )
        lines = []
        for entry in entries:
            msg = entry.get("textPayload", "")
            if not msg and "jsonPayload" in entry:
                msg = _json.dumps(entry["jsonPayload"])
            if msg:
                lines.append(msg)
        if lines:
            return "\nCloud Logging output:\n" + "\n".join(lines[-50:])
        return "\n(Cloud Logging entries found but no text payload)"
    except Exception as exc:
        return f"\n(Could not read Cloud Logging: {exc})"


@dataclass
class GCPBatchProvider(GCPCloudRunProvider):
    """Runs functions remotely on GCP Batch.

    Reuses the bucket-based artifact transfer of :class:`GCPCloudRunProvider`; only the job
    submission differs. ``machine_type`` is optional — Batch picks a machine from the
    requested CPU/memory when it is not set. Set ``spot=True`` for spot (preemptible) VMs.

    When ``region`` is set to ``"auto"``, the provider queries GCP for all regions
    that support the requested GPU and machine type, then tries each in order.
    If a region's capacity is exhausted (detected via Batch status events), the job
    is cancelled and retried in the next available region.
    """

    machine_type: Optional[str] = None
    spot: bool = False

    def _build_job(
        self, compute: ComputeSpecification, job_spec_path: AnyPath, error_gcs_path: str = ""
    ) -> Any:
        from google.cloud import batch_v1

        container = batch_v1.Runnable.Container(
            image_uri=compute.image,
            entrypoint="/bin/sh",
            commands=["-c", _bootstrap_command(job_spec_path, error_gcs_path=error_gcs_path)],
        )
        task_spec = batch_v1.TaskSpec(
            runnables=[batch_v1.Runnable(container=container)],
            compute_resource=batch_v1.ComputeResource(
                cpu_milli=int(compute.cpu * 1000),
                memory_mib=int(compute.memory),
            ),
        )
        if self.environment_variables:
            task_spec.environment = batch_v1.Environment(variables=dict(self.environment_variables))

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

    def _submit_job(self, job_name: str, compute: ComputeSpecification, job_spec_path: AnyPath):
        if self.region == "auto":
            self._submit_job_auto(job_name, compute, job_spec_path)
        else:
            self._submit_job_to_region(job_name, compute, job_spec_path, self.region)

    def _submit_job_auto(
        self, job_name: str, compute: ComputeSpecification, job_spec_path: AnyPath
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
            regions = _find_candidate_regions(self.project, accelerator_name, self.machine_type)
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

        big = [r for r in _BIG_REGIONS if r in regions]
        others = sorted(r for r in regions if r not in _BIG_REGIONS)
        regions = big + others

        exhausted_regions: list[str] = []
        for region in regions:
            try:
                self._submit_job_to_region(
                    job_name, compute, job_spec_path, region, early_exhaustion_detection=True
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
        job_spec_path: AnyPath,
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

        job = self._build_job(compute, job_spec_path, error_gcs_path=error_gcs_path)
        client = batch_v1.BatchServiceClient()
        parent = f"projects/{self.project}/locations/{region}"
        created = client.create_job(parent=parent, job=job, job_id=job_name)

        deadline = time.monotonic() + compute.timeout
        submitted_at = time.monotonic()
        while True:
            job_status = client.get_job(name=created.name).status
            state = job_status.state.name
            if state in _TERMINAL_STATES:
                break

            # Early detection: if capacity is exhausted, cancel and signal failover.
            if early_exhaustion_detection and _has_exhaustion_event(job_status.status_events):
                try:
                    client.delete_job(name=created.name)
                except Exception:
                    pass
                raise _RegionExhaustedException(region)

            # If still QUEUED after 20s, the scheduler hasn't picked up the job.
            if state == "QUEUED" and time.monotonic() - submitted_at > _QUEUED_TIMEOUT_SECONDS:
                try:
                    client.delete_job(name=created.name)
                except Exception:
                    pass
                if early_exhaustion_detection:
                    raise _RegionExhaustedException(region)
                events_summary = _format_events(job_status.status_events)
                raise ExpectedException(
                    f"GCP Batch job {job_name!r} still QUEUED after "
                    f"{_QUEUED_TIMEOUT_SECONDS}s in region {region!r}."
                    f"{events_summary}"
                )

            if time.monotonic() > deadline:
                try:
                    client.delete_job(name=created.name)
                except Exception:
                    pass
                if early_exhaustion_detection:
                    raise _RegionExhaustedException(region)
                events_summary = _format_events(job_status.status_events)
                raise ExpectedException(
                    f"GCP Batch job {job_name!r} did not complete within "
                    f"{compute.timeout:.0f}s (last state: {state!r})."
                    f"{events_summary}"
                )
            time.sleep(_POLL_INTERVAL_SECONDS)

        if state == "FAILED":
            events_summary = _format_events(job_status.status_events)
            remote_output = ""
            if error_gcs_path:
                for _ in range(10):
                    time.sleep(2)
                    try:
                        remote_output = (
                            "\nRemote output:\n" + AnyPath(error_gcs_path).read_bytes().decode()
                        )
                        break
                    except Exception as read_exc:
                        remote_output = f"\n(Error blob read failed: {read_exc})"
            # Fall back to Cloud Logging for the container's stdout/stderr.
            if "(Error blob read failed" in remote_output:
                cloud_logs = _read_batch_logs(self.project, region, created.name)
                remote_output += cloud_logs
            raise ExpectedException(
                f"GCP Batch job {job_name!r} failed in region {region!r}."
                f"{events_summary}{remote_output}"
            )

        try:
            client.delete_job(name=created.name)
        except Exception:
            pass


class _RegionExhaustedException(Exception):
    """Internal signal: a region's GPU capacity is exhausted."""

    def __init__(self, region: str):
        self.region = region
        super().__init__(f"Region {region!r} capacity exhausted")


@pydantic_dataclass
class GcpBatchCpuSmall(ComputeSpecification):
    """1 vCPU, 2GB RAM, Python 3.12 slim — for GCP Batch."""

    cpu: CpuCount = 1.0
    memory: MemorySize = 2048
    image: DockerImageUri = "python:3.12-slim"


@pydantic_dataclass
class GcpBatchGpu(ComputeSpecification):
    """4 vCPU, 16GB RAM, L4 GPU — for GCP Batch."""

    cpu: CpuCount = 4.0
    memory: MemorySize = 16384
    image: DockerImageUri = "nvidia/cuda:12.1.0-base-ubuntu22.04"
    gpu: GpuModel = "l4"
