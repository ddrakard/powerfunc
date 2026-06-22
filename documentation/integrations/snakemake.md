# Snakemake

powerfunc functions can be called directly from a [Snakemake](https://snakemake.readthedocs.io/)
rule. Call `.snakemake()` inside a `run:` block and the rule's inputs, params and outputs are
bound automatically.

## Usage

```python
# functions.py
import pandas as pd
from powerfunc import powerfunc

@powerfunc
def sum_col(df: pd.DataFrame) -> pd.DataFrame:
    return df.sum().to_frame().T
```

```python
# Snakefile
from functions import sum_col

rule sum:
    input: "data.csv"
    output: "result.csv"
    run:
        sum_col.snakemake()
```

## Binding rules

Inputs (`input`) and params (`params`) are bound to the function's arguments:

- When **both** inputs and params are present, they must all be **named** (keyword).
  Positional entries are only allowed when one of the two is absent.
- Inputs are passed as paths and are read through powerfunc's
  [converters](../readme.md#automatic-reading-and-writing-data), so a `pd.DataFrame`
  parameter receives the loaded file. Params are passed through unchanged.

Outputs (`output`) are bound as follows:

- A single **unnamed** output receives the function's **return value**, written through
  powerfunc's converters.
- Named outputs and multiple outputs are not supported.
