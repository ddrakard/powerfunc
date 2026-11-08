"""The GCP container bootstrap runs the setup stage on the caller's Python version."""

import sys

from upath import UPath

from powerfunc.providers.internal.gcp_shared import bootstrap_command


def test_setup_stage_uses_callers_python_version():
    command = bootstrap_command(UPath("gs://bucket/job_spec"))
    version = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert f"uv run --python {version} " in command
