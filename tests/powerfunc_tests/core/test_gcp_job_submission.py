"""The GCP providers' ``call`` submits its job under the generated ``pf-`` name.

The bucket is a local directory and the submission is replaced, so nothing reaches GCP.
"""

from dataclasses import dataclass

import pytest

from powerfunc.compute import ComputeSpecification
from powerfunc.providers.internal.gcp_shared import GCPJobProvider
from powerfunc_tests.remote_jobs import remote_add


class Submitted(Exception):
    """Ends the call at submission, carrying the job name."""


@dataclass
class RecordingProvider(GCPJobProvider):
    def _submit_job(self, job_name, compute, job_spec_path, environment):
        raise Submitted(job_name)


@pytest.mark.parametrize("user_identifier", ["", "ci"])
def test_job_submitted_under_generated_name(tmp_path, user_identifier):
    (tmp_path / "powerfunc").mkdir()  # a bucket needs no directories; a local path does
    provider = RecordingProvider(
        project="project",
        region="region",
        temporary_bucket_path=str(tmp_path),
        user_identifier=user_identifier,
    )
    with pytest.raises(Submitted) as submitted:
        remote_add(
            2,
            3,
            compute=ComputeSpecification(cpu=1.0, memory=1024, timeout=60.0, provider=provider),
        )
    job_name = submitted.value.args[0]
    assert job_name.startswith("pf-" + (f"{user_identifier}-" if user_identifier else ""))
    assert job_name.endswith("--output")
