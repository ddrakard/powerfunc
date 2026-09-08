"""Live integration tests for Modal, the counterparts of ``test_gcp_cloud_run.py``.

Never skipped: a Modal token (``MODAL_TOKEN_ID``/``MODAL_TOKEN_SECRET`` or
``~/.modal.toml``) is required, and the file test also requires
``GOOGLE_CLOUD_API_KEY`` and ``GCP_BUCKET``. Runs are kept tiny: a small CPU
container, no GPU.

The image is built from this checkout, not PyPI: ``modal.serialized`` pickles a
powerfunc function by module and name, so the container needs the same
``powerfunc`` and ``powerfunc_tests`` packages as the caller.
"""

import os
import pathlib
from dataclasses import dataclass
from typing import Optional

from cloudpathlib import AnyPath

from powerfunc.compute import ComputeSpecification
from powerfunc.providers.modal import ModalProvider, modal
from powerfunc_tests.remote_jobs import csv_sum, remote_add, remote_concat

ROOT = pathlib.Path(__file__).parents[3]
DATA_DIR = pathlib.Path(__file__).parents[1] / "data"
REMOTE_KEY_PATH = "/root/gcp_key.json"


@dataclass
class CheckoutProvider(ModalProvider):
    """Modal, with this checkout's ``powerfunc`` and ``tests`` in the image and,
    if ``gcp_key`` is given, that service-account key as the container's ADC."""

    gcp_key: Optional[str] = None

    def image(self, compute: ComputeSpecification) -> modal.Image:
        image = modal.Image.debian_slim(python_version="3.12").pip_install_from_pyproject(
            str(ROOT / "pyproject.toml")
        )
        if self.gcp_key:
            image = image.add_local_file(self.gcp_key, REMOTE_KEY_PATH)
        return image.add_local_python_source("powerfunc", "powerfunc_tests")

    def secrets(self) -> list[modal.Secret]:
        if not self.gcp_key:
            return []
        return [modal.Secret.from_dict({"GOOGLE_APPLICATION_CREDENTIALS": REMOTE_KEY_PATH})]


def _spec(provider):
    return ComputeSpecification(cpu=1.0, memory=1024, timeout=300.0, provider=provider)


def test_modal_returns_value():
    """A powerfunc function runs on Modal and its return value comes back."""
    assert remote_add(2, 3, compute=_spec(CheckoutProvider())) == 5


def test_modal_passes_arguments():
    """Arguments are delivered to the remote function, via ``compute=``."""
    assert remote_concat("power", "func", compute=_spec(CheckoutProvider())) == "powerfunc"


def test_modal_reads_a_file(gcp_credentials):
    """A ``gs://`` path given for a file-typed parameter is opened on Modal, with
    the GCP key given to the container."""
    provider = CheckoutProvider(gcp_key=os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    csv_path = AnyPath(os.environ["GCP_BUCKET"]) / "powerfunc" / "modal_test_data.csv"
    csv_path.write_bytes((DATA_DIR / "data.csv").read_bytes())
    try:
        assert csv_sum(str(csv_path), compute=_spec(provider)) == 1 + 2 + 3
    finally:
        csv_path.unlink()
