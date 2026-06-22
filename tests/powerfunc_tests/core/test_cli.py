import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).parent / "cli_example.py"
DATA = pathlib.Path(__file__).parent.parent / "data" / "data.csv"


def run(*args):
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
    )


def test_help_shows_subcommands():
    result = run("--help")
    assert "sum_col" in result.stdout
    assert "mean_col" in result.stdout
    assert "ignored" not in result.stdout


def test_sum_col():
    result = run("sum_col", str(DATA))
    assert result.returncode == 0
    assert result.stdout.strip() == "6.0"


def test_mean_col():
    result = run("mean_col", str(DATA))
    assert result.returncode == 0
    assert result.stdout.strip() == "2.0"


def test_sum_col_remote():
    result = run("sum_col", "https://storage.googleapis.com/powerfunc/data.csv")
    assert result.returncode == 0
    assert result.stdout.strip() == "6.0"
