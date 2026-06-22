import csv
import pathlib

import dask.dataframe as dd
import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.dataset as pa_dataset
import pytest

from powerfunc import powerfunc
from powerfunc.conversions import read, write

DATA_DIR = pathlib.Path(__file__).parent.parent / "data"

PD_DATA = pd.DataFrame({"value": [1, 2, 3]})
PL_DATA = pl.DataFrame({"value": [1, 2, 3]})
PA_DATA = pa.table({"value": [1, 2, 3]})


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
    next(reader)  # skip header
    return sum(int(row[0]) for row in reader)


READ_CASES = [
    pytest.param(pd_sum, "data.arrow", id="pandas-arrow"),
    pytest.param(pd_sum, "data.csv", id="pandas-csv"),
    pytest.param(pd_sum, "data.feather", id="pandas-feather"),
    pytest.param(pd_sum, "data.pandas.json", id="pandas-json"),
    pytest.param(pd_sum, "data.parquet", id="pandas-parquet"),
    pytest.param(pd_sum, "data.xlsx", id="pandas-xlsx"),
    pytest.param(pl_sum, "data.csv", id="polars-csv"),
    pytest.param(pl_sum, "data.polars.json", id="polars-json"),
    pytest.param(pl_sum, "data.parquet", id="polars-parquet"),
    pytest.param(pl_sum, "data.xlsx", id="polars-xlsx"),
    pytest.param(pa_sum, "data.arrow", id="pyarrow-arrow"),
    pytest.param(pa_sum, "data.csv", id="pyarrow-csv"),
    pytest.param(pa_sum, "data.feather", id="pyarrow-feather"),
    pytest.param(pa_sum, "data.parquet", id="pyarrow-parquet"),
    pytest.param(pa_dataset_sum, "data.arrow", id="pyarrow_dataset-arrow"),
    pytest.param(pa_dataset_sum, "data.csv", id="pyarrow_dataset-csv"),
    pytest.param(pa_dataset_sum, "data.feather", id="pyarrow_dataset-feather"),
    pytest.param(pa_dataset_sum, "data.parquet", id="pyarrow_dataset-parquet"),
    pytest.param(dd_sum, "data.csv", id="dask-csv"),
    pytest.param(dd_sum, "data.parquet", id="dask-parquet"),
    pytest.param(csv_sum, "data.csv", id="csv_reader-csv"),
]


@pytest.mark.parametrize("func,filename", READ_CASES)
def test_read(func, filename):
    assert func(DATA_DIR / filename) == 6


def pd_check(df):
    return df["value"].sum() == 6


def pl_check(df):
    return df["value"].sum() == 6


def pa_check(t):
    return sum(t.column("value").to_pylist()) == 6


WRITE_CASES = [
    pytest.param(PD_DATA, pd.DataFrame, ".arrow", pd_check, id="pandas-arrow"),
    pytest.param(PD_DATA, pd.DataFrame, ".csv", pd_check, id="pandas-csv"),
    pytest.param(PD_DATA, pd.DataFrame, ".feather", pd_check, id="pandas-feather"),
    pytest.param(PD_DATA, pd.DataFrame, ".json", pd_check, id="pandas-json"),
    pytest.param(PD_DATA, pd.DataFrame, ".parquet", pd_check, id="pandas-parquet"),
    pytest.param(PD_DATA, pd.DataFrame, ".xlsx", pd_check, id="pandas-xlsx"),
    pytest.param(PL_DATA, pl.DataFrame, ".csv", pl_check, id="polars-csv"),
    pytest.param(PL_DATA, pl.DataFrame, ".json", pl_check, id="polars-json"),
    pytest.param(PL_DATA, pl.DataFrame, ".parquet", pl_check, id="polars-parquet"),
    pytest.param(PL_DATA, pl.DataFrame, ".xlsx", pl_check, id="polars-xlsx"),
    pytest.param(PA_DATA, pa.Table, ".arrow", pa_check, id="pyarrow-arrow"),
    pytest.param(PA_DATA, pa.Table, ".csv", pa_check, id="pyarrow-csv"),
    pytest.param(PA_DATA, pa.Table, ".feather", pa_check, id="pyarrow-feather"),
    pytest.param(PA_DATA, pa.Table, ".parquet", pa_check, id="pyarrow-parquet"),
]


@pytest.mark.parametrize("value,type_,ext,check", WRITE_CASES)
def test_write(value, type_, ext, check, tmp_path):
    path = tmp_path / f"output{ext}"
    write(value, path)
    with read(path, type_) as result:
        assert check(result)
