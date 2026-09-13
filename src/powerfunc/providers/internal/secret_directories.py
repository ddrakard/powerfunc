"""Sending a provider's ``secret_directories`` to the compute: zipped and
encrypted with a key made for the call, the ciphertext travelling with the job's other
artifacts and the key alone by the provider's environment-variable side channel
(``KEY_VARIABLE``). The execute stage decrypts them into the codebase directory, at their
original relative paths, before the function runs."""

import io
import os
import pathlib
import zipfile
from typing import Optional

from cryptography.fernet import Fernet

from powerfunc.command_line import ExpectedException

KEY_VARIABLE = "POWERFUNC_SECRET_DIRECTORIES_KEY"


def encrypt_secret_directories(
    root: Optional[pathlib.Path], relative_paths: list[str]
) -> Optional[tuple[bytes, str]]:
    """The directories at ``relative_paths`` under ``root``, zipped and encrypted, with the
    key to decrypt them; ``None`` if there are none to send."""
    if not relative_paths:
        return None
    if root is None:
        raise ExpectedException(
            "secret_directories are relative to the codebase's git repository, "
            "but no codebase was found to send."
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in relative_paths:
            directory = root / relative
            if not directory.is_dir():
                raise ExpectedException(f"secret directory {directory} does not exist")
            for file in sorted(path for path in directory.rglob("*") if path.is_file()):
                archive.write(file, arcname=str(file.relative_to(root)))
    key = Fernet.generate_key()
    return Fernet(key).encrypt(buffer.getvalue()), key.decode()


def decrypt_secret_directories(ciphertext: bytes, directory: str) -> None:
    """Unpack the encrypted zip into ``directory`` with the key from ``KEY_VARIABLE``."""
    key = os.environ.get(KEY_VARIABLE)
    if not key:
        raise ExpectedException(
            f"secret directories were sent but {KEY_VARIABLE} is not set in the environment"
        )
    with zipfile.ZipFile(io.BytesIO(Fernet(key.encode()).decrypt(ciphertext))) as archive:
        for name in archive.namelist():
            if pathlib.PurePosixPath(name).is_absolute() or ".." in name.split("/"):
                raise ExpectedException(f"secret directories archive has unsafe path {name}")
        archive.extractall(directory)
