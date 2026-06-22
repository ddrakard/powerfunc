# powerfunc

Add superpowers to your functions. Run them from the CLI, on cloud data, or on cloud compute.

## Features

- Load and save function arguments and results to file paths, local or in cloud storage.
- Invoke functions on the command line.
- Remote execution on cloud compute.
- YAML configuration file support.
- Supports [pandas](https://pandas.pydata.org/), [polars](https://pola.rs/), [PyArrow](https://pypi.org/project/pyarrow/), [Dask](https://www.dask.org/), and the Python [`csv` module](https://docs.python.org/3/library/csv.html) out of the box
- Supports cloud providers [Google Cloud](https://cloud.google.com) and [Modal](https://modal.com/).
- Extensible for new data types and cloud providers.

## Installation

```bash
pip install powerfunc
```

With [Google Cloud](https://cloud.google.com) remote execution:

```bash
pip install 'powerfunc[gcp]'
```

With [Modal](https://modal.com/) remote execution:

```bash
pip install 'powerfunc[modal]'
```

## Example usage

Decorate a normal function with `@powerfunc`:

```python
import pandas as pd
from powerfunc import powerfunc

@powerfunc
def sum_col(df: pd.DataFrame) -> float:
    return float(df["value"].sum())

df = pd.DataFrame({"value": [1, 2, 3]})
print(sum_col(df))
```

Then use it on files, local or in the cloud:

```python
print(sum_col("data.csv"))
print(sum_col("https://storage.googleapis.com/powerfunc/data.csv"))
```

Add one line at the end of your file to make it runnable on the command line:

```python
from powerfunc import powerfunc

...

powerfunc.enable_cli()
```

```sh
python myfile.py gs://powerfunc/data.csv
```

## Support

This project is in early development. Breaking changes may happen at any time.

## Documentation

For complete information on using powerfunc, including executing on cloud compute, please see the [documentation](documentation/readme.md).

## License

Released under the [MIT](LICENSE.txt) license.
