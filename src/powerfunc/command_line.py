import inspect
import sys
from collections.abc import Callable

from jsonargparse import CLI

from powerfunc.configuration import configuration_paths


class ExpectedException(Exception):
    """Raised for known user errors that should display just the message, not a traceback."""


# Each function's parsed-arguments entry, by the function's name: the command's.
cli_functions: dict[str, Callable] = {}


def enable_cli():
    """Expose registered @powerfunc functions as CLI. Call at end of script."""
    try:
        frame = inspect.currentframe()
        if frame is None or frame.f_back is None:
            raise ExpectedException("Frame inspection not supported by this Python implementation.")
        # By the frame's globals, not inspect.getmodule: under ``python -m`` the same
        # file is often imported by its package name too, and getmodule finds that one.
        if frame.f_back.f_globals.get("__name__") != "__main__":
            return
        if not cli_functions:
            raise ExpectedException("No @powerfunc functions registered for CLI.")

        result = CLI(
            next(iter(cli_functions.values())) if len(cli_functions) == 1 else cli_functions,
            default_config_files=configuration_paths,
        )
        if result is not None:
            print(result)
    except ExpectedException as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
