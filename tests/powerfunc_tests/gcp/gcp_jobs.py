"""Plain helper functions executed remotely by the GCP remote-compute tests.

Kept free of test-only imports (e.g. pytest) so the remote container
can import this module after installing only powerfunc.
"""

import subprocess


def remote_add(a: int, b: int) -> int:
    return a + b


def remote_concat(prefix: str, suffix: str) -> str:
    return prefix + suffix


def gpu_name() -> str:
    """Return the name of the GPU visible inside the remote container.

    Runs ``nvidia-smi`` to confirm a GPU is actually attached and usable (not
    merely requested). Returns diagnostic info on failure (instead of raising)
    so the caller sees useful context in assertion output.
    """
    import os
    import shutil

    diagnostics: list[str] = []

    # GCP Batch mounts NVIDIA drivers at various paths depending on the host OS.
    _NVIDIA_PATHS = [
        "/usr/local/nvidia/bin",
        "/usr/bin",
        "/home/kubernetes/bin/nvidia/bin",
    ]

    # Check if nvidia-smi exists on PATH or well-known locations.
    smi_path = shutil.which("nvidia-smi")
    if not smi_path:
        for d in _NVIDIA_PATHS:
            candidate = os.path.join(d, "nvidia-smi")
            if os.path.isfile(candidate):
                smi_path = candidate
                break
    diagnostics.append(f"nvidia-smi path: {smi_path}")

    # Check /dev/nvidia* devices.
    try:
        dev_files = [f for f in os.listdir("/dev") if f.startswith("nvidia")]
    except OSError as e:
        dev_files = [f"error listing /dev: {e}"]
    diagnostics.append(f"/dev/nvidia* files: {dev_files}")

    # Try running nvidia-smi.
    smi_cmd = smi_path or "nvidia-smi"
    try:
        output = subprocess.run(
            [smi_cmd, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
        )
        diagnostics.append(f"nvidia-smi exit code: {output.returncode}")
        diagnostics.append(f"nvidia-smi stdout: {output.stdout.strip()!r}")
        diagnostics.append(f"nvidia-smi stderr: {output.stderr.strip()!r}")
        if output.returncode == 0 and output.stdout.strip():
            return output.stdout.strip()
    except FileNotFoundError:
        diagnostics.append("nvidia-smi: command not found")
    except Exception as e:
        diagnostics.append(f"nvidia-smi error: {type(e).__name__}: {e}")

    # Return diagnostics so they appear in the assertion failure message.
    return "GPU_NOT_FOUND: " + " | ".join(diagnostics)
