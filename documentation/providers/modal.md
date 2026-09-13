# Modal

This page describes how to execute powerfunc functions remotely on [Modal](https://modal.com).

## Contents

- [Installation](#installation)
- [Basic usage](#basic-usage)
- [The remote environment](#the-remote-environment)
- [Presets](#presets)

## Installation

Make sure to install with the `modal` option.

```sh
pip install 'powerfunc[modal]'
```

or

```sh
uv add 'powerfunc[modal]'
```

You must have a Modal account. Then authenticate to Modal:

```sh
python -m modal setup
```

## Basic usage

```python
from powerfunc import powerfunc
from powerfunc.providers.modal import ModalCpuSmall

@powerfunc
def sum_col(df: pd.DataFrame) -> float:
    return float(df["value"].sum())

result = sum_col("data.csv", compute=ModalCpuSmall(timeout=600))
```

Or set a default in `powerfunc.yaml` so all calls run on Modal without passing `compute=`:

```yaml
compute:
  class_path: powerfunc.providers.modal.ModalCpuSmall
  init_args:
    timeout: 600
```

## The remote environment

The container image is `image` — a registry image, or Modal's `debian_slim` when empty — built once and cached by Modal. Your codebase (your repository minus `.git` and whatever git ignores) is not built into it but mounted when the container starts, onto the image's working directory (its `WORKDIR`, over any files already there — so an image that already contains your project and its environment gets just your current changes laid on top); Modal uploads only the files it has not seen before, so editing your code costs neither an image build nor a full upload. `setup_command` then runs there, on every call, and the function runs with `python -m powerfunc.providers.internal.generic_execute_entrypoint` using the `python` the setup command left on `PATH`, so the same `setup_command` works here and on GCP. By default (`setup_command` empty, as in the predefined configurations) the image must already have `python` with powerfunc and your dependencies:

```python
from powerfunc.providers.modal import ModalCpuSmall

compute = ModalCpuSmall(timeout=600, image="ghcr.io/me/my-project:latest")
result = sum_col("data.csv", compute=compute)
```

Otherwise the provider's `setup_command` has to produce it; `powerfunc.compute.UV_PROJECT_SETUP` (`uv sync --locked && . .venv/bin/activate`) treats the codebase as a uv project, `PIXI_PROJECT_SETUP` does the same with pixi, `PIP_PYPROJECT_SETUP`/`PIP_REQUIREMENTS_TXT_SETUP` pip-install the codebase's `pyproject.toml`/`requirements.txt` into a fresh `.venv`, or use any command that leaves `python` on `PATH`. In `powerfunc.yaml`:

```yaml
compute:
  class_path: powerfunc.providers.modal.ModalCpuSmall
  init_args:
    timeout: 600
    provider:
      class_path: powerfunc.providers.modal.ModalProvider
      init_args:
        setup_command: "python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
```

The command runs verbatim: anything it needs, such as `uv` itself, must be in the image or installed by the command. Since it runs on every call, a dependency install there is paid each time — for anything heavy, put the environment in `image` instead.

`ModalProvider(environment_variables={"NAME": "value"})` sets environment variables of the running function. For example, to read `gs://` paths with a service-account key rather than ADC, give the key JSON as [fsspec configuration](https://filesystem-spec.readthedocs.io/en/latest/features.html#configuration): `environment_variables={"FSSPEC_GCS_TOKEN": key_json}`. `secret_directories=["config/"]` sends whole directories (relative to the repository root, git-ignored or not) encrypted, as described in the [readme](../readme.md#cloud-providers-and-remote-execution), rather than in the image.

## Presets

| Class | CPU | Memory | GPU |
|---|---|---|---|
| `ModalCpuSmall` | 1 vCPU | 1GB | — |
| `ModalGpuA100` | 8 vCPU | 80GB | A100 |

All presets require a `timeout` argument (in seconds), e.g. `ModalCpuSmall(timeout=600)`.
