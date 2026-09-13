"""Third stage of a remote job, for any provider: import the function and run it, in the
Python the setup stage left configured.

Run as ``python -m powerfunc.providers.internal.generic_execute_entrypoint <job spec path>
[codebase]``. See :mod:`powerfunc.providers.internal.job_specification`.
"""

import importlib
import operator
import sys
from typing import Any

import cloudpickle as pickle
from upath import UPath

from powerfunc.decorator import PowerFunc
from powerfunc.providers.internal.job_specification import (
    EXECUTE_ENTRYPOINT,
    load_job_spec,
    report_failure,
)
from powerfunc.providers.internal.secret_directories import decrypt_secret_directories


def execute(spec: dict[str, Any], codebase: str) -> None:
    """Import the function from ``codebase`` (with the secret directories decrypted into
    it), run it, write the pickled result."""
    if "secret_directories_path" in spec:
        ciphertext = UPath(spec["secret_directories_path"]).read_bytes()
        decrypt_secret_directories(ciphertext, codebase)
    kwargs = {
        name: pickle.loads(UPath(path).read_bytes())
        for name, path in spec["argument_paths"].items()
    }
    if codebase:
        sys.path.insert(0, codebase)
    module_path, qualname = spec["function"].split(":", 1)
    module = importlib.import_module(module_path)
    function: PowerFunc = operator.attrgetter(qualname)(module)
    result = function._run_without_parsing(**kwargs)
    UPath(spec["output_path"]).write_bytes(pickle.dumps(result))


def main(argv: list[str]) -> None:
    """``python -m {EXECUTE_ENTRYPOINT} <job spec path> [codebase directory]``."""
    if not 1 <= len(argv) <= 2:
        sys.exit(f"usage: python -m {EXECUTE_ENTRYPOINT} <job spec path> [codebase directory]")
    job_spec_path, codebase = [*argv, ""][:2]
    spec = load_job_spec(job_spec_path)
    try:
        execute(spec, codebase)
    except BaseException as exc:
        report_failure(spec, exc)
        raise


if __name__ == "__main__":
    main(sys.argv[1:])
