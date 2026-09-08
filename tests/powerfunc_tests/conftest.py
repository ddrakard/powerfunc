import json
import os
import tempfile

import pytest


@pytest.fixture(scope="module")
def gcp_credentials():
    """Validate the service-account JSON in ``GOOGLE_CLOUD_API_KEY`` and expose it
    via ADC (``GOOGLE_APPLICATION_CREDENTIALS``) for the duration of the module.

    Fails (does not skip) if the provided key is not a service-account JSON: GCP
    Batch, Cloud Run Jobs and GCS need service-account credentials, not a bare API
    key.
    """
    try:
        info = json.loads(os.environ["GOOGLE_CLOUD_API_KEY"])
    except json.JSONDecodeError as error:
        raise ValueError(
            "GOOGLE_CLOUD_API_KEY is set but is not valid JSON. It must be a GCP "
            "service-account JSON key."
        ) from error

    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise ValueError(
            "GOOGLE_CLOUD_API_KEY must be a GCP service-account JSON key "
            '(a JSON object with "type": "service_account").'
        )

    previous = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(info, handle)
        credentials_path = handle.name
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
    try:
        yield info
    finally:
        if previous is None:
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        else:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = previous
        os.unlink(credentials_path)
