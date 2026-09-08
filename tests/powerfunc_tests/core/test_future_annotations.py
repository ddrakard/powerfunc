"""``@powerfunc`` under ``from __future__ import annotations``."""

from __future__ import annotations

import pathlib

import pandas as pd

from powerfunc import powerfunc

DATA_DIR = pathlib.Path(__file__).parents[1] / "data"


@powerfunc
def row_count(df: pd.DataFrame) -> int:
    return len(df)


def test_path_is_read():
    """A path given for ``df`` is read as a DataFrame, not passed on as a string.

    The ``__future__`` import above makes ``df``'s annotation the string
    ``'pd.DataFrame'`` at runtime. The decorator must evaluate it to the type to
    find its registered converter; if it did not, ``len`` would get the path
    string and this would return its character count.
    """
    assert row_count(str(DATA_DIR / "data.csv")) == len(pd.read_csv(DATA_DIR / "data.csv"))
