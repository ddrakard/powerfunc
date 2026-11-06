"""``detach`` reaches the provider's app runs; no Modal account needed.

``App.run`` is replaced, so nothing is sent to Modal: the second run, the one that would
start a container, is not entered.
"""

import contextlib

import modal
import pytest

from powerfunc.compute import ComputeSpecification
from powerfunc.providers.modal import ModalProvider
from powerfunc_tests.remote_jobs import remote_add


class Stop(Exception):
    """Ends the call at the run that would start a container."""


@pytest.fixture
def detaches(monkeypatch):
    """The ``detach`` argument of each ``App.run`` the call makes."""
    recorded = []

    @contextlib.contextmanager
    def run(self, *, detach=False, **arguments):
        recorded.append(detach)
        if len(recorded) > 1:
            raise Stop
        yield self

    monkeypatch.setattr(modal.App, "run", run)
    return recorded


def _call(detach):
    provider = ModalProvider(detach=detach)
    with pytest.raises(Stop):
        remote_add(
            2,
            3,
            compute=ComputeSpecification(cpu=1.0, memory=1024, timeout=300.0, provider=provider),
        )


def test_detaches_when_asked(detaches):
    _call(True)
    assert detaches == [True, True]


def test_ephemeral_by_default(detaches):
    _call(False)
    assert detaches == [False, False]
