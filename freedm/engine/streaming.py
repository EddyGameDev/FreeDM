# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""Part of the Download class: Streaming media: HLS and DASH playlists (N10)."""
from __future__ import annotations

import os
import time

from freedm.engine.constants import (CONNECT_TIMEOUT,
                                   MAX_RETRIES, READ_TIMEOUT)
from freedm.stream import (StreamError, check_segment_url,
                           decrypt_aes128, host_of as stream_host_of,
                           is_stream_url, key_from_data, parse_m3u8,
                           parse_mpd)


class StreamingMixin:
    """Streaming media: HLS and DASH playlists (N10).

A playlist is data from a third party, so this is also where
the URL policy lives: only http(s) is allowed, private
addresses need the user's permission, and the user's own
headers never follow the playlist to another host."""

    def _looks_like_playlist(self, content_type: str, url: str) -> bool:
        """True when the response is a stream playlist, not a file."""
        kind = (content_type or "").split(";")[0].strip().lower()
        if kind in ("application/vnd.apple.mpegurl", "application/x-mpegurl",
                    "audio/mpegurl", "application/dash+xml"):
            return True
        return is_stream_url(url)

    def _fetch_playlist(self, url: str):
        """Download and parse one playlist."""
        response = self.session.get(
            url, headers=self._session_headers(),
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            proxies=self._proxies_for(url),
            verify=self.verify_ssl, allow_redirects=True)
        try:
            text = response.text
            final = response.url or url
            kind = (response.headers.get("Content-Type") or "").lower()
        finally:
            response.close()
        if "dash+xml" in kind or final.lower().endswith(".mpd"):
            return parse_mpd(text, final)
        return parse_m3u8(text, final)

    def _load_playlist(self):
        """The playlist of this stream (a master playlist is followed)."""
        playlist = self._fetch_playlist(self._request_url)
        if playlist.is_master:
            best = playlist.best_variant()
            if best is None:
                raise StreamError("the master playlist has no variants")
            playlist = self._fetch_playlist(best.url)
        return playlist

    def _run_stream(self) -> bool:
        """Download a stream's segments into the .part file.

        The segments are written one after the other, so the result is the
        whole stream in one file. A small sidecar remembers what is already
        on disk, so an interrupted stream continues instead of starting over.
        """
        playlist = self._load_playlist()
        segments = playlist.segments
        if not segments:
            raise StreamError("the playlist contains no segments")
        self.stream_playlist = playlist
        self.stream_segments = len(segments)
        self.stream_encrypted = playlist.encrypted

        state_file = (self.state_path or "") + ".stream.json"
        sizes = self._read_stream_state(state_file)
        skip = min(len(sizes), len(segments))
        done_bytes = sum(sizes[:skip])
        if done_bytes and os.path.exists(self.part_path or ""):
            try:
                with open(self.part_path, "r+b") as fh:
                    fh.truncate(done_bytes)
            except OSError:
                skip, done_bytes = 0, 0

        appending = bool(done_bytes) and os.path.exists(self.part_path or "")
        with open(self.part_path, "ab" if appending else "wb") as out:
            if not appending:
                self.downloaded = 0
            for index in range(skip, len(segments)):
                data = self._fetch_segment(segments[index], index)
                out.write(data)
                done_bytes += len(data)
                self.downloaded = done_bytes
                self._store_save()
                self._save_stream_state(state_file, segments, index + 1)
        self.total_size = max(self.total_size, done_bytes)
        return True

    def _read_stream_state(self, path: str) -> list[int]:
        """The sizes of the segments already written (for a resume)."""
        if not path or not os.path.exists(path):
            return []
        try:
            import json
            with open(path, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
            if saved.get("url") != self.url:
                return []
            return [int(s) for s in saved.get("sizes", [])]
        except (OSError, ValueError, TypeError):
            return []

    def _save_stream_state(self, path: str, segments, count: int) -> None:
        """Remember what is on disk, so an interrupted stream can continue."""
        if not path:
            return
        try:
            import json
            sizes = self._read_stream_state(path)
            while len(sizes) < count:
                sizes.append(0)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"url": self.url, "sizes": sizes[:count]}, fh)
        except OSError:
            pass

    def _stream_headers(self, url: str) -> dict:
        """The user's own headers only go to the playlist's own host.

        A playlist is data from a third party: it must not be able to make
        FreeDM send the user's ``Authorization`` (or ``Referer``) header to a
        host the user never chose."""
        if stream_host_of(url) == stream_host_of(self._request_url):
            return self._session_headers()
        return {}

    def _check_stream_url(self, url: str) -> str:
        """Apply the playlist URL policy (see freedm/stream.py)."""
        return check_segment_url(url, self._request_url,
                                allow_private=bool(self.allow_private_segments))

    def _fetch_segment(self, segment, index: int) -> bytes:
        """Fetch one segment, decrypting it when the playlist says so."""
        segment.url = self._check_stream_url(segment.url)
        headers = self._stream_headers(segment.url)
        if segment.byte_range:
            length, offset = segment.byte_range
            headers["Range"] = f"bytes={offset}-{offset + length - 1}"
        attempt = 0
        while True:
            try:
                response = self.session.get(
                    segment.url, headers=headers,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    proxies=self._proxies_for(segment.url),
                    verify=self.verify_ssl, allow_redirects=True)
                try:
                    if response.status_code >= 400:
                        raise IOError(f"HTTP {response.status_code}")
                    data = response.content
                finally:
                    response.close()
                break
            except Exception as exc:      # noqa: BLE001
                attempt += 1
                if attempt > MAX_RETRIES:
                    raise IOError(f"segment {index} failed: {exc}") from exc
                time.sleep(min(2 ** attempt * 0.5, 10))
        if segment.key_url:
            key = self._fetch_key(segment)
            iv = segment.key_iv or index.to_bytes(16, "big")
            data = decrypt_aes128(data, key, iv)
        return data

    def _fetch_key(self, segment) -> bytes:
        """Fetch an AES-128 key."""
        segment.key_url = self._check_stream_url(segment.key_url)
        response = self.session.get(
            segment.key_url, headers=self._stream_headers(segment.key_url),
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            proxies=self._proxies_for(segment.key_url),
            verify=self.verify_ssl, allow_redirects=True)
        try:
            data = response.content
        finally:
            response.close()
        return key_from_data(segment.key_url, data)
