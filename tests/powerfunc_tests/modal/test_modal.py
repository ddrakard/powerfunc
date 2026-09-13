"""Live integration tests for Modal, the counterparts of ``test_gcp_cloud_run.py``.

Never skipped: a Modal token (``MODAL_TOKEN_ID``/``MODAL_TOKEN_SECRET`` or
``~/.modal.toml``) is required, and the file test also requires
``GOOGLE_CLOUD_API_KEY`` and ``GCP_BUCKET``. Runs are kept tiny: a small CPU
container, no GPU.

The environment is built in the container from this checkout by the generic
``setup_command`` (after installing uv, which Modal's Debian slim lacks); the command also
puts ``tests/`` on the path, since ``powerfunc_tests`` is not part of the installed project.
"""

import os
import pathlib

from upath import UPath

from powerfunc.compute import ComputeSpecification
from powerfunc.providers.modal import ModalProvider
from powerfunc_tests.gcp.gcp_shared import TEST_SETUP_COMMAND
from powerfunc_tests.remote_jobs import codebase_file_text, csv_sum, remote_add, remote_concat

DATA_DIR = pathlib.Path(__file__).parents[1] / "data"


def _provider(**fields):
    """A ``ModalProvider`` building this checkout's environment with uv, plus ``fields``."""
    return ModalProvider(
        setup_command=f"pip install -q uv && {TEST_SETUP_COMMAND}",
        **fields,
    )


def _spec(provider=None):
    return ComputeSpecification(
        cpu=1.0, memory=1024, timeout=300.0, provider=provider or _provider()
    )


def test_modal_returns_value():
    """A powerfunc function runs on Modal and its return value comes back."""
    assert remote_add(2, 3, compute=_spec()) == 5


def test_modal_passes_arguments():
    """Arguments are delivered to the remote function, via ``compute=``."""
    assert remote_concat("power", "func", compute=_spec()) == "powerfunc"


def test_modal_reads_a_file(gcp_credentials):
    """A ``gs://`` path given for a file-typed parameter is opened on Modal, with
    the GCP key given to the container as fsspec's gcsfs token."""
    provider = _provider(
        environment_variables={"FSSPEC_GCS_TOKEN": os.environ["GOOGLE_CLOUD_API_KEY"]}
    )
    csv_path = UPath(os.environ["GCP_BUCKET"]) / "powerfunc" / "modal_test_data.csv"
    csv_path.write_bytes((DATA_DIR / "data.csv").read_bytes())
    try:
        assert csv_sum(str(csv_path), compute=_spec(provider)) == 1 + 2 + 3
    finally:
        csv_path.unlink()


def test_modal_sends_secret_directories(secret_directory):
    """A git-ignored directory named in ``secret_directories`` is in the codebase on
    Modal, though not in the image."""
    spec = _spec(_provider(secret_directories=[secret_directory]))
    assert codebase_file_text(f"{secret_directory}/token.txt", compute=spec) == "hunter2"
