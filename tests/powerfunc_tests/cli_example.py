import pandas as pd

from powerfunc import powerfunc


@powerfunc
def sum_col(df: pd.DataFrame) -> float:
    return float(df["value"].sum())


@powerfunc
def mean_col(df: pd.DataFrame) -> float:
    return float(df["value"].mean())


@powerfunc(cli=False)
def ignored(df: pd.DataFrame) -> float:
    return 0.0


powerfunc.enable_cli()
