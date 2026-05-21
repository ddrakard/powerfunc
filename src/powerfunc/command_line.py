import inspect
import sys

from jsonargparse import CLI

from powerfunc.configuration import configuration_paths


class ExpectedException(Exception):
    """Raised for known user errors that should display just the message, not a traceback."""


cli_functions: list[tuple] = []
_cli_active = False


def enable_cli():
    """Expose registered @powerfunc functions as CLI. Call at end of script."""
    try:
        frame = inspect.currentframe()
        if frame is None or frame.f_back is None:
            raise ExpectedException("Frame inspection not supported by this Python implementation.")
        caller_module = inspect.getmodule(frame.f_back)
        if caller_module is None or caller_module.__name__ != "__main__":
            return
        if not cli_functions:
            raise ExpectedException("No @powerfunc functions registered for CLI.")

        global _cli_active
        wrappers = [wrapper for wrapper, _ in cli_functions]
        _cli_active = True
        result = CLI(
            wrappers[0] if len(wrappers) == 1 else wrappers,
            default_config_files=configuration_paths,
        )
        if result is not None:
            print(result)
    except ExpectedException as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
