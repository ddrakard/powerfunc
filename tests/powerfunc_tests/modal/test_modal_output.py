"""Unit tests of the plain output manager; no Modal account needed."""

import asyncio
import inspect

import modal
import modal_proto.api_pb2 as api_pb2
from modal._output.manager import OutputManager

from powerfunc.providers.internal.modal_output import PlainOutputManager, forward_remote_output


def _log(fd: int, data: str) -> api_pb2.TaskLogs:
    return api_pb2.TaskLogs(data=data, file_descriptor=fd)


def test_writes_remote_streams_to_local_ones(capsys):
    manager = PlainOutputManager()
    asyncio.run(manager.put_streaming_log(_log(api_pb2.FILE_DESCRIPTOR_STDOUT, "out\n")))
    asyncio.run(manager.put_fetched_log(_log(api_pb2.FILE_DESCRIPTOR_STDERR, "err\n"), "p: "))
    captured = capsys.readouterr()
    assert captured.out == "out\n"
    assert captured.err == "p: err\n"


def test_implements_the_whole_interface():
    """Every abstract method of Modal's ``OutputManager`` is implemented, so a Modal upgrade
    that adds one fails here rather than in a run."""
    assert not inspect.isabstract(PlainOutputManager)
    assert PlainOutputManager().is_enabled


def test_installed_once_and_respects_enable_output():
    previous = OutputManager.get()
    try:
        OutputManager._set(modal._output.manager._DISABLED_OUTPUT_MANAGER)
        forward_remote_output()
        installed = OutputManager.get()
        assert isinstance(installed, PlainOutputManager)
        forward_remote_output()
        assert OutputManager.get() is installed
        with modal.enable_output():
            forward_remote_output()
            assert not isinstance(OutputManager.get(), PlainOutputManager)
    finally:
        OutputManager._set(previous)
