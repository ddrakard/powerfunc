
# `powerfunc` documentation

## Contents

- [Installation](#installation)
- [Basic usage](#basic-usage)
- [Automatic reading and writing data](#automatic-reading-and-writing-data)
- [Command line usage](#command-line-usage)
- [Cloud providers and remote execution](#cloud-providers-and-remote-execution)
- [Configuration](#configuration)
- [Supported formats](#supported-formats)
- [Integrations](#integrations)
- [Known limitations](#known-limitations)
- [Advanced usage](#advanced-usage)

## Installation

Installation using [pip](https://pypi.org/project/pip/):

```sh
pip install powerfunc
```

For GCP remote execution:

```sh
pip install 'powerfunc[gcp]'
```

For Modal remote execution:

```sh
pip install 'powerfunc[modal]'
```

Or using [uv](https://github.com/astral-sh/uv):

```sh
uv add powerfunc
```

```sh
uv add 'powerfunc[gcp]'
```

```sh
uv add 'powerfunc[modal]'
```

## Basic usage

To get started, decorate a function with `@powerfunc`.

```python
import pandas as pd
from powerfunc import powerfunc

@powerfunc
def sum_col(df: pd.DataFrame) -> float:
    return float(df["value"].sum())
```

You can still use the function as normal.

```python
df = pd.DataFrame({"value": [1, 2, 3]})
print(sum_col(df))
```

### Automatic reading and writing data

Decorated functions can automatically read and write to files. The files can be local, on the web, or in cloud storage. For cloud storage URLs (such as Google Cloud `gs://`) install and authenticate the appropriate package as described in [Cloud providers and remote execution](#cloud-providers-and-remote-execution).

#### Reading files

```python
# Local
print(sum_col("data.csv"))
# Public web files
print(sum_col("https://storage.googleapis.com/powerfunc/data.csv"))
# Cloud storage (requires configuration for private files)
print(sum_col("gs://powerfunc/data.csv"))
```

### Writing files

```python
# Reading and writing local files
sum_col("data.csv", output_path="result.json")
# Reading and writing remote files
sum_col("gs://bucket/data.csv", output_path="gs://bucket/result.parquet")
```

## Command line usage

Add `powerfunc.enable_cli()` at the end of a script to expose all `@powerfunc` functions as a CLI.

```python
import pandas as pd
from powerfunc import powerfunc

@powerfunc
def sum_col(df: pd.DataFrame) -> float:
    return float(df["value"].sum())

@powerfunc
def mean_col(df: pd.DataFrame) -> float:
    return float(df["value"].mean())

@powerfunc(cli=False)
def internal(df: pd.DataFrame) -> float:
    return 0.0

powerfunc.enable_cli()
```

```bash
python my_script.py sum_col data.csv
python my_script.py mean_col data.csv --output_path result.json
python my_script.py --help
```

## Cloud providers and remote execution

Powerfunc functions can be run on cloud compute by providing a `compute` argument. It is composed of two parts, a `ComputeSpecification` which describes the type of hardware required, and a `Provider` which provides the connection to the desired cloud service.

To enable in Python (change for relevant provider):

```python
my_function("data.csv", compute=MyComputeSpecification())
```

Equivalently on the command line:

```sh
python myfile.py myfunction data.csv --compute=MyComputeSpecification
```

Each compute provider has its own setup process. See the individual pages for provider-specific documentation:

- [GCP](providers/gcp.md)
- [Modal](providers/modal.md)

The [configuration](#configuration) section is useful for working with compute providers, including configuring a default provider.

## Configuration

Create a configuration file, at `powerfunc.yaml` or `configuration/powerfunc.yaml` by default, for any argument to a powerfunc function. This is particularly useful for the `compute` parameter. The file should be structured according to the [jsonargparse](https://github.com/omni-us/jsonargparse) library (which is not just for JSON).

For example:

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

Individual fields can be overridden on the command line. This is again particularly useful for the compute parameter.

```sh
python myfile.py sum_col data.csv --compute.cpu=4
```

The configuration file search paths can be changed in Python:

```python
from powerfunc import configuration_paths

configuration_paths.append("my_config.yaml")
```

When using the CLI, pass a config file with `--config`:

```sh
python my_script.py sum_col data.csv --config my_config.yaml
```

## Supported formats

| Type | Formats |
|---|---|
| `pd.DataFrame` | `.csv`, `.parquet`, `.json`, `.xls`, `.xlsx`, `.feather`, `.arrow` |
| `pl.DataFrame` | `.csv`, `.parquet`, `.json`, `.xlsx` |
| `pa.Table` | `.csv`, `.parquet`, `.arrow`, `.feather` |
| `pa.dataset.Dataset` | `.csv`, `.parquet`, `.arrow`, `.feather` |
| `dask.dataframe.DataFrame` | `.csv`, `.parquet` |
| `csv.reader` | `.csv` |

## Integrations

powerfunc functions can be driven by external workflow tools:

- [Snakemake](integrations/snakemake.md) — bind a rule's inputs, params and outputs with `function.snakemake()`.

## Known limitations

### Anonymous `gs://` access

For public GCS buckets without credentials, configure fsspec before importing powerfunc:

```python
import fsspec
fsspec.config.conf["gs"] = {"token": "anon"}
```

**Parquet files on `gs://` hang without credentials** for pandas and polars — their parquet readers use pyarrow's C++ GCS filesystem which has no anonymous mode and no timeout. Use `gcloud auth application-default login` to resolve this, or access parquet via HTTPS instead.

## Advanced usage

For customising and extending powerfunc please see [Advanced usage](advanced_usage.md)