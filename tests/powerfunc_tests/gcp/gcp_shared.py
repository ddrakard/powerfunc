"""Shared helpers for GCP provider tests (Cloud Run and Batch)."""

import os

from powerfunc.compute import ComputeSpecification


def get_project_and_bucket(gcp_credentials):
    """Extract project, region and bucket from credentials and environment."""
    project = os.environ.get("GCP_PROJECT") or gcp_credentials.get("project_id")
    if not project:
        raise ValueError(
            "No GCP project found: set GCP_PROJECT or use a service-account key "
            "that contains project_id."
        )
    bucket = os.environ.get("GCP_BUCKET")
    if not bucket:
        raise ValueError("GCP_BUCKET is required to run the GCP tests (e.g. gs://my-bucket).")
    region = os.environ.get("GCP_REGION", "us-central1")
    return project, region, bucket


def make_spec(provider):
    """Create a basic CPU compute spec for testing."""
    return ComputeSpecification(
        cpu=1.0, memory=2048, timeout=300.0, image="python:3.12-slim", provider=provider
    )
