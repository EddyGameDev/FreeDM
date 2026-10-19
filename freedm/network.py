"""Network options: proxy configuration, address-family preference and mirror
sources (Milestone 2, goal N7).

Headless - no Tkinter - so the engine, the GUI and the tests share one
definition of "how do we reach the server?".

Three independent mechanisms:

- **Proxy** (:class:`ProxyConfig`): an HTTP/SOCKS proxy with optional
  credentials, plus a bypass list for hosts that must be reached directly.
  One shared configuration, so it applies to every download.
- **Address preference** (:func:`install_address_preference`): prefer IPv4
  (or IPv6) when a host resolves to both. A half-working IPv6 route is a
  common cause of downloads that hang for minutes before falling back.
- **Mirrors** (:func:`mirror_url`): alternative sources for the same file. A
  mirror is a *base* URL; the path of the original URL is appended, so
  ``https://a.example/files/x.zip`` with the mirror ``https://b.example/mirror``
  is fetched from ``https://b.example/mirror/files/x.zip``.
"""
from __future__ import annotations

import socket
import threading
from urllib.parse import urlparse, urlunparse


class ProxyConfig:
    """Proxy settings shared by every download."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.url = ""
        self.username = ""
        self.password = ""
        self.bypass = ""          # comma separated hosts

    # -- configuration ----------------------------------------------------
    def configure(self, url: str = "", username: str = "",
                  password: str = "", bypass: str = "") -> None:
        with self._lock:
            self.url = (url or "").strip()
            self.username = (username or "").strip()
            self.password = password or ""
            self.bypass = (bypass or "").strip()

    @property
    def enabled(self) -> bool:
        with self._lock:
            return bool(self.url)

    def summary(self) -> str:
        """A safe description for the UI (never shows the password)."""
        with self._lock:
            if not self.url:
                return "no proxy"
            who = f" as {self.username}" if self.username else ""
            return f"{self.url}{who}"

    # -- helpers ----------------------------------------------------------
    def bypass_hosts(self) -> list[str]:
        with self._lock:
            return [h.strip().lower() for h in self.bypass.split(",")
                    if h.strip()]

    def is_bypassed(self, url: str) -> bool:
        """Should this URL bypass the proxy?"""
        hosts = self.bypass_hosts()
        if not hosts:
            return False
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            return False
        if not host:
            return False
        for pattern in hosts:
            if pattern == "*":
                return True
            if pattern.startswith("*."):
                if host.endswith(pattern[1:]):
                    return True
            elif host == pattern or host.endswith("." + pattern):
                return True
        return False

    def proxies(self) -> dict:
        """The ``requests`` proxy mapping for the configured proxy."""
        with self._lock:
            if not self.url:
                return {}
            url = self.url
            username, password = self.username, self.password
        if "://" not in url:
            url = "http://" + url
        if username:
            scheme, _, rest = url.partition("://")
            from urllib.parse import quote
            netloc = rest.split("/", 1)[0]
            path = rest[len(netloc):]
            host = netloc.rsplit("@", 1)[-1]
            credentials = f"{quote(username, safe='')}:{quote(password, safe='')}"
            url = f"{scheme}://{credentials}@{host}{path}"
        return {"http": url, "https": url}

    def proxies_for(self, url: str) -> dict | None:
        """The per-request proxy override, or ``None`` to use the session's.

        A bypassed host gets ``{"http": None, "https": None}``, which makes
        ``requests`` drop the proxy for that request."""
        if not self.enabled:
            return None
        if self.is_bypassed(url):
            return {"http": None, "https": None}
        return None


#: The one configuration the app uses.
PROXY = ProxyConfig()


# -- address family preference --------------------------------------------
_state = {"prefer_ipv4": True, "installed": False}
_lock = threading.Lock()

#: The real resolver, captured before we ever wrap it.
_ORIGINAL_GETADDRINFO = socket.getaddrinfo


def _sorted_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """``socket.getaddrinfo`` with the preferred address family first."""
    infos = _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)
    if not _state["prefer_ipv4"]:
        return infos
    return sorted(infos, key=lambda item: 0 if item[0] == socket.AF_INET else 1)


def install_address_preference(prefer_ipv4: bool = True) -> None:
    """Prefer IPv4 (or IPv6) when a host resolves to both.

    Installed once and toggled by the flag, so a setting change takes effect
    immediately for the next connection."""
    with _lock:
        _state["prefer_ipv4"] = bool(prefer_ipv4)
        if not _state["installed"]:
            socket.getaddrinfo = _sorted_getaddrinfo
            _state["installed"] = True


def address_preference() -> bool:
    """True when IPv4 is preferred."""
    return _state["prefer_ipv4"]


def sorted_addresses(host: str, port: int = 80,
                     prefer_ipv4: bool = True) -> list:
    """The resolved addresses of a host, preferred family first.

    Useful for diagnostics and for the "connection check" in the GUI."""
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    if not infos:
        return []
    if prefer_ipv4:
        return sorted(infos, key=lambda item: 0 if item[0] == socket.AF_INET
                      else 1)
    return sorted(infos, key=lambda item: 0 if item[0] == socket.AF_INET6
                  else 1)


# -- mirrors ---------------------------------------------------------------
def mirror_url(base: str, path: str) -> str:
    """Build the URL of a file on a mirror.

    ``base`` is the mirror's base URL, ``path`` the path of the original
    file. The result keeps the original query string, because signed URLs
    often carry one."""
    base = (base or "").strip()
    if not base:
        return ""
    if "://" not in base:
        base = "http://" + base
    parsed = urlparse(base)
    base_path = parsed.path.rstrip("/")
    original = urlparse(path or "")
    combined = f"{base_path}{original.path or '/'}"
    if not combined.startswith("/"):
        combined = "/" + combined
    return urlunparse((parsed.scheme, parsed.netloc, combined,
                       parsed.params, original.query, ""))


def mirror_path(base: str, original_url: str) -> str:
    """The URL of the original file on a mirror (see :func:`mirror_url`).

    The query string of the original is kept: signed URLs carry one."""
    try:
        parsed = urlparse(original_url)
    except ValueError:
        return mirror_url(base, "/")
    original = urlunparse(("", "", parsed.path or "/", "", parsed.query, ""))
    return mirror_url(base, original)
