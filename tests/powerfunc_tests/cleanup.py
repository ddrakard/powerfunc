"""Delete leftover ``pf-*`` GCP Batch and Cloud Run jobs in the CI project.

Run by CI after the GCP tests, including when the run is cancelled or killed, so
that a job created by an interrupted test cannot keep running (and holding GPU
quota) behind later runs.

This is a CI safety net, so it must work even when the code under test is broken:
it deliberately uses nothing from ``src/`` (``powerfunc``) or the test package,
only the Google client libraries and the standard library. The only coupling is
the ``pf-`` name prefix that powerfunc gives its jobs.

Reads the service-account JSON from ``GOOGLE_CLOUD_API_KEY`` (project taken from
it, override with ``GCP_PROJECT``). Batch jobs are listed across all locations;
Cloud Run cannot do that, so its jobs are listed in the tests' region
(``GCP_REGION``, default ``us-central1``). Only jobs that are still running are
deleted; finished ones are inert history.
"""

import json
import os

from google.cloud import batch_v1, run_v2
from google.oauth2 import service_account

PREFIX = "pf-"
BATCH_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "DELETION_IN_PROGRESS"}


def main() -> None:
    info = json.loads(os.environ["GOOGLE_CLOUD_API_KEY"])
    credentials = service_account.Credentials.from_service_account_info(info)
    project = os.environ.get("GCP_PROJECT") or info["project_id"]
    region = os.environ.get("GCP_REGION", "us-central1")

    batch = batch_v1.BatchServiceClient(credentials=credentials)
    for job in batch.list_jobs(parent=f"projects/{project}/locations/-"):
        short_name = job.name.rsplit("/", 1)[-1]
        if short_name.startswith(PREFIX) and job.status.state.name not in BATCH_TERMINAL_STATES:
            print(f"Deleting Batch job {job.name} ({job.status.state.name})", flush=True)
            batch.delete_job(name=job.name)

    # Only jobs with a running execution: an idle job definition costs nothing, and
    # deleting every old one would exhaust the Cloud Run write quota.
    run = run_v2.JobsClient(credentials=credentials)
    executions = run_v2.ExecutionsClient(credentials=credentials)
    for job in run.list_jobs(parent=f"projects/{project}/locations/{region}"):
        short_name = job.name.rsplit("/", 1)[-1]
        if not short_name.startswith(PREFIX) or job.execution_count == 0:
            continue
        if any(not e.completion_time for e in executions.list_executions(parent=job.name)):
            print(f"Deleting Cloud Run job {job.name} (running)", flush=True)
            run.delete_job(name=job.name)


if __name__ == "__main__":
    main()
