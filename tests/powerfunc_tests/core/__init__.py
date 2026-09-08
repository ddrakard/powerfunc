"""Test package for powerfunc.

``cli_example`` is imported here, as a package's ``__init__`` commonly
imports its modules, so that ``python -m powerfunc_tests.core.cli_example``
runs it as ``__main__`` while the same file is also loaded under its package
name. ``enable_cli`` must still register the command line in that case: it
reads ``__name__`` from the calling module's globals, which is ``"__main__"``
for the module being run, rather than asking ``inspect.getmodule``, which would
return the package-named copy.
"""

from . import cli_example  # noqa: F401
