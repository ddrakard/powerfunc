# Google Cloud Platform Cloud Run

This page describes how to execute powerfunc functions remotely on [GCP Cloud Run Jobs](https://cloud.google.com/run/docs/create-jobs).

## Contents

- [Installation](#installation)
- [Setup and configuration](#setup-and-configuration)
- [Environment variables](#environment-variables)
- [Predefined configurations](#predefined-configurations)
- [Supported GPUs](#supported-gpus)
- [Limitations](#limitations)

## Installation

Make sure to install with the `gcp` option.

```sh
pip install powerfunc[gcp]
```

or

```sh
uv add powerfunc[gcp]
```

## Usage

You need to have a Google Cloud account with a project inside it where the remote execution can happen. You must authenticate with the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) using:

```sh
gcloud auth application-default login
```

powerfunc transfers data in and out of the compute job using a [Google Cloud Storage bucket](https://docs.cloud.google.com/storage/docs/buckets). Therefore, you need to have or create a bucket that powerfunc can use, and provide these details.

The recommended approach is to configure the provider in `powerfunc.yaml`:

```yaml
compute:
  class_path: powerfunc.providers.gcp.GcpCpuSmall
  init_args:
    provider:
      class_path: powerfunc.providers.gcp.GCPProvider
      init_args:
        project: my-gcp-project
        region: us-central1
        temporary_bucket_path: gs://my-bucket/powerfunc-temp
```

Or directly in Python:

```python
from powerfunc.providers.gcp import GCPProvider, GcpCpuSmall

provider = GCPProvider(
    project="my-gcp-project",
    region="us-central1",
    temporary_bucket_path="gs://my-bucket/",
)
compute = GcpCpuSmall(provider=provider)

result = sum_col("gs://bucket/data.csv", compute=compute)
```

### Command line usage

When runnng from the command line, [module-style invocation](https://docs.python.org/3/using/cmdline.html#cmdoption-m) `python -m my.module` must be used instead of direct script execution `python myscript.py`.

## Cold start time

Cloud Run Jobs can require some time to start, particularly for a docker image that has not been used recently.

## Environment variables

Pass environment variables to the remote container:

```yaml
compute:
  class_path: powerfunc.providers.gcp.GcpCpuSmall
  init_args:
    provider:
      class_path: powerfunc.providers.gcp.GCPProvider
      init_args:
        project: my-project
        region: us-central1
        temporary_bucket_path: gs://my-bucket/tmp
        environment_variables:
          MY_API_KEY: secret123
```

## Supported GPUs

`t4`, `a100`, `l4`, `v100`

## Predefined configurations

| Class | CPU | Memory | Image | GPU |
|---|---|---|---|---|
| `GcpCpuSmall` | 1 vCPU | 2GB | `python:3.12-slim` | — |
| `GcpGpu` | 4 vCPU | 16GB | `gcr.io/deeplearning-platform-release/base-cu121` | L4 |

Convenience instances `powerfunc.providers.gcp.GCP_CPU_SMALL` and `powerfunc.providers.gcp.GCP_GPU` are available for direct use.

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
