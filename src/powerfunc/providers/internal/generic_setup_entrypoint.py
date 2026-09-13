"""Second stage of a remote job, for any provider: unpack the codebase into the working
directory (the image's ``WORKDIR``), run the job's ``setup_command`` there, then run
:mod:`powerfunc.providers.internal.generic_execute_entrypoint` in the same shell — so whatever
``python`` the command leaves first on ``PATH`` runs the function.

Run as ``python -m powerfunc.providers.internal.generic_setup_entrypoint <job spec path>`` by the
provider's bootstrap. See :mod:`powerfunc.providers.internal.job_specification`.
"""

import os
import shlex
import subprocess
import sys
from typing import Any

from upath import UPath

from powerfunc.providers.internal.codebase_transfer import unpack_codebase
from powerfunc.providers.internal.job_specification import (
    EXECUTE_ENTRYPOINT,
    SETUP_ENTRYPOINT,
    load_job_spec,
    report_failure,
)


def run_setup_then_execute(setup_command: str, job_spec_path: str, codebase: str) -> int:
    """Run ``setup_command`` (possibly empty) then :data:`EXECUTE_ENTRYPOINT`, in one ``sh``
    so whatever ``python`` the command leaves first on ``PATH`` runs the function."""
    execute = f"exec python -m {EXECUTE_ENTRYPOINT} {shlex.quote(job_spec_path)}"
    if codebase:
        execute += " " + shlex.quote(codebase)
    script = f"{setup_command} && {execute}" if setup_command.strip() else execute
    return subprocess.run(["sh", "-c", script]).returncode


def setup(spec: dict[str, Any], job_spec_path: str) -> int:
    """Unpack the codebase, run the setup command in it, then execute."""
    try:
        codebase = unpack_codebase(spec)
        code = run_setup_then_execute(spec.get("setup_command", ""), job_spec_path, codebase)
    except BaseException as exc:
        report_failure(spec, exc)
        raise
    if code != 0 and not UPath(spec["output_path"] + "__error").exists():
        report_failure(spec, RuntimeError(f"setup_command or python exited with code {code}"))
    return code


def main(argv: list[str]) -> int:
    """``python -m {SETUP_ENTRYPOINT} <job spec path>``: returns the exit code."""
    if len(argv) != 1:
        sys.exit(f"usage: python -m {SETUP_ENTRYPOINT} <job spec path>")
    (job_spec_path,) = argv
    if "://" not in job_spec_path:
        job_spec_path = os.path.abspath(job_spec_path)
    return setup(load_job_spec(job_spec_path), job_spec_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
