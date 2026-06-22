"""Live integration tests for GCP Cloud Run remote compute.

These run a real function on GCP via :class:`powerfunc.providers.gcp_cloud_run.GCPCloudRunProvider`
and assert the returned value.

Authentication: GCP providers authenticate via service-account credentials
(Application Default Credentials), not a bare API key.
``GOOGLE_CLOUD_API_KEY`` must contain a GCP service-account **JSON key**;
the test writes it to a temp file and points ``GOOGLE_APPLICATION_CREDENTIALS``
at it. A live run also needs a writable bucket (``GCP_BUCKET``); the project is
taken from the JSON (override with ``GCP_PROJECT``) and the region defaults to
``us-central1`` (override with ``GCP_REGION``).
"""

import pytest

from powerfunc.compute import ComputeSpecification
from powerfunc.providers.gcp_cloud_run import GCPCloudRunProvider
from powerfunc_tests.gcp.gcp_jobs import gpu_name, remote_add, remote_concat
from powerfunc_tests.gcp.gcp_shared import get_project_and_bucket, make_spec

# NVIDIA CUDA minimal image (~238 MB, ships nvidia-smi + CUDA runtime).
_GPU_IMAGE = "nvidia/cuda:12.1.0-base-ubuntu22.04"


@pytest.fixture(scope="module")
def provider(gcp_credentials):
    project, region, bucket = get_project_and_bucket(gcp_credentials)
    return GCPCloudRunProvider(project=project, region=region, temporary_bucket_path=bucket)


def test_cloud_run_returns_value(provider):
    """A plain function runs on Cloud Run and its return value comes back."""
    result = provider.call(remote_add, {"a": 2, "b": 3}, make_spec(provider))
    assert result == 5


def test_cloud_run_passes_arguments(provider):
    """Arguments are pickled to GCS and delivered to the remote function."""
    result = provider.call(
        remote_concat, {"prefix": "power", "suffix": "func"}, make_spec(provider)
    )
    assert result == "powerfunc"


def test_cloud_run_gpu_is_visible(provider):
    """A GPU-requested Cloud Run job has an L4 actually visible to the container."""
    # Cloud Run L4 requires >= 4 vCPU / 16 GiB.
    spec = ComputeSpecification(
        cpu=4.0, memory=16384, timeout=300.0, image=_GPU_IMAGE, gpu="l4", provider=provider
    )
    assert "L4" in provider.call(gpu_name, {}, spec)
