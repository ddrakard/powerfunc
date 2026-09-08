"""Live integration tests for GCP Cloud Run Jobs remote compute (with GCS).

These run a real function on GCP via :class:`powerfunc.providers.gcp_cloud_run.GCPCloudRunProvider`
and assert the returned value.

Skip policy: the tests are **skipped only** when ``GOOGLE_CLOUD_API_KEY`` is
absent or an empty string. If a key *is* provided, it must be usable — any
unexpected state (not valid JSON, not a service-account key, missing
bucket/project, or GCP auth/run errors) fails loudly rather than skipping.

Authentication: Cloud Run Jobs and Cloud Storage authenticate via
service-account credentials (Application Default Credentials), not a bare API
key. ``GOOGLE_CLOUD_API_KEY`` must therefore contain a GCP service-account
**JSON key**; the test writes it to a temp file and points
``GOOGLE_APPLICATION_CREDENTIALS`` at it. A live run also needs a writable
bucket (``GCP_BUCKET``); the project is taken from the JSON (override with
``GCP_PROJECT``) and the region defaults to ``us-central1`` (override with
``GCP_REGION``).
"""

import os
import pathlib

import pytest
from cloudpathlib import AnyPath

from powerfunc.compute import ComputeSpecification
from powerfunc.providers.gcp_cloud_run import GCPCloudRunProvider
from powerfunc_tests.remote_jobs import csv_sum, gpu_name, remote_add, remote_concat

DATA_DIR = pathlib.Path(__file__).parents[1] / "data"

# NVIDIA CUDA minimal image (~238 MB, ships nvidia-smi + CUDA runtime).
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
        raise ValueError(
            "GCP_BUCKET is required to run the GCP remote tests (e.g. gs://my-bucket)."
        )
    region = os.environ.get("GCP_REGION", "us-central1")
    return GCPCloudRunProvider(project=project, region=region, temporary_bucket_path=bucket)


def _spec(provider):
    return ComputeSpecification(
        cpu=1.0, memory=2048, timeout=300.0, image="python:3.12-slim", provider=provider
    )


def test_gcp_cloud_run_remote_returns_value(provider):
    """A powerfunc function runs on Cloud Run and its return value comes back."""
    result = remote_add(2, 3, compute=_spec(provider))
    assert result == 5


def test_gcp_cloud_run_remote_passes_arguments(provider):
    """Arguments are pickled to GCS and delivered to the remote function, via ``compute=``."""
    result = remote_concat("power", "func", compute=_spec(provider))
    assert result == "powerfunc"


def test_gcp_cloud_run_remote_reads_a_file(provider):
    """A ``gs://`` path given for a file-typed parameter is opened on the compute."""
    csv_path = AnyPath(provider.temporary_bucket_path) / "powerfunc" / "test_data.csv"
    csv_path.write_bytes((DATA_DIR / "data.csv").read_bytes())
    try:
        assert csv_sum(str(csv_path), compute=_spec(provider)) == 1 + 2 + 3
    finally:
        csv_path.unlink()


def test_gcp_cloud_run_remote_gpu_is_visible(provider):
    """A GPU-requested Cloud Run job has an L4 actually visible to the container."""
    # Cloud Run L4 requires >= 4 vCPU / 16 GiB.
    spec = ComputeSpecification(
        cpu=4.0, memory=16384, timeout=300.0, image=_GPU_IMAGE, gpu="l4", provider=provider
    )
    assert "L4" in gpu_name(compute=spec)
