import pathlib
import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext

from upath import UPath

_LOCAL_PROTOCOLS = frozenset({"", "file", "local"})

# (type_, extension) -> {"reader": ..., "writer": ..., "native_protocols": ...}
_registry: dict[tuple, dict] = {}


def is_readable(type_):
    return any(k[0] == type_ for k in _registry)


def register_converters(
    type_,
    extension,
    reader=None,
    writer=None,
    native_protocols=frozenset(),
):
    """Register reader and/or writer for a given type and file extension.

    native_protocols: URI schemes the reader handles directly (e.g. {"gs", "https"}).
    reader must return a context manager. writer must accept (value, path_str).
    """
    _registry[(type_, extension)] = {
        "reader": reader,
        "writer": writer,
        "native_protocols": native_protocols,
    }


def as_context(function):
    """Wrap an eager reader function so it returns a nullcontext."""

    def wrapper(path):
        return nullcontext(function(path))

    return wrapper


Reader = Callable[[str | pathlib.Path], AbstractContextManager[object]]


def read(value: object, type_: type) -> AbstractContextManager[object]:
    """Convert a path or URI to the target type, returning a context manager.

    If no reader is registered for the type and file extension, the value is
    returned unchanged. Cloud URIs are streamed directly if the reader declares
    the scheme as native, otherwise downloaded to a temporary local file first.
    """
    if not isinstance(value, str | pathlib.Path | UPath):
        return nullcontext(value)
    path = UPath(str(value))
    suffix = path.suffix
    entry = _registry.get((type_, suffix))
    if entry is None or entry["reader"] is None:
        return nullcontext(value)
    reader = entry["reader"]
    if path.protocol in _LOCAL_PROTOCOLS:
        return reader(pathlib.Path(path.path))
    if path.protocol in entry["native_protocols"]:
        return reader(str(path))
    return _temporary_copy_reader(reader, path)


@contextmanager
def _temporary_copy_reader(reader: Reader, path: UPath) -> Iterator[object]:
    with tempfile.TemporaryDirectory() as directory:
        local = pathlib.Path(directory) / path.name
        local.write_bytes(path.read_bytes())
        with reader(local) as value:
            yield value


def write(value, path):
    """Write value to path using the registered writer based on file extension."""
    path = UPath(str(path))
    suffix = path.suffix
    entry = _registry.get((type(value), suffix))
    if entry is None or entry["writer"] is None:
        raise ValueError(
            f"No writer registered for {type(value).__name__} to '{suffix}'. "
            f"Register one with register_converters()."
        )
    entry["writer"](value, str(path))


@contextmanager
def _csv_reader_ctx(path):
    import csv

    with open(path, newline="") as file:
        yield csv.reader(file)


# Load all format registrations
from powerfunc.formats import arrow, csv_reader, dask, pandas, polars  # noqa: E402, F401
