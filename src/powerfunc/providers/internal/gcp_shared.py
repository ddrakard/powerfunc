"""What the GCP providers share: artifacts in a bucket, and the container bootstrap.

A provider subclasses :class:`GCPJobProvider` and implements ``_submit_job`` to run a
container with :func:`bootstrap_command` as its command.
"""

import collections.abc
import importlib.metadata
import json
import random
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import cloudpickle as pickle
from upath import UPath

from powerfunc.compute import ComputeSpecification, Provider
from powerfunc.decorator import PowerFunc
from powerfunc.providers.internal.codebase_transfer import repository_root, zip_codebase
from powerfunc.providers.internal.job_specification import (
    GET_UV,
    PATH_PREFIX,
    SETUP_ENTRYPOINT,
    function_identifier,
    job_spec,
)
from powerfunc.providers.internal.secret_directories import (
    KEY_VARIABLE,
    encrypt_secret_directories,
)

MAX_JOB_NAME_LENGTH = 63  # GCP resource name limit (Cloud Run and Batch)


def bootstrap_command(job_spec_path: UPath, error_gcs_path: str = "") -> str:
    """Shell command run in the remote container: the first of the job's three stages.

    1. This bootstrap needs nothing from the image: it gets `uv
       <https://docs.astral.sh/uv/>`_ via a fallback chain (existing → curl → wget →
       pip → apt-get install curl) and uses ``uv run`` — ephemeral environment with
       powerfunc, Python downloaded if needed — to start the generic setup entrypoint.
    2. setup unpacks the codebase and runs the job's ``setup_command`` in it.
    3. setup then runs the generic execute entrypoint with the ``python`` that command left
       on ``PATH`` (the image's own if there was no command), which imports and runs the
       function. That Python must have powerfunc installed.

    Requires at least one of: ``curl``, ``wget``, ``pip``, or
    ``apt-get`` (to install ``curl``).

    If *error_gcs_path* is provided, on failure the **entire** output
    (including the install step) is uploaded to GCS via ``gsutil``, ``curl``,
    or Python ``urllib``.
    """
    # The setup stage runs the same powerfunc version as the caller.
    powerfunc_version = importlib.metadata.version("powerfunc")
    run_cmd = (
        f'uv run --with "powerfunc=={powerfunc_version}" --with "pydantic>=2" '
        f"python -m {SETUP_ENTRYPOINT} {job_spec_path}"
    )
    main_cmd = GET_UV + " && " + run_cmd
    if error_gcs_path:
        gcs_no_prefix = error_gcs_path.replace("gs://", "", 1)
        bucket, _, obj_name = gcs_no_prefix.partition("/")
        encoded_name = urllib.parse.quote(obj_name, safe="")
        upload_url = (
            f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}"
            f"/o?uploadType=media&name={encoded_name}"
        )
        py_upload = (
            "import json,urllib.request,sys;"
            "t=json.loads(urllib.request.urlopen(urllib.request.Request("
            '"http://metadata.google.internal/computeMetadata/v1/instance/'
            'service-accounts/default/token",'
            'headers={"Metadata-Flavor":"Google"})).read())["access_token"];'
            'd=open("/tmp/pf_out.txt","rb").read();'
            "urllib.request.urlopen(urllib.request.Request(sys.argv[1],"
            'data=d,method="POST",'
            'headers={"Authorization":"Bearer "+t,'
            '"Content-Type":"application/octet-stream"}))'
        )

        # curl-based upload using GCE metadata server token (no Python needed).
        curl_upload = (
            'PF_TOKEN=$(curl -sf -H "Metadata-Flavor: Google" '
            '"http://metadata.google.internal/computeMetadata/v1/instance/'
            'service-accounts/default/token" '
            '| grep -o \'"access_token":"[^"]*"\' | cut -d\'"\' -f4) && '
            'curl -sf -H "Authorization: Bearer $PF_TOKEN" '
            '-H "Content-Type: application/octet-stream" '
            f"--data-binary @/tmp/pf_out.txt '{upload_url}'"
        )

        return (
            PATH_PREFIX + f"({main_cmd}) > /tmp/pf_out.txt 2>&1; "
            "PF_RC=$?; cat /tmp/pf_out.txt; "
            "if [ $PF_RC -ne 0 ]; then "
            f"gsutil cp /tmp/pf_out.txt {error_gcs_path} 2>/dev/null || "
            f"{curl_upload} 2>/dev/null || "
            f"python3 -c '{py_upload}' '{upload_url}' 2>/dev/null || "
            f"python -c '{py_upload}' '{upload_url}' 2>/dev/null || "
            "true; fi; exit $PF_RC"
        )
    return PATH_PREFIX + main_cmd


def generate_names(
    names: collections.abc.Collection[str], user_identifier: str = ""
) -> dict[str, str]:
    """Generate unique qualified names for artifact storage.

    Returns a mapping from original to generated name, prefixed with *user_identifier* if set.
    """
    prefix_parts = []
    if user_identifier:
        prefix_parts.append(user_identifier)
    prefix_parts.append(time.strftime("%Y%m%d_%H%M%S"))
    prefix_parts.append(str(random.randint(0, 999999)).zfill(6))
    prefix = "_".join(prefix_parts)
    return {name: f"{prefix}_{name}" for name in names}


@dataclass
class GCPJobProvider(Provider):
    """Base of the GCP providers: puts the job's artifacts in ``temporary_bucket_path`` and
    reads the result back; subclasses submit the container."""

    project: str
    region: str
    temporary_bucket_path: str
    setup_command: str = ""
    """Shell command run in the sent codebase before the function, which must leave a python
    with powerfunc installed first on PATH; empty if the image has one."""
    environment_variables: dict[str, str] = field(default_factory=dict)
    """Environment variables of the running function."""
    secret_directories: list[str] = field(default_factory=list)
    """Directories, relative to the codebase's git root, sent encrypted rather than with the
    codebase: for credentials and other files git ignores."""
    user_identifier: str = ""
    """Prefix for the artifact names, to tell your jobs apart in a shared bucket."""

    def _generate_paths(self, names: collections.abc.Collection[str]) -> dict[str, UPath]:
        # "powerfunc" prefix ensures we don't pollute the user's directory
        # if they pass a bucket root as temporary_bucket_path
        base = UPath(self.temporary_bucket_path) / "powerfunc"
        generated_names = generate_names(names, self.user_identifier)
        return {name: base / generated for name, generated in generated_names.items()}

    def _submit_job(
        self,
        job_name: str,
        compute: ComputeSpecification,
        job_spec_path: UPath,
        environment: dict[str, str],
    ) -> None:
        """Run a container with ``compute.image``, ``environment`` as its variables and
        ``bootstrap_command(...)`` as its ``sh -c`` command, and wait for it to finish."""
        raise NotImplementedError

    def call(self, function: PowerFunc, arguments: dict, compute: ComputeSpecification) -> Any:
        function_id = function_identifier(function)
        root = repository_root(function)
        codebase = None if root is None else zip_codebase(root, self.secret_directories)
        secret_directories = encrypt_secret_directories(root, self.secret_directories)
        environment = dict(self.environment_variables)

        artifact_names = ["_output", "_job_spec"] + [f"_argument_{k}" for k in arguments]
        if codebase is not None:
            artifact_names = ["_codebase", *artifact_names]
        if secret_directories is not None:
            artifact_names = ["_secret_directories", *artifact_names]
        paths = self._generate_paths(artifact_names)

        try:
            if codebase is not None:
                paths["_codebase"].write_bytes(codebase)
            if secret_directories is not None:
                paths["_secret_directories"].write_bytes(secret_directories[0])
                environment[KEY_VARIABLE] = secret_directories[1]

            for name, value in arguments.items():
                paths[f"_argument_{name}"].write_bytes(pickle.dumps(value))

            spec = job_spec(
                function_id,
                str(paths["_output"]),
                {name: str(paths[f"_argument_{name}"]) for name in arguments},
                self.setup_command,
                str(paths["_codebase"]) if codebase is not None else None,
                str(paths["_secret_directories"]) if secret_directories is not None else None,
            )
            paths["_job_spec"].write_bytes(json.dumps(spec).encode())

            job_name = ("pf-" + paths["_output"].name.replace("_", "-"))[:MAX_JOB_NAME_LENGTH]
            self._submit_job(job_name, compute, paths["_job_spec"], environment)

            result = pickle.loads(paths["_output"].read_bytes())
        finally:
            for path in paths.values():
                try:
                    path.unlink()
                except Exception:
                    pass

        return result
