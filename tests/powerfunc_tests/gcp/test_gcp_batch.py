"""Live integration tests for GCP Batch remote compute.

These run a real function on GCP via
:class:`powerfunc.providers.gcp_batch.GCPBatchProvider` (Compute Engine VMs via
GCP Batch + GCS for artifact transfer) and assert the returned value.

Skip policy and authentication match the Cloud Run tests in
``test_gcp_cloud_run.py``: skipped **only** when ``GOOGLE_CLOUD_API_KEY`` is absent
or empty; any other unexpected state fails loudly. ``GOOGLE_CLOUD_API_KEY`` must
be a GCP service-account JSON key (used via Application Default Credentials);
``GCP_BUCKET`` is required, the project comes from the JSON (override with
``GCP_PROJECT``) and the region defaults to ``us-central1`` (override with
``GCP_REGION``).
"""

import os

import pytest

from powerfunc.command_line import ExpectedException
from powerfunc.compute import ComputeSpecification
from powerfunc.providers.gcp_batch import GCPBatchProvider
from powerfunc_tests.remote_jobs import gpu_name, remote_add, remote_concat

# Official NVIDIA CUDA 12.1 minimal image (~238 MB, likely cached on GCP's
# mirror.gcr.io).  Ships the CUDA runtime but no Python — the uv-based
# bootstrap auto-installs Python and powerfunc.  ``install_gpu_drivers=True``
# mounts the NVIDIA kernel driver from the host COS VM.
_GPU_IMAGE = "nvidia/cuda:12.1.0-base-ubuntu22.04"

API_KEY = os.environ.get("GOOGLE_CLOUD_API_KEY", "")

# Skip ONLY when the key is absent or empty. A provided-but-wrong key must fail,
# not skip — silently ignoring an unexpected state hides real problems.
pytestmark = pytest.mark.skipif(
    not API_KEY.strip(),
    reason="GOOGLE_CLOUD_API_KEY not set or empty",
)


@pytest.fixture(scope="module")
def provider(gcp_credentials):
    project = os.environ.get("GCP_PROJECT") or gcp_credentials.get("project_id")
    if not project:
        raise ValueError(
            "No GCP project found: set GCP_PROJECT or use a service-account key "
            "that contains project_id."
        )
    bucket = os.environ.get("GCP_BUCKET")
    if not bucket:
        raise ValueError("GCP_BUCKET is required to run the GCP Batch tests (e.g. gs://my-bucket).")
    region = os.environ.get("GCP_REGION", "us-central1")
    return GCPBatchProvider(project=project, region=region, temporary_bucket_path=bucket)


def _spec(provider):
    return ComputeSpecification(
        cpu=1.0, memory=2048, timeout=300.0, image="python:3.12-slim", provider=provider
    )


def test_gcp_batch_returns_value(provider):
    """A powerfunc function runs on GCP Batch and its return value comes back."""
    result = remote_add(2, 3, compute=_spec(provider))
    assert result == 5


def test_gcp_batch_passes_arguments(provider):
    """Arguments are pickled to GCS and delivered to the remote Batch function."""
    result = remote_concat("power", "func", compute=_spec(provider))
    assert result == "powerfunc"


@pytest.fixture(scope="module")
def gpu_provider(provider):
    """A Batch provider using region='auto' to find available L4 capacity.

    Queries GCP for regions with L4 + G2 machines, tries each in order, and
    fails over automatically on capacity exhaustion.
    """
    return GCPBatchProvider(
        project=provider.project,
        region="auto",
        temporary_bucket_path=provider.temporary_bucket_path,
        machine_type="g2-standard-4",
    )


def test_gcp_batch_gpu_is_visible(gpu_provider):
    """A GPU-requested Batch job has an L4 actually visible to the container."""
    spec = ComputeSpecification(
        cpu=4.0, memory=16384, timeout=300.0, image=_GPU_IMAGE, gpu="l4", provider=gpu_provider
    )
    try:
        result = gpu_name(compute=spec)
    except ExpectedException as exc:
        if "exhausted" in str(exc).lower() or "no capacity" in str(exc).lower():
            pytest.skip(f"L4 GPU capacity unavailable across all regions: {exc}")
        raise
    assert "L4" in result
