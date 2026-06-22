"""Live integration tests for Modal remote compute.

These run a real function on Modal via
:class:`powerfunc.providers.modal.ModalProvider` and assert the returned value.

The helper functions (``remote_add``, ``remote_concat``) are defined with
``__module__ = "__main__"`` so that cloudpickle serialises their bytecode
instead of recording a module reference.  Without this, Modal's remote
container would try to import ``powerfunc_tests`` — which doesn't exist there.
"""

from powerfunc.providers.modal import ModalCpuSmall, ModalProvider


def _spec():
    return ModalCpuSmall(timeout=300.0)


def remote_add(a: int, b: int) -> int:
    return a + b


remote_add.__module__ = "__main__"


def remote_concat(prefix: str, suffix: str) -> str:
    return prefix + suffix


remote_concat.__module__ = "__main__"


def test_modal_remote_returns_value():
    """A plain function runs on Modal and its return value comes back."""
    provider = ModalProvider()
    result = provider.call(remote_add, {"a": 2, "b": 3}, _spec())
    assert result == 5


def test_modal_remote_passes_arguments():
    """Arguments are serialized and delivered to the remote function."""
    provider = ModalProvider()
    result = provider.call(remote_concat, {"prefix": "power", "suffix": "func"}, _spec())
    assert result == "powerfunc"
