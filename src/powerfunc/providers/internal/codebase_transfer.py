"""Sending the caller's codebase to the compute: zipped from the git repository holding the
function, unpacked into the container's working directory there for the setup and execute
stages."""

import inspect
import io
import os
import pathlib
import subprocess
import warnings
import zipfile
from collections.abc import Sequence
from typing import Any

from upath import UPath

from powerfunc.decorator import PowerFunc


def repository_root(function: PowerFunc) -> pathlib.Path | None:
    """The root of the git repository holding ``function``, if there is one; ``None`` (with
    a warning) means the function comes from an installed package and there is no codebase
    to send."""
    try:
        start = pathlib.Path(inspect.getfile(inspect.unwrap(function))).resolve().parent
    except TypeError:
        start = pathlib.Path.cwd()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True
    )
    if result.returncode != 0:
        warnings.warn(
            "No git repository found. Assuming the function is from an installed package "
            "and no codebase will be sent to the remote container.",
            stacklevel=2,
        )
        return None
    return pathlib.Path(result.stdout.strip())


def zip_codebase(repo_root: pathlib.Path, exclude_directories: Sequence[str] = ()) -> bytes:
    """Zip all git-tracked files of the repository at ``repo_root``, except those under the
    ``exclude_directories`` (relative to it)."""
    excluded = tuple(directory.strip("/") + "/" for directory in exclude_directories)
    files = subprocess.check_output(["git", "ls-files"], cwd=repo_root).decode().splitlines()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in files:
            if not file.startswith(excluded):
                zf.write(repo_root / file, arcname=file)
    return buffer.getvalue()


def codebase_of(function: PowerFunc) -> bytes | None:
    """The zipped codebase to send so that ``function`` is importable on the compute."""
    root = repository_root(function)
    return None if root is None else zip_codebase(root)


def unpack_codebase(spec: dict[str, Any]) -> str:
    """Unpack the codebase sent with the job into the working directory (the image's
    ``WORKDIR``, over whatever it already holds), returning it; "" if none was sent."""
    if "codebase_path" not in spec:
        return ""
    directory = os.getcwd()
    with zipfile.ZipFile(io.BytesIO(UPath(spec["codebase_path"]).read_bytes())) as archive:
        archive.extractall(directory)
    return directory
