"""The provider-independent job stages, run locally with file paths instead of a bucket."""

import json
import pathlib
import subprocess
import sys

import cloudpickle
import pytest

from powerfunc.providers.internal import codebase_transfer, job_specification, secret_directories
from powerfunc.providers.internal import generic_execute_entrypoint as execute_entrypoint
from powerfunc_tests import remote_jobs


def test_function_identifier_is_module_and_qualname():
    assert job_specification.function_identifier(remote_jobs.remote_add) == (
        "powerfunc_tests.remote_jobs:remote_add"
    )


def test_codebase_contains_the_function_module_importably():
    codebase = codebase_transfer.codebase_of(remote_jobs.remote_add)
    assert codebase is not None
    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(codebase)).namelist()
    assert "tests/powerfunc_tests/remote_jobs.py" in names


def test_zip_codebase_excludes_secret_directories_even_if_tracked():
    """A tracked directory named as a secret directory travels encrypted only."""
    import io
    import zipfile

    root = codebase_transfer.repository_root(remote_jobs.remote_add)
    assert root is not None
    names = zipfile.ZipFile(
        io.BytesIO(codebase_transfer.zip_codebase(root, ["tests/powerfunc_tests/"]))
    ).namelist()
    assert not any(name.startswith("tests/powerfunc_tests/") for name in names)
    assert "pyproject.toml" in names


def _write_spec(directory: pathlib.Path, function, arguments: dict, **extra) -> pathlib.Path:
    argument_paths = {}
    for name, value in arguments.items():
        path = directory / f"{name}.pkl"
        path.write_bytes(cloudpickle.dumps(value))
        argument_paths[name] = str(path)
    spec = job_specification.job_spec(
        function=job_specification.function_identifier(function),
        output_path=str(directory / "output.pkl"),
        argument_paths=argument_paths,
        **extra,
    )
    spec_path = directory / "job_spec.json"
    spec_path.write_text(json.dumps(spec))
    return spec_path


def test_execute_stage_runs_the_function_and_writes_the_result(tmp_path):
    spec_path = _write_spec(tmp_path, remote_jobs.remote_add, {"a": 2, "b": 3})
    execute_entrypoint.main([str(spec_path)])
    assert cloudpickle.loads((tmp_path / "output.pkl").read_bytes()) == 5


def test_execute_stage_reports_failures_beside_the_output(tmp_path):
    spec_path = _write_spec(tmp_path, remote_jobs.remote_add, {"a": 2, "b": "x"})
    with pytest.raises(TypeError):
        execute_entrypoint.main([str(spec_path)])
    assert "TypeError" in (tmp_path / "output.pkl__error").read_text()


def test_setup_stage_unpacks_the_codebase_over_the_working_directory_then_execute(tmp_path):
    codebase = codebase_transfer.codebase_of(remote_jobs.remote_add)
    assert codebase is not None
    (tmp_path / "codebase.zip").write_bytes(codebase)
    (tmp_path / "already_in_image").write_text("kept")
    marker = tmp_path / "setup_ran_in"
    spec_path = _write_spec(
        tmp_path,
        remote_jobs.remote_concat,
        {"prefix": "a", "suffix": "b"},
        codebase_path=str(tmp_path / "codebase.zip"),
        # The command makes the codebase importable, as a real one does by installing it.
        setup_command=f"pwd > {marker} && ls pyproject.toml >> {marker} && export PYTHONPATH=tests",
    )
    result = subprocess.run(
        [sys.executable, "-m", job_specification.SETUP_ENTRYPOINT, spec_path.name],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert cloudpickle.loads((tmp_path / "output.pkl").read_bytes()) == "ab"
    ran_in, listed = marker.read_text().split()
    assert pathlib.Path(ran_in) == tmp_path
    assert listed == "pyproject.toml"
    assert (tmp_path / "already_in_image").read_text() == "kept"


def test_execute_stage_decrypts_secret_directories_into_the_codebase(
    tmp_path, secret_directory, monkeypatch
):
    root = pathlib.Path(__file__).parents[3]
    assert secret_directory in subprocess.check_output(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"],
        cwd=root,
        text=True,
    )
    ciphertext, key = secret_directories.encrypt_secret_directories(root, [secret_directory])
    assert b"hunter2" not in ciphertext
    (tmp_path / "secrets").write_bytes(ciphertext)
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    spec_path = _write_spec(
        tmp_path,
        remote_jobs.codebase_file_text,
        {"relative_path": f"{secret_directory}/token.txt"},
        secret_directories_path=str(tmp_path / "secrets"),
    )
    with pytest.raises(Exception, match=secret_directories.KEY_VARIABLE):
        execute_entrypoint.main([str(spec_path), str(codebase)])
    monkeypatch.setenv(secret_directories.KEY_VARIABLE, key)
    execute_entrypoint.main([str(spec_path), str(codebase)])
    assert (codebase / secret_directory / "token.txt").read_text() == "hunter2"
