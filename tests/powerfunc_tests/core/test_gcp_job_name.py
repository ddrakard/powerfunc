"""GCP job names: kept whole, or a clear error when ``user_identifier`` makes them too long."""

import pytest

from powerfunc.command_line import ExpectedException
from powerfunc.providers.internal.gcp_shared import (
    MAX_JOB_NAME_LENGTH,
    generate_names,
    job_name,
)


def _name(user_identifier):
    output = generate_names(["_output"], user_identifier)["_output"]
    return job_name(output, user_identifier)


def test_short_identifier_keeps_whole_name():
    name = _name("ci")
    assert name.startswith("pf-ci-")
    assert name.endswith("--output")
    assert len(name) <= MAX_JOB_NAME_LENGTH


def test_longest_identifier_that_fits():
    # pf- + identifier + -YYYYMMDD-HHMMSS-NNNNNN--output is 33 characters plus the identifier.
    assert len(_name("x" * 29)) == MAX_JOB_NAME_LENGTH


def test_too_long_identifier_raises():
    with pytest.raises(ExpectedException, match="Shorten the provider's user_identifier"):
        _name("x" * 30)
