"""Modal's client output, reduced to the container's stdout and stderr.

Modal's own display (``modal.enable_output()``) draws an in-place status tree on the terminal
through one process-wide object; two apps started at once in one process corrupt it. This
manager forwards only the remote process's stdout and stderr, to the local ones, and draws
nothing, so it can be shared by any number of concurrent runs.
"""

import sys

import modal_proto.api_pb2
from modal._output.manager import DisabledOutputManager, OutputManager


class PlainOutputManager(DisabledOutputManager):
    """Writes the remote container's stdout and stderr to the local ones; no status display."""

    @property
    def is_enabled(self) -> bool:
        return True

    async def put_streaming_log(self, log: modal_proto.api_pb2.TaskLogs, prefix: str = "") -> None:
        stream = (
            sys.stderr
            if log.file_descriptor == modal_proto.api_pb2.FILE_DESCRIPTOR_STDERR
            else sys.stdout
        )
        stream.write(prefix + log.data)
        stream.flush()

    async def put_fetched_log(self, log: modal_proto.api_pb2.TaskLogs, prefix: str = "") -> None:
        await self.put_streaming_log(log, prefix)


def forward_remote_output() -> None:
    """Install :class:`PlainOutputManager` as Modal's output manager unless output is already
    enabled (a ``modal.enable_output()`` in force is respected). The manager is stateless, so
    it is installed once for the process rather than per run: a per-run install and restore
    would race between threads and leave a run without its logs."""
    if not OutputManager.get().is_enabled:
        OutputManager._set(PlainOutputManager())  # pyright: ignore[reportPrivateUsage]
