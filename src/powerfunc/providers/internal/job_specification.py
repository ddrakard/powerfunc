"""What the providers share about a remote job: on the caller's side, the function's
identifier, the JSON *spec* sent to the compute and the shell snippets that get ``uv`` onto an
arbitrary image for the first stage; on the compute's side, reading the spec back and
reporting failures. The codebase is sent by :mod:`powerfunc.providers.internal.codebase_transfer`;
the stages run on the compute are :mod:`powerfunc.providers.internal.generic_setup_entrypoint` and
:mod:`powerfunc.providers.internal.generic_execute_entrypoint`.
"""

import json
import traceback
from typing import Any

from upath import UPath

import __main__
from powerfunc.command_line import ExpectedException
from powerfunc.decorator import PowerFunc

SETUP_ENTRYPOINT = "powerfunc.providers.internal.generic_setup_entrypoint"
EXECUTE_ENTRYPOINT = "powerfunc.providers.internal.generic_execute_entrypoint"

# Where uv's installer (``$HOME/.local/bin``) and ``pip install uv`` (``/usr/local/bin``) put it.
PATH_PREFIX = 'export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"; '

_UV_URL = "https://astral.sh/uv/install.sh"
GET_UV = (
    "{ command -v uv >/dev/null 2>&1 || "
    "{ command -v curl >/dev/null 2>&1 && curl -LsSf " + _UV_URL + " | sh; } || "
    "{ command -v wget >/dev/null 2>&1 && wget -qO- " + _UV_URL + " | sh; } || "
    "{ command -v pip >/dev/null 2>&1 && pip install uv -q; } || "
    "{ apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq curl >/dev/null 2>&1 "
    "&& curl -LsSf " + _UV_URL + " | sh; }; }"
)
"""Shell: ensure ``uv`` is on PATH, trying existing → curl → wget → pip → apt-get curl."""


# Caller side


def job_spec(
    function: str,
    output_path: str,
    argument_paths: dict[str, str],
    setup_command: str = "",
    codebase_path: str | None = None,
    secret_directories_path: str | None = None,
) -> dict[str, Any]:
    """The JSON-able spec the compute-side stages read; ``function`` is ``module:qualname``,
    ``secret_directories_path`` holds the encrypted zip of
    :mod:`powerfunc.providers.internal.secret_directories`."""
    spec: dict[str, Any] = {
        "function": function,
        "output_path": output_path,
        "argument_paths": argument_paths,
        "setup_command": setup_command,
    }
    if codebase_path is not None:
        spec["codebase_path"] = codebase_path
    if secret_directories_path is not None:
        spec["secret_directories_path"] = secret_directories_path
    return spec


def function_identifier(function: PowerFunc) -> str:
    """``module:qualname`` by which the compute imports the function."""
    if function.__module__ == "__main__":
        if __main__.__spec__ is None:
            raise ExpectedException(
                "Run your script with 'python -m my_script' instead of "
                "'python my_script.py' to enable remote execution."
            )
        module_name = __main__.__spec__.name
    else:
        module_name = function.__module__
    return f"{module_name}:{function.__qualname__}"


# Compute side


def load_job_spec(job_spec_path: str) -> dict[str, Any]:
    return json.loads(UPath(job_spec_path).read_bytes().decode())


def report_failure(spec: dict[str, Any], exc: BaseException) -> None:
    """Write the error to a sibling of the output path so the caller can retrieve it."""
    error_info = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
    try:
        UPath(spec["output_path"] + "__error").write_bytes(error_info.encode())
    except Exception:
        pass
