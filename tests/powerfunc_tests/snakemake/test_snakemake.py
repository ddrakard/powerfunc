"""Tests that run real Snakemake workflows calling function.snakemake()."""

import pathlib
import shutil
import subprocess
import sys

import pandas as pd
import pytest

from powerfunc import powerfunc

pytest.importorskip("snakemake")

SNAKEMAKE_DIR = pathlib.Path(__file__).parent
DATA_DIR = SNAKEMAKE_DIR.parent / "data"


def run_workflow(tmp_path, smk_file, targets):
    """Run a Snakemake workflow in tmp_path using a .smk file from this directory."""
    shutil.copy(SNAKEMAKE_DIR / "functions.py", tmp_path / "functions.py")
    for data_file in smk_file_data_files(smk_file):
        shutil.copy(DATA_DIR / data_file, tmp_path / data_file)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "snakemake",
            "--cores",
            "1",
            "--snakefile",
            str(SNAKEMAKE_DIR / smk_file),
            *targets,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def smk_file_data_files(smk_file):
    """Return data files referenced by a .smk file (simple grep for known files)."""
    content = (SNAKEMAKE_DIR / smk_file).read_text()
    files = []
    if "data.csv" in content:
        files.append("data.csv")
    return files


def test_input(tmp_path):
    """A file input is read into a DataFrame; the return value is written to the output."""
    run_workflow(tmp_path, "input.smk", ["out.csv"])
    assert pd.read_csv(tmp_path / "out.csv")["value"].tolist() == [2, 4, 6]


def test_params(tmp_path):
    """A params value is passed to the function; no file input is involved."""
    run_workflow(tmp_path, "params.smk", ["out.csv"])
    assert pd.read_csv(tmp_path / "out.csv")["value"].tolist() == [0, 1, 2, 3]


def test_named_outputs_rejected(tmp_path):
    """Named outputs are not supported and should produce an error."""
    with pytest.raises(Exception, match="Named outputs are not supported"):
        run_workflow(tmp_path, "named_outputs_rejected.smk", ["head.csv", "tail.csv"])


def test_input_params_and_output_combination(tmp_path):
    """Named input + named params + output bound together."""
    run_workflow(tmp_path, "input_params_and_output.smk", ["out.csv"])
    assert pd.read_csv(tmp_path / "out.csv")["value"].tolist() == [3, 6, 9]


def test_positional_rejected_when_both_inputs_and_params(tmp_path):
    """Positional inputs and params together are rejected."""
    with pytest.raises(Exception, match="must all be named"):
        run_workflow(tmp_path, "positional_rejected.smk", ["out.csv"])


def test_multiple_positional_outputs_rejected(tmp_path):
    """Multiple positional outputs are not supported."""
    with pytest.raises(Exception, match="Multiple outputs are not supported"):
        run_workflow(tmp_path, "multiple_outputs_rejected.smk", ["a.csv", "b.csv"])


def test_outside_snakemake_context_raises():
    """Calling .snakemake() outside a rule raises RuntimeError."""

    @powerfunc
    def noop() -> None:
        pass

    with pytest.raises(RuntimeError, match="outside of a Snakemake"):
        noop.snakemake()
