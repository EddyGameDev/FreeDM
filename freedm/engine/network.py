# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Part of the Download class: The HTTP side: the session, the cookies, the user's headers,"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

import requests

from freedm.engine.constants import (CONNECT_TIMEOUT,
                                   READ_TIMEOUT, USER_AGENT)
from freedm.network import PROXY, mirror_path


class NetworkMixin:
    """The HTTP side: the session, the cookies, the user's headers,
the proxy and the alternative sources (mirrors)."""

    def _session_headers(self) -> dict:
        # The cookie is carried by the jar, not as a raw header: a raw
        # `Cookie` header is dropped on every redirect and would be sent to
        # any host the session talks to.
        return {name: value for name, value in self.headers.items()
                if name.lower() != "cookie"}

    def _proxies_for(self, url: str) -> dict | None:
        """Per-request proxy override (``None`` = use the session's)."""
        return PROXY.proxies_for(url)

    def set_mirrors(self, mirrors: list[str] | None) -> None:
        """Set the alternative sources for this job (mirror base URLs)."""
        clean = []
        for item in (mirrors or []):
            text = str(item).strip()
            if text and text not in clean:
                clean.append(text)
        self.mirrors = clean
        self._source_index = 0
        self._store_save()

    @property
    def _source_count(self) -> int:
        return 1 + len(self.mirrors)

    def _advance_source(self) -> bool:
        """Move to the next mirror. True when there was one."""
        if self._source_index + 1 >= self._source_count:
            self._source_index = 0
            return False
        self._source_index += 1
        return True

    @property
    def _source_url(self) -> str:
        """The URL of the source currently in use."""
        if self._source_index == 0:
            return self.final_url or self.url
        return mirror_path(self.mirrors[self._source_index - 1],
                           self.final_url or self.url)

    @property
    def _request_url(self) -> str:
        """URL after redirects, so signed/CDN URLs are requested directly."""
        return self.final_url or self.url

    def _apply_cookies(self, cookies) -> None:
        if not cookies:
            return
        if isinstance(cookies, str):
            jar = {}
            for part in cookies.split(";"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    jar[key.strip()] = value.strip()
            self.session.cookies.update(requests.utils.cookiejar_from_dict(jar))
        elif isinstance(cookies, dict):
            self.session.cookies.update(requests.utils.cookiejar_from_dict(cookies))
        else:
            for c in cookies:
                if not isinstance(c, dict):
                    continue
                try:
                    self.session.cookies.set(
                        str(c.get("name", "")), str(c.get("value", "")),
                        domain=str(c.get("domain") or ""),
                        path=str(c.get("path") or "/"))
                except (AttributeError, ValueError):
                    # Malformed cookie entries (e.g. missing domain) are skipped
                    # rather than aborting the whole download.
                    continue

    def _apply_cookie_header(self) -> None:
        """Move a hand-written ``Cookie:`` header into the cookie jar.

        ``requests`` drops a raw ``Cookie`` header whenever it follows a
        redirect, and a session-level header is sent to *every* host the
        session talks to. Putting the value in the jar instead means it
        survives redirects to the same host and is never sent anywhere else.

        The header itself stays in ``self.headers`` so it is still saved with
        the job and restored on the next start; it is only kept out of the
        raw request headers."""
        raw = None
        for name, value in self.headers.items():
            if name.lower() == "cookie":
                raw = value
                break
        if not raw:
            return
        # The session must not send it raw.
        for name in list(self.session.headers):
            if name.lower() == "cookie":
                self.session.headers.pop(name, None)
        jar = {}
        for part in str(raw).split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                key, value = key.strip(), value.strip()
                if key:
                    jar[key] = value
        if not jar:
            return
        try:
            host = urlparse(self.final_url or self.url).hostname or ""
        except ValueError:
            host = ""
        if not host:
            return
        for key, value in jar.items():
            try:
                self.session.cookies.set(
                    key, value, domain=host, path="/")
            except (AttributeError, ValueError):
                continue

    def _validator_changed(self) -> bool:
        """True if a fresh HEAD shows a different ETag/Last-Modified."""
        if not self.validator:
            return False
        try:
            r = self.session.head(self._request_url, headers=self._session_headers(),
                                  allow_redirects=True,
                                  timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                                  proxies=self._proxies_for(self._request_url),
                                  verify=self.verify_ssl)
            current = r.headers.get("ETag") or r.headers.get("Last-Modified")
        except Exception:       # noqa: BLE001
            return False
        return bool(current and current != self.validator)

    def _source_base_url(self) -> str:
        """The URL of the source currently selected (primary or a mirror)."""
        if self._source_index == 0:
            return self.url
        return mirror_path(self.mirrors[self._source_index - 1], self.url)
