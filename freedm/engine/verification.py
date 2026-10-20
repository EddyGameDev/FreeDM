# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Part of the Download class: Integrity checks: the size and the optional checksum of"""
from __future__ import annotations

import os

from freedm.engine.constants import DONE, ERROR
from freedm.engine.errors import VerificationError
from freedm.verify import parse_checksum, verify_checksum, verify_size


class VerificationMixin:
    """Integrity checks: the size and the optional checksum of
the finished file (N3, N10)."""

    def _check_complete(self) -> None:
        """N3: refuse to call a short download complete.

        The server told us how many bytes to expect; if fewer arrived the file
        is truncated, so the job fails loudly instead of being reported as
        done. The partial file is kept so the user can resume it."""
        if self.total_size <= 0:
            return
        if self.downloaded == self.total_size:
            return
        raise VerificationError(
            f"incomplete download: expected {self.total_size} bytes, "
            f"got {self.downloaded}")

    def _verify_result(self) -> None:
        """Check the finished file's size and optional checksum.

        Raises :class:`VerificationError` with a clear, user-facing message
        when the file is short/long or the checksum does not match. The file
        itself is never deleted - the user may still want it."""
        path = self.path
        if not path or not os.path.exists(path):
            raise VerificationError("the finished file is missing")
        ok, message = verify_size(path, self.total_size)
        if not ok:
            self.checksum_result = message
            raise VerificationError(message)
        if self.checksum:
            ok, message, _status = verify_checksum(path, self.checksum)
            self.checksum_result = message
            if not ok:
                raise VerificationError(message)

    def verify_now(self) -> tuple[bool, str]:
        """Re-run size/checksum verification on the finished file.

        Returns ``(ok, message)``. A finished job that fails verification is
        marked ``error``; a job that is not finished keeps its status."""
        was_done = self.status == DONE
        try:
            self._verify_result()
        except VerificationError as exc:
            self.checksum_result = str(exc)
            if was_done:
                self.status = ERROR
                self.error = str(exc)
            self._store_save()
            return False, str(exc)
        if was_done:
            self.error = None
            self._store_save()
        return True, self.checksum_result

    def set_checksum(self, spec: str) -> tuple[bool, str]:
        """Set the expected checksum ("sha256:ab12...") and re-verify.

        Returns ``(ok, message)``; an invalid checksum is rejected with an
        explanation and nothing is changed."""
        try:
            algo, digest = parse_checksum(spec)
        except ValueError as exc:
            return False, str(exc)
        self.checksum = f"{algo}:{digest}" if algo else ""
        self._store_save()
        if self.status == DONE and self.path:
            return self.verify_now()
        return True, f"{algo} checksum set" if algo else "checksum cleared"
