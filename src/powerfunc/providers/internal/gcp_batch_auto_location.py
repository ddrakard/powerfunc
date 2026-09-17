"""Region selection and diagnostics for GCP Batch: which regions have a GPU, whether a
job's status events show a region is out of capacity, and the job's Cloud Logging output."""

import time
from collections.abc import Iterable
from typing import TYPE_CHECKING

from powerfunc.command_line import ExpectedException

if TYPE_CHECKING:
    from google.cloud import batch_v1

# Regions likely to have the most GPU capacity — tried first in auto mode.
_BIG_REGIONS = (
    "us-central1",
    "us-east1",
    "us-west1",
    "europe-west1",
    "europe-west4",
    "asia-east1",
)

# Batch error codes (reported in status events as "code - CODE_...") meaning no VM can be
# obtained: the zone has no capacity, or the project's quota is used up.
_EXHAUSTION_CODES = (
    "CODE_GCE_ZONE_RESOURCE_POOL_EXHAUSTED",
    "CODE_GCE_STOCKOUT",
    "CODE_GCE_QUOTA_EXCEEDED",
)


def candidate_regions(
    project: str,
    accelerator_name: str,
    machine_type: str | None,
) -> list[str]:
    """Query GCP for regions where both the accelerator and machine type exist.

    Regions likely to have the most GPU capacity come first.
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

    regions = {z.rsplit("-", 1)[0] for z in accel_zones}
    big = [r for r in _BIG_REGIONS if r in regions]
    return big + sorted(regions - set(big))


def has_exhaustion_event(status_events: Iterable["batch_v1.StatusEvent"]) -> bool:
    """Whether any status event indicates the job cannot get a VM (capacity or quota)."""
    return any(
        f"code - {code}" in event.description
        for event in status_events
        for code in _EXHAUSTION_CODES
    )


def format_events(status_events: Iterable["batch_v1.StatusEvent"]) -> str:
    """The last few status events, for error messages."""
    events = list(status_events)
    if not events:
        return ""
    lines = [f"  - [{e.type_}] {e.description}" for e in events[-5:]]
    return "\nRecent status events:\n" + "\n".join(lines)


def read_batch_logs(project: str, region: str, job_name: str) -> str:
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
