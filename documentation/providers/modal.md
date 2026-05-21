# Modal

This page describes how to execute powerfunc functions remotely on [Modal](https://modal.com).

## Contents

- [Installation](#installation)
- [Basic usage](#basic-usage)
- [Dependencies](#dependencies)
- [Presets](#presets)

## Installation

Make sure to install with the `modal` option.

```sh
pip install powerfunc[modal]
```

or

```sh
uv add powerfunc[modal]
```

You must have a Modal account. Then authenticate to Modal:

```sh
python -m modal setup
```

## Basic usage

```python
from powerfunc import powerfunc
from powerfunc.providers.modal import MODAL_CPU_SMALL

@powerfunc
def sum_col(df: pd.DataFrame) -> float:
    return float(df["value"].sum())

result = sum_col("data.csv", compute=MODAL_CPU_SMALL)
```

Or set a default in `powerfunc.yaml` so all calls run on Modal without passing `compute=`:

```yaml
compute:
  class_path: powerfunc.providers.modal.ModalCpuSmall
```

## Dependencies

By default the container uses Modal's `debian_slim` base image. If your function imports packages that aren't in the standard library, specify them via `pip_packages` on the provider:

```python
from powerfunc.providers.modal import ModalProvider, ModalCpuSmall

compute = ModalCpuSmall(provider=ModalProvider(pip_packages=("pandas", "pyarrow")))
result = sum_col("data.csv", compute=compute)
```

To use a different base image, set `image` on the compute specification:

```python
from powerfunc.providers.modal import ModalCpuSmall

compute = ModalCpuSmall(image="python:3.12-slim")
result = sum_col("data.csv", compute=compute)
```

Or in `powerfunc.yaml`:

```yaml
compute:
  class_path: powerfunc.providers.modal.ModalCpuSmall
  init_args:
    image: "python:3.12-slim"
    provider:
      class_path: powerfunc.providers.modal.ModalProvider
      init_args:
        pip_packages: ["pandas", "pyarrow"]
```

## Presets

| Class | CPU | Memory | GPU |
|---|---|---|---|
| `ModalCpuSmall` | 1 vCPU | 1GB | — |
| `ModalGpuA100` | 8 vCPU | 80GB | A100 |

Convenience instances `powerfunc.providers.modal.MODAL_CPU_SMALL` and `powerfunc.providers.modal.MODAL_GPU_A100` are available for direct use.
