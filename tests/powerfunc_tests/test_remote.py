import csv

import fsspec

# Required for anonymous access to public GCS buckets — without this, gcsfs will
# attempt to authenticate and hang indefinitely if no credentials are found.
fsspec.config.conf["gs"] = {"token": "anon"}

import dask.dataframe as dd  # noqa: E402
import pandas as pd  # noqa: E402
import polars as pl  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.dataset as pa_dataset  # noqa: E402
import pytest  # noqa: E402

from powerfunc import powerfunc  # noqa: E402


@powerfunc
def pd_sum(df: pd.DataFrame) -> float:
    return df["value"].sum()


@powerfunc
def pl_sum(df: pl.DataFrame) -> float:
    return df["value"].sum()


@powerfunc
def pa_sum(table: pa.Table) -> int:
    return sum(table.column("value").to_pylist())


@powerfunc
def pa_dataset_sum(dataset: pa_dataset.Dataset) -> int:
    return sum(dataset.to_table().column("value").to_pylist())


@powerfunc
def dd_sum(df: dd.DataFrame) -> float:
    return df["value"].sum().compute()


@powerfunc
def csv_sum(reader: csv.reader) -> int:
    next(reader)
    return sum(int(row[0]) for row in reader)


HANGS_GCS = "hangs: pyarrow GCS filesystem requires credentials"


LIBRARIES = [
    pytest.param(pd_sum, "data.csv", {}, id="pandas-csv"),
    pytest.param(pd_sum, "data.parquet", {"gs": HANGS_GCS}, id="pandas-parquet"),
    pytest.param(pd_sum, "data.pandas.json", {}, id="pandas-json"),
    pytest.param(pd_sum, "data.xlsx", {}, id="pandas-xlsx"),
    pytest.param(pl_sum, "data.csv", {}, id="polars-csv"),
    pytest.param(pl_sum, "data.parquet", {"gs": HANGS_GCS}, id="polars-parquet"),
    pytest.param(pl_sum, "data.polars.json", {}, id="polars-json"),
    pytest.param(pl_sum, "data.xlsx", {}, id="polars-xlsx"),
    pytest.param(pa_sum, "data.csv", {}, id="pyarrow-csv"),
    pytest.param(pa_sum, "data.parquet", {}, id="pyarrow-parquet"),
    pytest.param(pa_sum, "data.feather", {}, id="pyarrow-feather"),
    pytest.param(pa_sum, "data.arrow", {}, id="pyarrow-arrow"),
    pytest.param(pa_dataset_sum, "data.csv", {}, id="pyarrow_dataset-csv"),
    pytest.param(pa_dataset_sum, "data.parquet", {}, id="pyarrow_dataset-parquet"),
    pytest.param(pa_dataset_sum, "data.arrow", {}, id="pyarrow_dataset-arrow"),
    pytest.param(dd_sum, "data.csv", {}, id="dask-csv"),
    pytest.param(dd_sum, "data.parquet", {}, id="dask-parquet"),
    pytest.param(csv_sum, "data.csv", {}, id="csv_reader-csv"),
]

ENDPOINTS = [
    pytest.param("gs", "gs://powerfunc", id="gs"),
    pytest.param("https", "https://storage.googleapis.com/powerfunc", id="https"),
]


@pytest.mark.parametrize("endpoint,base", ENDPOINTS)
@pytest.mark.parametrize("func,filename,skips", LIBRARIES)
def test_remote(func, filename, skips, endpoint, base):
    if skips.get(endpoint):
        pytest.skip(skips[endpoint])
    assert func(f"{base}/{filename}") == 6
