"""Live integration tests for GCP Batch remote compute.

These run a real function on GCP via
:class:`powerfunc.providers.gcp_batch.GCPBatchProvider` (Compute Engine VMs via
GCP Batch + GCS for artifact transfer) and assert the returned value.

Authentication: GCP providers authenticate via service-account credentials
(Application Default Credentials), not a bare API key.
``GOOGLE_CLOUD_API_KEY`` must be a GCP service-account JSON key;
``GCP_BUCKET`` is required, the project comes from the JSON (override with
``GCP_PROJECT``) and the region defaults to ``us-central1`` (override with
``GCP_REGION``).
"""

import pytest

from powerfunc.compute import ComputeSpecification
from powerfunc.providers.gcp_batch import GCPBatchProvider
from powerfunc_tests.gcp.gcp_jobs import gpu_name, remote_add, remote_concat
from powerfunc_tests.gcp.gcp_shared import get_project_and_bucket, make_spec

# Official NVIDIA CUDA 12.1 minimal image (~238 MB, likely cached on GCP's
# mirror.gcr.io).  Ships the CUDA runtime but no Python — the uv-based
# bootstrap auto-installs Python and powerfunc.  ``install_gpu_drivers=True``
# mounts the NVIDIA kernel driver from the host COS VM.
_GPU_IMAGE = "nvidia/cuda:12.1.0-base-ubuntu22.04"


@pytest.fixture(scope="module")
def provider(gcp_credentials):
    project, region, bucket = get_project_and_bucket(gcp_credentials)
    return GCPBatchProvider(project=project, region=region, temporary_bucket_path=bucket)


def test_batch_returns_value(provider):
    """A plain function runs on Batch and its return value comes back."""
    result = provider.call(remote_add, {"a": 2, "b": 3}, make_spec(provider))
    assert result == 5


def test_batch_passes_arguments(provider):
    """Arguments are pickled to GCS and delivered to the remote Batch function."""
    result = provider.call(
        remote_concat, {"prefix": "power", "suffix": "func"}, make_spec(provider)
    )
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


def test_batch_gpu_is_visible(gpu_provider):
    """A GPU-requested Batch job has an L4 actually visible to the container."""
    spec = ComputeSpecification(
        cpu=4.0, memory=16384, timeout=300.0, image=_GPU_IMAGE, gpu="l4", provider=gpu_provider
    )
    result = gpu_provider.call(gpu_name, {}, spec)
    assert "L4" in result
