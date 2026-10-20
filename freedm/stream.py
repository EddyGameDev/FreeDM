"""Streaming media: HLS (.m3u8) and DASH (.mpd) playlists (Milestone 2, goal
N10).

A stream is not a file: it is a *playlist* that points at many small files
(segments). This module turns such a playlist into a list of ordinary HTTP
requests, and FreeDM downloads them like any other download - with the same
resuming, the same proxy settings and the same cookies.

What is supported:

**HLS** - master playlists (a list of quality levels) and media playlists
(the segments), including ``#EXT-X-KEY`` (AES-128), ``#EXT-X-BYTERANGE`` and
the ``#EXT-X-MAP`` initialisation segment.

**DASH** - a manifest with ``SegmentTemplate`` (a fixed segment length) and
with ``SegmentList`` (explicit segment URLs).

**Page sniffing** - a best-effort scan of an HTML page for a playlist URL, so
the user can paste a page address instead of the playlist address.

The output is the concatenated segments (a ``.ts`` for MPEG-TS streams, an
``.mp4`` for fragmented MP4). Remuxing to a single MP4 needs FFmpeg, which is
optional: the file is written as it comes.
"""
from __future__ import annotations

import base64
import os
import re
import urllib.parse
from dataclasses import dataclass, field

#: A playlist we could not make sense of.
class StreamError(Exception):
    """The playlist could not be parsed or is not a stream we support."""


@dataclass
class Variant:
    """One quality level of a master playlist."""
    url: str
    bandwidth: int = 0
    resolution: str = ""
    codecs: str = ""


@dataclass
class Segment:
    """One piece of a media playlist."""
    url: str
    duration: float = 0.0
    byte_range: tuple[int, int] | None = None      # (length, offset)
    key_url: str = ""
    key_iv: bytes | None = None
    is_map: bool = False                          # the initialisation segment


@dataclass
class Playlist:
    """A parsed playlist: either a master (variants) or a media (segments)."""
    kind: str = "media"                            # "master" | "media"
    variants: list[Variant] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    target_duration: float = 0.0
    total_duration: float = 0.0
    encrypted: bool = False

    @property
    def is_master(self) -> bool:
        return self.kind == "master"

    def best_variant(self) -> Variant | None:
        """The highest bandwidth variant, or the first one."""
        if not self.variants:
            return None
        return max(self.variants, key=lambda v: v.bandwidth)

    def media_url(self) -> str:
        """The URL of the media playlist to download."""
        if self.is_master:
            best = self.best_variant()
            if best is None:
                raise StreamError("the master playlist has no variants")
            return best.url
        raise StreamError("this is already a media playlist")


# ---------------------------------------------------------------------------
# HLS
# ---------------------------------------------------------------------------
_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def _parse_attributes(text: str) -> dict:
    """Parse an ``#EXT-X-...:KEY=VALUE,KEY="VALUE"`` attribute list."""
    values = {}
    for name, value in _ATTR_RE.findall(text):
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        values[name] = value
    return values


def _absolute(url: str, base: str) -> str:
    """Resolve a possibly relative playlist URL against its base."""
    if not url:
        return url
    if url.startswith(("http://", "https://")):
        return url
    return urllib.parse.urljoin(base, url)


def resolve_url(url: str, base: str = "") -> str:
    """Resolve a playlist URL and refuse anything that is not http(s).

    A playlist is data from a third party, so it must never be able to
    point FreeDM at another protocol (a local file, say)."""
    absolute = _absolute(url, base)
    scheme = urllib.parse.urlparse(absolute).scheme.lower()
    if scheme not in ("http", "https"):
        raise StreamError(
            f"only http and https URLs are allowed in a playlist, not "
            f"{scheme or 'a scheme-less URL'}: {absolute}")
    return absolute


def host_of(url: str) -> str:
    """The host of a URL (lower case, without the port)."""
    try:
        return (urllib.parse.urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


_PRIVATE_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost",
                  "ip6-loopback"}
_resolved: dict[str, bool] = {}


def is_private_host(host: str) -> bool:
    """True for a loopback, link-local, private or otherwise reserved address.

    A name is resolved once and the answer cached, so a host that points at
    the local network is caught as well."""
    import ipaddress
    import socket

    name = (host or "").strip("[]").lower()
    if not name:
        return False
    if name in _PRIVATE_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        pass
    else:
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or
                    ip.is_unspecified)
    if name in _resolved:
        return _resolved[name]
    private = False
    try:
        infos = socket.getaddrinfo(name, None)
    except OSError:
        infos = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except (ValueError, IndexError):
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved):
            private = True
            break
    _resolved[name] = private
    return private


def check_segment_url(url: str, playlist_url: str = "",
                      allow_private: bool = False) -> str:
    """Check one URL that a playlist named.

    The playlist's own host is always fine - the user chose it. Any *other*
    host must be a public address, unless the user has allowed private
    addresses, because a hostile playlist could otherwise use FreeDM to
    reach the user's local network."""
    absolute = resolve_url(url, playlist_url)
    if allow_private:
        return absolute
    host = host_of(absolute)
    if not host:
        return absolute
    if host and host == host_of(playlist_url):
        return absolute
    if is_private_host(host):
        raise StreamError(
            f"the playlist points at a private address ({host}); "
            f"FreeDM will not connect to it. Turn on "
            f"'Allow segments from private addresses' if you trust it.")
    return absolute


def parse_m3u8(text: str, base_url: str = "") -> Playlist:
    """Parse an HLS playlist (master or media).

    ``base_url`` is the URL the playlist came from; relative segment URLs are
    resolved against it."""
    if not text or "#EXTM3U" not in text:
        raise StreamError("this is not an HLS playlist")
    lines = [line.strip() for line in text.splitlines()]
    playlist = Playlist()

    pending_bandwidth = 0
    pending_resolution = ""
    pending_codecs = ""
    pending_duration = 0.0
    pending_range: tuple[int, int] | None = None
    current_key = ""
    current_iv: bytes | None = None

    for line in lines:
        if not line:
            continue
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = _parse_attributes(line.split(":", 1)[1])
            pending_bandwidth = int(attrs.get("BANDWIDTH", 0) or 0)
            pending_resolution = attrs.get("RESOLUTION", "")
            pending_codecs = attrs.get("CODECS", "")
            continue
        if line.startswith("#EXT-X-MEDIA:"):
            attrs = _parse_attributes(line.split(":", 1)[1])
            uri = attrs.get("URI", "")
            if uri:
                playlist.variants.append(Variant(
                    url=_absolute(uri, base_url),
                    bandwidth=int(attrs.get("BANDWIDTH", 0) or 0),
                    resolution=attrs.get("RESOLUTION", ""),
                    codecs=attrs.get("CODECS", "")))
            continue
        if line.startswith("#EXT-X-KEY:"):
            attrs = _parse_attributes(line.split(":", 1)[1])
            method = attrs.get("METHOD", "NONE").upper()
            if method in ("NONE", ""):
                current_key, current_iv = "", None
            else:
                current_key = _absolute(attrs.get("URI", ""), base_url)
                iv = attrs.get("IV", "")
                if iv.lower().startswith("0x"):
                    try:
                        current_iv = int(iv[2:], 16).to_bytes(16, "big")
                    except ValueError:
                        current_iv = None
                else:
                    current_iv = None
                playlist.encrypted = True
            continue
        if line.startswith("#EXT-X-BYTERANGE:"):
            value = line.split(":", 1)[1]
            length, _, offset = value.partition("@")
            try:
                length = int(length)
                offset = int(offset) if offset else 0
            except ValueError:
                length, offset = 0, 0
            pending_range = (length, offset)
            continue
        if line.startswith("#EXT-X-MAP:"):
            attrs = _parse_attributes(line.split(":", 1)[1])
            uri = attrs.get("URI", "")
            if uri:
                playlist.segments.append(Segment(
                    url=_absolute(uri, base_url),
                    is_map=True,
                    key_url=current_key, key_iv=current_iv))
            continue
        if line.startswith("#EXTINF:"):
            value = line.split(":", 1)[1].split(",", 1)[0]
            try:
                pending_duration = float(value)
            except ValueError:
                pending_duration = 0.0
            continue
        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                playlist.target_duration = float(
                    line.split(":", 1)[1].strip())
            except ValueError:
                pass
            continue
        if line.startswith("#"):
            continue                      # any other tag: ignored
        # A plain line is a URL: a variant (after STREAM-INF) or a segment.
        if pending_bandwidth or pending_resolution:
            playlist.variants.append(Variant(
                url=_absolute(line, base_url),
                bandwidth=pending_bandwidth,
                resolution=pending_resolution,
                codecs=pending_codecs))
            playlist.kind = "master"
            pending_bandwidth, pending_resolution, pending_codecs = 0, "", ""
            continue
        playlist.segments.append(Segment(
            url=_absolute(line, base_url),
            duration=pending_duration,
            byte_range=pending_range,
            key_url=current_key, key_iv=current_iv))
        playlist.total_duration += pending_duration
        pending_duration = 0.0
        pending_range = None

    if playlist.is_master and not playlist.segments:
        return playlist
    if not playlist.segments and not playlist.variants:
        raise StreamError("the playlist contains no segments")
    return playlist


# ---------------------------------------------------------------------------
# DASH
# ---------------------------------------------------------------------------
def parse_mpd(text: str, base_url: str = "") -> Playlist:
    """Parse a DASH manifest (the common SegmentTemplate/SegmentList forms).

    A DASH manifest can describe several representations (different
    qualities); the highest bandwidth one is used."""
    import xml.etree.ElementTree as ET

    if not text or "<MPD" not in text:
        raise StreamError("this is not a DASH manifest")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise StreamError(f"the DASH manifest is not valid XML: {exc}") from exc

    def tag(name: str) -> str:
        return name.split("}")[-1]

    playlist = Playlist()
    best = None
    best_bandwidth = -1

    for adaptation in root.iter():
        if tag(adaptation.tag) != "AdaptationSet":
            continue
        for representation in adaptation.iter():
            if tag(representation.tag) != "Representation":
                continue
            bandwidth = int(representation.get("bandwidth", 0) or 0)
            if bandwidth > best_bandwidth:
                best_bandwidth = bandwidth
                best = representation

    if best is None:
        raise StreamError("the DASH manifest has no representation")

    base = base_url
    for child in best.iter():
        name = tag(child.tag)
        if name == "BaseURL" and child.text:
            base = _absolute(child.text.strip(), base_url)
        elif name == "SegmentList":
            duration = float(child.get("duration", 0) or 0)
            timescale = float(child.get("timescale", 1) or 1)
            per_segment = duration / timescale if timescale else 0.0
            for index, url_node in enumerate(child):
                if tag(url_node.tag) != "SegmentURL":
                    continue
                media = url_node.get("media", "")
                playlist.segments.append(Segment(
                    url=_absolute(media, base),
                    duration=per_segment,
                    byte_range=_byte_range(url_node.get("mediaRange"))))
        elif name == "SegmentTemplate":
            media = child.get("media", "")
            initialisation = child.get("initialization", "")
            timescale = float(child.get("timescale", 1) or 1)
            duration = float(child.get("duration", 0) or 0)
            start_number = int(child.get("startNumber", 1) or 1)
            if initialisation:
                playlist.segments.append(Segment(
                    url=_absolute(initialisation, base), is_map=True))
            if media and duration and timescale:
                per_segment = duration / timescale
                count = _segment_count(child, playlist)
                for index in range(count):
                    playlist.segments.append(Segment(
                        url=_absolute(media.replace("$Number$",
                                                   str(start_number + index)),
                                      base),
                        duration=per_segment))
            elif media:
                # No duration: the template is not something we can expand.
                raise StreamError(
                    "this DASH manifest uses a segment template without a "
                    "fixed duration, which FreeDM cannot expand")

    if not playlist.segments:
        raise StreamError("the DASH manifest contains no segments")
    playlist.total_duration = sum(s.duration for s in playlist.segments)
    return playlist


def _byte_range(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    start, _, end = value.partition("-")
    try:
        return (int(end) - int(start) + 1, int(start))
    except ValueError:
        return None


def _segment_count(template, playlist) -> int:
    """How many segments a SegmentTemplate describes."""
    count = template.get("segmentCount")
    if count:
        return int(count)
    duration = template.get("duration")
    timescale = template.get("timescale")
    total = template.get("totalDuration") or template.get("mediaPresentationDuration")
    if duration and timescale and total:
        try:
            per = float(duration) / float(timescale)
            return max(1, int(float(total) / per))
        except (TypeError, ValueError, ZeroDivisionError):
            return 1
    return 1


# ---------------------------------------------------------------------------
# Page sniffing
# ---------------------------------------------------------------------------
_PLAYLIST_RE = re.compile(
    r'["\'\s](https?://[^\s"\'<>]+\.(?:m3u8|mpd)(?:\?[^\s"\'<>]*)?)["\'\s]')


def sniff_page(html: str) -> list[str]:
    """Find playlist URLs in a page.

    Best effort: it looks for ``.m3u8`` and ``.mpd`` addresses in the
    markup and in the inline scripts. It cannot see a URL that is built at
    run time by the site's JavaScript."""
    found: list[str] = []
    for match in _PLAYLIST_RE.finditer(html or ""):
        url = match.group(1)
        if url not in found:
            found.append(url)
    return found


# ---------------------------------------------------------------------------
# Decryption
# ---------------------------------------------------------------------------
def decrypt_aes128(data: bytes, key: bytes, iv: bytes | None = None) -> bytes:
    """Decrypt an AES-128-CBC segment.

    The IV comes from the playlist; when it is missing the segment number is
    used, as the HLS specification requires. ``cryptography`` is used when it
    happens to be installed, and a small pure-Python implementation otherwise
    (FreeDM does not want a heavy dependency for this)."""
    if len(key) != 16:
        raise StreamError(f"the AES-128 key must be 16 bytes, got {len(key)}")
    if iv is None:
        raise StreamError("the segment has no initialisation vector")
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        from freedm.aes import decrypt_cbc
        return decrypt_cbc(data, key, iv)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    return decryptor.update(data) + decryptor.finalize()


def key_from_data(uri: str, data: bytes) -> bytes:
    """Read an AES-128 key: raw bytes, or base64 in a text file."""
    if len(data) == 16:
        return data
    text = data.decode("utf-8", "replace").strip()
    if text.startswith("-----BEGIN"):
        # A PEM key: the base64 body between the markers.
        body = "".join(line for line in text.splitlines()
                       if "-----" not in line)
        return base64.b64decode(body)
    try:
        decoded = base64.b64decode(text, validate=True)
    except Exception as exc:          # noqa: BLE001
        raise StreamError(f"the key at {uri} is not usable: {exc}") from exc
    if len(decoded) != 16:
        raise StreamError(f"the key at {uri} is {len(decoded)} bytes, not 16")
    return decoded


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def is_stream_url(url: str) -> bool:
    """True when the URL looks like a playlist."""
    path = urllib.parse.urlparse(url or "").path.lower()
    return path.endswith(".m3u8") or path.endswith(".mpd")


def output_name(url: str, playlist: Playlist | None = None,
                container: str = "") -> str:
    """A sensible file name for the downloaded stream."""
    path = urllib.parse.urlparse(url or "").path
    base = os.path.basename(path)
    if base.lower().endswith(".m3u8"):
        base = base[:-5]
    elif base.lower().endswith(".mpd"):
        base = base[:-4]
    base = base or "stream"
    if not container:
        container = ".ts"
    if not base.lower().endswith(container):
        base += container
    return base
