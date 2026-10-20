# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""The exceptions the engine raises."""
from __future__ import annotations


class DownloadCanceled(Exception):
    """Raised when an existing destination file is protected and the user
    declines to overwrite (or the policy is 'cancel')."""


class FileChangedError(IOError):
    """The remote file changed between requests, so a resume would corrupt it.
    The caller should restart the download from zero."""


class RangeNotSupportedError(IOError):
    """The server stopped honouring Range requests mid-download."""


class AuthRequiredError(IOError):
    """The server rejected the request (401/403); cookies or headers are needed."""


class VerificationError(IOError):
    """The finished file failed its size or checksum verification (N3)."""
