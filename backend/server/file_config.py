"""Helpers for loading and validating server file upload configuration."""

import os
import re

from backend.core.config import ForgeConfig
from backend.core.constants import MAX_FILENAME_LENGTH
from backend.core.logger import forge_logger as logger
from backend.server.shared import config as shared_config


def sanitize_filename(filename: str) -> str:
    """Sanitize the filename to prevent directory traversal."""
    filename = os.path.basename(filename)
    filename = re.sub("[^\\w\\-_\\.]", "", filename)
    if len(filename) > MAX_FILENAME_LENGTH:
        name, ext = os.path.splitext(filename)
        filename = name[: MAX_FILENAME_LENGTH - len(ext)] + ext
    return filename


def load_file_upload_config(
    config: ForgeConfig = shared_config,
) -> tuple[int, bool, set[str]]:
    """Load file upload configuration from the config object.

    This function retrieves the file upload settings from the global config object.
    It handles the following settings:
    - Maximum file size for uploads
    - Whether to restrict file types
    - Set of allowed file extensions

    It also performs sanity checks on the values to ensure they are valid and safe.

    Returns:
        tuple: A tuple containing:
            - max_file_size_mb (int): Maximum file size in MB. 0 means no limit.
            - restrict_file_types (bool): Whether file type restrictions are enabled.
            - allowed_extensions (set): Set of allowed file extensions.

    """
    max_file_size_mb = config.file_uploads_max_file_size_mb
    restrict_file_types = config.file_uploads_restrict_file_types
    allowed_extensions = config.file_uploads_allowed_extensions
    if not isinstance(max_file_size_mb, int) or max_file_size_mb < 0:
        logger.warning(
            "Invalid max_file_size_mb: %s. Setting to 0 (no limit).", max_file_size_mb
        )
        max_file_size_mb = 0
    if not isinstance(allowed_extensions, list | set) or not allowed_extensions:
        logger.warning(
            'Invalid allowed_extensions: %s. Setting to [".*"].', allowed_extensions
        )
        allowed_extensions = {".*"}
    else:
        allowed_extensions = {
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in allowed_extensions
        }
    if not restrict_file_types:
        allowed_extensions = {".*"}
    logger.debug(
        "File upload config: max_size=%sMB, restrict_types=%s, allowed_extensions=%s",
        max_file_size_mb,
        restrict_file_types,
        allowed_extensions,
    )
    return (max_file_size_mb, restrict_file_types, allowed_extensions)


MAX_FILE_SIZE_MB, RESTRICT_FILE_TYPES, ALLOWED_EXTENSIONS = load_file_upload_config()


def is_extension_allowed(filename: str) -> bool:
    """Check if the file extension is allowed based on the current configuration.

    This function supports wildcards and files without extensions.
    The check is case-insensitive for extensions.

    Args:
        filename (str): The name of the file to check.

    Returns:
        bool: True if the file extension is allowed, False otherwise.

    """
    if not RESTRICT_FILE_TYPES:
        return True
    file_ext = os.path.splitext(filename)[1].lower()
    return (
        ".*" in ALLOWED_EXTENSIONS
        or file_ext in (ext.lower() for ext in ALLOWED_EXTENSIONS)
        or (file_ext == "" and "." in ALLOWED_EXTENSIONS)
    )


def get_unique_filename(filename: str, folder_path: str) -> str:
    """Returns unique filename on given folder_path. By checking if the given.

    filename exists. If it doesn't, filename is simply returned.

    Otherwise, it append copy(#number) until the filename is unique.

    Args:
        filename (str): The name of the file to check.
        folder_path (str): directory path in which file name check is performed.

    Returns:
        string: unique filename.

    """
    name, ext = os.path.splitext(filename)
    filename_candidate = filename
    copy_index = 0
    while os.path.exists(os.path.join(folder_path, filename_candidate)):
        if copy_index == 0:
            filename_candidate = f"{name} copy{ext}"
        else:
            filename_candidate = f"{name} copy({copy_index}){ext}"
        copy_index += 1
    return filename_candidate
