import pandas as pd

from powerfunc import powerfunc


@powerfunc
def double(df: pd.DataFrame) -> pd.DataFrame:
    return df * 2


@powerfunc
def make(n: int) -> pd.DataFrame:
    return pd.DataFrame({"value": list(range(n))})


@powerfunc
def split(df: pd.DataFrame, head: str, tail: str) -> None:
    half = len(df) // 2
    df.iloc[:half].to_csv(head, index=False)
    df.iloc[half:].to_csv(tail, index=False)


@powerfunc
def scale(df: pd.DataFrame, factor: int) -> pd.DataFrame:
    return df * factor
