"""Command line of three functions: two reading a file, one showing its defaults' layering."""

from dataclasses import dataclass

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


@dataclass
class Spec:
    cpu: int = 1
    memory: int = 2


DEFAULT_SPEC = Spec(cpu=3)
DEFAULT_RANGES = {"a": 1.0}


@powerfunc
def show(spec: Spec = DEFAULT_SPEC, ranges: dict[str, float] = DEFAULT_RANGES) -> str:
    return f"{spec.cpu} {spec.memory} {type(ranges).__name__} {dict(ranges)}"


powerfunc.enable_cli()
