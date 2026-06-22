# Google Cloud Platform

powerfunc supports two GCP execution backends: [Cloud Run Jobs](https://cloud.google.com/run/docs/create-jobs) and [Batch](https://cloud.google.com/batch/docs). Both use the same authentication, bucket-based data transfer, and `ComputeSpecification` model.

## Contents

- [Installation](#installation)
- [Setup and configuration](#setup-and-configuration)
- [Cloud Run](#cloud-run)
- [Batch](#batch)
- [Environment variables](#environment-variables)
- [Predefined configurations](#predefined-configurations)
- [Supported GPUs](#supported-gpus)
- [Limitations](#limitations)

## Installation

Make sure to install with the `gcp` option.

```sh
pip install 'powerfunc[gcp]'
```

or

```sh
uv add 'powerfunc[gcp]'
```

## Setup

You need to have a Google Cloud account with a project inside it where the remote execution can happen. You must authenticate with the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) using:

```sh
gcloud auth application-default login
```

powerfunc transfers data in and out of the compute job using a [Google Cloud Storage bucket](https://docs.cloud.google.com/storage/docs/buckets). Therefore, you need to have or create a bucket that powerfunc can use, and provide these details.

### Command line usage

When runnng from the command line, [module-style invocation](https://docs.python.org/3/using/cmdline.html#cmdoption-m) `python -m my.module` must be used instead of direct script execution `python myscript.py`.

## Cloud Run

Cloud Run Jobs is a serverless execution backend. It scales to zero, has fast cold starts for cached images, and supports GPUs.

Configure in `powerfunc.yaml`:

```yaml
compute:
  class_path: powerfunc.providers.gcp_cloud_run.GcpCloudRunCpuSmall
  init_args:
    timeout: 600
    provider:
      class_path: powerfunc.providers.gcp_cloud_run.GCPCloudRunProvider
      init_args:
        project: my-gcp-project
        region: us-central1
        temporary_bucket_path: gs://my-bucket/powerfunc-temp
```

Or directly in Python:

```python
from powerfunc.providers.gcp_cloud_run import GCPCloudRunProvider, GcpCloudRunCpuSmall

provider = GCPCloudRunProvider(
    project="my-gcp-project",
    region="us-central1",
    temporary_bucket_path="gs://my-bucket/",
)
compute = GcpCloudRunCpuSmall(timeout=600, provider=provider)

result = sum_col("gs://bucket/data.csv", compute=compute)
```

Cloud Run Jobs can require some time to start, particularly for a docker image that has not been used recently.

## Batch

Batch provisions Compute Engine VMs. It supports GPUs, higher resource limits than Cloud Run, spot (preemptible) VMs, and explicit machine type selection.

Configure in `powerfunc.yaml`:

```yaml
compute:
  class_path: powerfunc.providers.gcp_batch.GcpBatchCpuSmall
  init_args:
    timeout: 600
    provider:
      class_path: powerfunc.providers.gcp_batch.GCPBatchProvider
      init_args:
        project: my-gcp-project
        region: us-central1
        temporary_bucket_path: gs://my-bucket/powerfunc-temp
```

Or directly in Python:

```python
from powerfunc.providers.gcp_batch import GCPBatchProvider, GcpBatchCpuSmall

provider = GCPBatchProvider(
    project="my-gcp-project",
    region="us-central1",
    temporary_bucket_path="gs://my-bucket/",
    spot=True,  # optional: use spot (preemptible) VMs
    machine_type="n1-standard-4",  # optional: Batch auto-selects if omitted
)
compute = GcpBatchCpuSmall(timeout=600, provider=provider)

result = sum_col("gs://bucket/data.csv", compute=compute)
```

`machine_type` is optional — Batch selects a machine from the requested CPU/memory when it
is not given. For GPUs, a compatible `machine_type` is usually required.

## Environment variables

Both Cloud Run and Batch support passing environment variables to the remote container via the `environment_variables` provider option:

```python
provider = GCPCloudRunProvider(
    project="my-project",
    region="us-central1",
    temporary_bucket_path="gs://my-bucket/tmp",
    environment_variables={"MY_API_KEY": "secret123"},
)
```

Or in `powerfunc.yaml`:

```yaml
provider:
  init_args:
    environment_variables:
      MY_API_KEY: secret123
```

## Supported GPUs

Both Cloud Run and Batch support: `t4`, `a100`, `l4`, `v100`.

## Predefined configurations

| Class | Provider | CPU | Memory | Image | GPU |
|---|---|---|---|---|---|
| `GcpCloudRunCpuSmall` | Cloud Run | 1 vCPU | 2GB | `python:3.12-slim` | — |
| `GcpCloudRunGpu` | Cloud Run | 4 vCPU | 16GB | `nvidia/cuda:12.1.0-base-ubuntu22.04` | L4 |
| `GcpBatchCpuSmall` | Batch | 1 vCPU | 2GB | `python:3.12-slim` | — |
| `GcpBatchGpu` | Batch | 4 vCPU | 16GB | `nvidia/cuda:12.1.0-base-ubuntu22.04` | L4 |

All presets require a `timeout` argument (in seconds), e.g. `GcpCloudRunCpuSmall(timeout=600)` or `GcpBatchCpuSmall(timeout=600)`.

## Known limitations

### Codebase synchronisation

A simple codebase synchronisation method is used. It is not robust to work with all codebases and scenarios. For complex setups, understanding of the underlying infrastructure technologies (such as Python packaging and [Docker](https://www.docker.com/)) will likely be needed. To enable rapid execution for complex codebases, additional setup in needed, such as preparing docker images.

### Anonymous usage

For public GCS buckets without credentials, configure fsspec before importing powerfunc:

```python
import fsspec
fsspec.config.conf["gs"] = {"token": "anon"}
```

**Parquet files on `gs://` hang without credentials** for pandas and polars — their parquet readers use pyarrow's C++ GCS filesystem which has no anonymous mode and no timeout. Use `gcloud auth application-default login` to resolve this, or access parquet via HTTPS instead.
