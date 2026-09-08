"""Defaults, then configuration file, then what the call gives, from either entry point.

The command line reads ``configuration/powerfunc.yaml`` and ``powerfunc.yaml``
from the working directory, or ``--config`` instead, and argv overwrites fields
and keys of what they hold. A call from Python reads no file unless ``config``
names one, or is True for those defaults -- else a stray file in the working
directory would change any call's arguments -- and its own arguments win.
"""

import pathlib
import subprocess
import sys

import pytest

from powerfunc import powerfunc

SCRIPT = pathlib.Path(__file__).parent / "cli_example.py"


def run(*args):
    result = subprocess.run([sys.executable, SCRIPT, "show", *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_defaults():
    assert run() == "3 2 dict {'a': 1.0}"


def test_command_line_overwrites_dataclass_field_of_default():
    assert run("--spec.memory", "8") == "3 8 dict {'a': 1.0}"


def test_command_line_overwrites_dict_key_of_default():
    assert run("--ranges.b", "2") == "3 2 dict {'a': 1.0, 'b': 2.0}"


def test_config_file_then_command_line(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("spec:\n  cpu: 5\nranges:\n  a: 3.0\n  c: 4.0\n")
    assert run("--config", str(config)) == "5 2 dict {'a': 3.0, 'c': 4.0}"
    assert run("--config", str(config), "--spec.memory", "8", "--ranges.a", "9") == (
        "5 8 dict {'a': 9.0, 'c': 4.0}"
    )


def test_runs_as_a_module_its_package_already_imported():
    result = subprocess.run(
        [sys.executable, "-m", "powerfunc_tests.core.cli_example", "show", "--ranges.b", "2"],
        capture_output=True,
        text=True,
        cwd=SCRIPT.parents[2],
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "3 2 dict {'a': 1.0, 'b': 2.0}"


@powerfunc
def scaled(value: float, *, scale: float = 1.0) -> float:
    return value * scale


@pytest.fixture
def default_configuration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "powerfunc.yaml").write_text("scale: 10\n")
    return tmp_path


def test_python_call_ignores_default_files(default_configuration):
    assert scaled(2.0) == 2.0


def test_python_call_config_true_reads_default_files(default_configuration):
    assert scaled(2.0, config=True) == 20.0


def test_python_call_config_path_reads_that_file(tmp_path):
    configuration = tmp_path / "elsewhere.yaml"
    configuration.write_text("scale: 3\n")
    assert scaled(2.0, config=configuration) == 6.0
    assert scaled(2.0, config=str(configuration)) == 6.0


def test_python_call_arguments_win_over_the_file(default_configuration):
    assert scaled(2.0, scale=5.0, config=True) == 10.0


def test_a_function_may_not_name_a_parameter_powerfunc_adds():
    with pytest.raises(TypeError, match="config"):

        @powerfunc
        def clashing(config: str) -> str:
            return config
