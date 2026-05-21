import os
import pathlib
from contextlib import contextmanager, nullcontext

from cloudpathlib import AnyPath, CloudPath

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


def read(value, type_):
    """Convert a path or URI to the target type, returning a context manager.

    If no reader is registered for the type and file extension, the value is
    returned unchanged. Cloud URIs are streamed directly if the reader declares
    the scheme as native, otherwise downloaded locally via cloudpathlib first.
    """
    if not isinstance(value, (str, pathlib.Path, CloudPath)):
        return nullcontext(value)
    path = AnyPath(str(value))
    suffix = path.suffix
    entry = _registry.get((type_, suffix))
    if entry is None or entry["reader"] is None:
        return nullcontext(value)
    reader = entry["reader"]
    native_protocols = entry["native_protocols"]
    if isinstance(path, CloudPath):
        scheme = type(path).cloud_prefix.replace("://", "")
        if scheme in native_protocols:
            return reader(str(path))
        return reader(pathlib.Path(os.fspath(path)))
    return reader(pathlib.Path(value))


def write(value, path):
    """Write value to path using the registered writer based on file extension."""
    path = AnyPath(str(path))
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
