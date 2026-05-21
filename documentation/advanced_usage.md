# Advanced usage

## Contents

- [Custom compute presets](#custom-compute-presets)
- [Custom file converters](#custom-file-converters)

## Custom compute presets

Subclass `ComputeSpecification` to define reusable compute configurations:

```python
from dataclasses import field
from pydantic.dataclasses import dataclass
from powerfunc.compute import ComputeSpecification, Provider
from powerfunc.providers.gcp import GCPProvider

provider = GCPProvider(
    project="my-project",
    region="us-central1",
    temporary_bucket_path="gs://my-bucket/tmp",
)

@dataclass
class MyGpuSpec(ComputeSpecification):
    cpu: float = 8.0
    memory: int = 32768
    image: str = "gcr.io/deeplearning-platform-release/base-cu121"
    gpu: str = "a100"
    provider: Provider = field(default_factory=lambda: provider)

MY_GPU = MyGpuSpec()
```

Subclasses are automatically discoverable by jsonargparse, so users can select them by name in config files:

```yaml
compute:
  class_path: my_module.MyGpuSpec
```

## Custom file converters

Register readers and writers for new types using `register_converters`:

```python
from powerfunc import powerfunc
from powerfunc.conversions import register_converters, as_context
import numpy as np

register_converters(
    np.ndarray,
    ".npy",
    reader=as_context(np.load),
    writer=lambda arr, path: np.save(path, arr),
)
```

Once registered, `np.ndarray` parameters accept file paths automatically:

```python
@powerfunc
def process(arr: np.ndarray) -> np.ndarray:
    return arr * 2

process("data.npy")
process("gs://bucket/data.npy")
```

### Context manager readers

For formats that require keeping a file handle open during the function call (e.g. memory-mapped files), use a `@contextmanager` reader instead of `as_context`:

```python
from contextlib import contextmanager
from powerfunc.conversions import register_converters

@contextmanager
def _open_memmap(path):
    arr = np.load(path, mmap_mode="r")
    try:
        yield arr
    finally:
        del arr

register_converters(np.ndarray, ".npy", reader=_open_memmap)
```

### Native cloud protocol support

If your reader natively handles cloud URIs (e.g. `gs://`, `s3://`), declare them so powerfunc skips the local download step:

```python
register_converters(
    pd.DataFrame,
    ".csv",
    reader=as_context(pd.read_csv),
    native_protocols={"gs", "s3", "https"},
)
```
