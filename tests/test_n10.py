"""Milestone 2 / goal N10 tests: HLS and DASH streaming.

Run with:  python tests/test_n10.py
       or:  python -m pytest tests/test_n10.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)

import range_server                      # noqa: E402
from freedm.engine import Download, DONE, ERROR  # noqa: E402
from freedm import stream                # noqa: E402


def wait_for(dl: Download, timeout: float = 120) -> str:
    t0 = time.time()
    while dl.status not in (DONE, ERROR) and time.time() - t0 < timeout:
        time.sleep(0.2)
    return dl.status


class AesTests(unittest.TestCase):
    """The pure-Python AES-128 must be a correct implementation."""

    def test_fips_197_test_vector(self):
        from freedm.aes import decrypt_block, _expand_key
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        cipher = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
        plain = bytes.fromhex("00112233445566778899aabbccddeeff")
        self.assertEqual(decrypt_block(cipher, _expand_key(key)), plain)

    def test_the_sbox_is_the_standard_one(self):
        from freedm.aes import SBOX, INV_SBOX
        for value, expected in ((0x00, 0x63), (0x01, 0x7c), (0x53, 0xed),
                                (0xff, 0x16)):
            self.assertEqual(SBOX[value], expected, hex(value))
        for value in range(256):
            self.assertEqual(INV_SBOX[SBOX[value]], value)

    def test_cbc_matches_a_reference_implementation(self):
        try:
            from Crypto.Cipher import AES
            from Crypto.Util.Padding import pad
        except ImportError:
            self.skipTest("pycryptodome is not installed")
        from freedm.aes import decrypt_cbc
        key = bytes(range(16))
        iv = bytes(range(16, 32))
        plain = b"FreeDM stream payload " * 20
        cipher = AES.new(key, AES.MODE_CBC, iv)
        self.assertEqual(decrypt_cbc(cipher.encrypt(pad(plain, 16)), key, iv),
                         plain)


class PlaylistTests(unittest.TestCase):
    """Parsing the playlists."""

    def test_a_media_playlist(self):
        text = ("#EXTM3U\n#EXT-X-TARGETDURATION:4\n"
                "#EXTINF:4.0,\nseg0.ts\n#EXTINF:4.0,\nseg1.ts\n"
                "#EXT-X-ENDLIST\n")
        playlist = stream.parse_m3u8(text, "http://host/a/media.m3u8")
        self.assertFalse(playlist.is_master)
        self.assertEqual(len(playlist.segments), 2)
        self.assertEqual(playlist.segments[0].url, "http://host/a/seg0.ts")
        self.assertEqual(playlist.segments[0].duration, 4.0)
        self.assertEqual(playlist.total_duration, 8.0)

    def test_a_master_playlist(self):
        text = ("#EXTM3U\n"
                "#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\n"
                "low.m3u8\n"
                "#EXT-X-STREAM-INF:BANDWIDTH=2400000,RESOLUTION=1280x720\n"
                "high.m3u8\n")
        playlist = stream.parse_m3u8(text, "http://host/master.m3u8")
        self.assertTrue(playlist.is_master)
        self.assertEqual(len(playlist.variants), 2)
        best = playlist.best_variant()
        self.assertEqual(best.bandwidth, 2400000)
        self.assertEqual(best.url, "http://host/high.m3u8")

    def test_a_byte_range(self):
        text = ("#EXTM3U\n#EXTINF:4.0,\n#EXT-X-BYTERANGE:1000@2000\n"
                "seg.ts\n")
        playlist = stream.parse_m3u8(text, "http://host/m.m3u8")
        self.assertEqual(playlist.segments[0].byte_range, (1000, 2000))

    def test_an_encrypted_playlist(self):
        text = ('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key.bin",'
                'IV=0x000102030405060708090a0b0c0d0e0f\n#EXTINF:4.0,\nseg.ts\n')
        playlist = stream.parse_m3u8(text, "http://host/m.m3u8")
        self.assertTrue(playlist.encrypted)
        self.assertEqual(playlist.segments[0].key_url, "http://host/key.bin")
        self.assertEqual(len(playlist.segments[0].key_iv), 16)

    def test_a_map_segment(self):
        text = ('#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:4.0,\nseg.m4s\n')
        playlist = stream.parse_m3u8(text, "http://host/m.m3u8")
        self.assertTrue(playlist.segments[0].is_map)
        self.assertEqual(playlist.segments[0].url, "http://host/init.mp4")

    def test_a_broken_playlist(self):
        with self.assertRaises(stream.StreamError):
            stream.parse_m3u8("not a playlist", "http://host/x.m3u8")

    def test_an_empty_playlist(self):
        with self.assertRaises(stream.StreamError):
            stream.parse_m3u8("#EXTM3U\n", "http://host/x.m3u8")

    def test_a_dash_manifest(self):
        text = ("""<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">
  <Period><AdaptationSet mimeType="video/mp4">
    <Representation id="1" bandwidth="1200000">
      <SegmentTemplate media="seg-$Number$.ts" duration="4" timescale="1"
                       startNumber="1" segmentCount="3"/>
    </Representation>
  </AdaptationSet></Period>
</MPD>""")
        playlist = stream.parse_mpd(text, "http://host/dash/manifest.mpd")
        self.assertEqual(len(playlist.segments), 3)
        self.assertEqual(playlist.segments[0].url,
                         "http://host/dash/seg-1.ts")
        self.assertEqual(playlist.segments[2].url,
                         "http://host/dash/seg-3.ts")

    def test_a_dash_segment_list(self):
        text = ("""<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period><AdaptationSet>
    <Representation id="1" bandwidth="800000">
      <SegmentList duration="4" timescale="1">
        <SegmentURL media="a.ts"/>
        <SegmentURL media="b.ts"/>
      </SegmentList>
    </Representation>
  </AdaptationSet></Period>
</MPD>""")
        playlist = stream.parse_mpd(text, "http://host/dash/manifest.mpd")
        self.assertEqual([s.url for s in playlist.segments],
                         ["http://host/dash/a.ts", "http://host/dash/b.ts"])

    def test_a_broken_dash_manifest(self):
        with self.assertRaises(stream.StreamError):
            stream.parse_mpd("<nonsense/>", "http://host/x.mpd")

    def test_sniffing_a_page(self):
        html = ('<html><script>var u = "https://cdn.example/live/stream.m3u8";'
                '</script><a href="https://cdn.example/v/other.mpd">v</a>'
                '</html>')
        found = stream.sniff_page(html)
        self.assertIn("https://cdn.example/live/stream.m3u8", found)
        self.assertIn("https://cdn.example/v/other.mpd", found)

    def test_sniffing_a_page_without_a_playlist(self):
        self.assertEqual(stream.sniff_page("<html>nothing</html>"), [])

    def test_is_stream_url(self):
        self.assertTrue(stream.is_stream_url("http://x/a.m3u8"))
        self.assertTrue(stream.is_stream_url("http://x/a.mpd"))
        self.assertFalse(stream.is_stream_url("http://x/a.zip"))

    def test_output_name(self):
        self.assertEqual(stream.output_name("http://x/show.m3u8"), "show.ts")
        self.assertEqual(stream.output_name("http://x/a/b.mpd"), "b.ts")


class StreamDownloadTests(unittest.TestCase):
    """Downloading a stream end to end."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = range_server.start_server(0, 1)
        cls.port = cls.httpd.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="freedm_n10_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_an_hls_stream_is_downloaded(self):
        dl = Download(self.base + "/hls/media.m3u8", dest_dir=self.out)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertTrue(os.path.exists(dl.path))
        with open(dl.path, "rb") as fh:
            data = fh.read()
        self.assertEqual(data, b"".join(range_server.HLS_SEGMENTS))
        self.assertEqual(dl.stream_segments, 3)

    def test_a_master_playlist_is_followed(self):
        dl = Download(self.base + "/hls/master.m3u8", dest_dir=self.out)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        with open(dl.path, "rb") as fh:
            self.assertEqual(fh.read(), b"".join(range_server.HLS_SEGMENTS))

    def test_a_dash_stream_is_downloaded(self):
        dl = Download(self.base + "/dash/manifest.mpd", dest_dir=self.out)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        with open(dl.path, "rb") as fh:
            data = fh.read()
        self.assertEqual(data, b"".join(range_server.HLS_SEGMENTS))

    def test_an_encrypted_stream_is_decrypted(self):
        dl = Download(self.base + "/hls/enc.m3u8", dest_dir=self.out)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        with open(dl.path, "rb") as fh:
            data = fh.read()
        self.assertEqual(data, b"".join(range_server.HLS_SEGMENTS))
        self.assertTrue(dl.stream_encrypted)

    def test_the_file_name_comes_from_the_playlist(self):
        dl = Download(self.base + "/hls/media.m3u8", dest_dir=self.out)
        dl.start()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        self.assertTrue(dl.path.endswith(".ts"), dl.path)

    def test_the_stream_resumes_after_a_pause(self):
        dl = Download(self.base + "/hls/media.m3u8", dest_dir=self.out)
        dl.start()
        time.sleep(0.4)
        dl.pause()
        time.sleep(0.4)
        dl.resume()
        self.assertEqual(wait_for(dl), DONE, dl.error)
        with open(dl.path, "rb") as fh:
            self.assertEqual(fh.read(), b"".join(range_server.HLS_SEGMENTS))

    def test_a_broken_playlist_fails_cleanly(self):
        dl = Download(self.base + "/nope.m3u8", dest_dir=self.out)
        dl.start()
        self.assertEqual(wait_for(dl), ERROR)
        self.assertTrue(dl.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
