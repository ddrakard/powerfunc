import pathlib

import pandas as pd

from powerfunc import powerfunc

DATA_DIR = pathlib.Path(__file__).parent / "data"

DF_DATA = pd.DataFrame({"value": [1, 2, 3]})


@powerfunc
def sum_column(df: pd.DataFrame) -> float:
    return df["value"].sum()


def test_basic():
    assert sum_column(DF_DATA) == 6.0


def test_csv():
    assert sum_column(DATA_DIR / "data.csv") == 6.0


def test_csv_str():
    assert sum_column(str(DATA_DIR / "data.csv")) == 6.0
