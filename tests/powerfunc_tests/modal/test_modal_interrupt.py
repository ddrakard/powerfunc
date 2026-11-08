"""Errors Modal's runner swallows still reach the caller; no Modal account needed.

Modal's runner catches a ``KeyboardInterrupt`` raised inside ``app.run()``, and when detached
also a ``ConnectionError``, and leaves the ``with`` block normally. ``App.run`` is replaced by a
context manager that does the same, and the work inside the block is made to raise, so nothing
is sent to Modal.
"""

import contextlib

import modal
import pytest

from powerfunc.compute import ComputeSpecification
from powerfunc.providers.modal import ModalProvider
from powerfunc_tests.remote_jobs import remote_add


@pytest.fixture(autouse=True)
def swallowing_run(monkeypatch):
    """``App.run`` that swallows what Modal's does."""

    @contextlib.contextmanager
    def run(self, *, detach=False, **arguments):
        try:
            yield self
        except KeyboardInterrupt:
            pass
        except ConnectionError:
            if not detach:
                raise

    monkeypatch.setattr(modal.App, "run", run)


def raiser(error):
    def raise_error(*arguments, **keywords):
        raise error

    return raise_error


def _call(detach):
    remote_add(
        2,
        3,
        compute=ComputeSpecification(
            cpu=1.0, memory=1024, timeout=300.0, provider=ModalProvider(detach=detach)
        ),
    )


def _notes(error):
    return " ".join(getattr(error, "__notes__", []))


@pytest.mark.parametrize("detach", [False, True])
def test_ctrl_c_during_call(monkeypatch, detach):
    monkeypatch.setattr(modal.Function, "remote", raiser(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt) as raised:
        _call(detach)
    assert ("modal app stop" in _notes(raised.value)) == detach


def test_lost_connection_while_detached(monkeypatch):
    monkeypatch.setattr(modal.Function, "remote", raiser(ConnectionError("gone")))
    with pytest.raises(ConnectionError, match="gone") as raised:
        _call(True)
    assert "modal app stop" in _notes(raised.value)


def test_ctrl_c_during_image_resolution(monkeypatch):
    monkeypatch.setattr(modal.Image, "_get_metadata", raiser(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        _call(False)


def test_other_errors_unchanged(monkeypatch):
    monkeypatch.setattr(modal.Function, "remote", raiser(ValueError("bad")))
    with pytest.raises(ValueError, match="bad") as raised:
        _call(True)
    assert _notes(raised.value) == ""
