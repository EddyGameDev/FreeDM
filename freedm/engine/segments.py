# Required Notice: Copyright (c) 2026 outlawproductionstwo-hash
"""The pieces of a file and the work queue that hands them out."""
from __future__ import annotations

from freedm.engine.constants import (DYNAMIC_SPLITTING,
                                   MAX_PIECE_SIZE, MAX_SEGMENTS,
                                   MIN_PIECE_SIZE, MIN_SEGMENT_SIZE,
                                   MIN_SPLIT_SIZE, PIECE_SPEED_SAMPLES,
                                   SPLIT_TARGET_SECONDS)


class Segment:
    __slots__ = ("index", "start", "end", "downloaded")

    def __init__(self, index: int, start: int, end: int, downloaded: int = 0):
        self.index = index
        self.start = start
        self.end = end              # inclusive
        self.downloaded = downloaded

    @property
    def size(self) -> int:
        return self.end - self.start + 1

    @property
    def remaining(self) -> int:
        return max(0, self.size - self.downloaded)

    @property
    def done(self) -> bool:
        return self.downloaded >= self.size

    def to_dict(self) -> dict:
        return {"index": self.index, "start": self.start, "end": self.end,
                "downloaded": self.downloaded}

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        return cls(d["index"], d["start"], d["end"], d.get("downloaded", 0))


class SegmentsMixin:
    """The work queue of pieces (N4).

The pending work is kept in a queue and re-divided as workers
finish, so the piece size follows the slowest connection."""

    def _prepare_pending(self) -> None:
        """Build the pending work set from the current pieces."""
        with self._lock:
            self._pending = {}
            for s in self.segments:
                if not s.done:
                    self._pending[s.index] = s
            self._next_index = max(
                (s.index for s in self.segments), default=-1) + 1
            self.initial_piece_count = len(self.segments)

    def _piece_target(self) -> int:
        """How many bytes a piece should hold (adaptive, N4).

        The target follows the *slowest* recent connection, not the average:
        one slow pipe is what decides when the file is really finished, so
        the pieces handed out stay small enough that a stalled connection
        can only hold back a little data. A fast link raises the target, so
        large files need fewer requests."""
        with self._lock:
            samples = list(self._piece_speeds)
        if not samples:
            # Nothing measured yet: be conservative so the very first pieces
            # are already small enough to be safe on a slow connection.
            return MIN_PIECE_SIZE
        target = int(min(samples) * SPLIT_TARGET_SECONDS)
        return max(MIN_PIECE_SIZE, min(MAX_PIECE_SIZE, target))

    def _note_piece_speed(self, nbytes: int, seconds: float) -> None:
        """Remember how fast the last piece was (drives the piece size)."""
        if nbytes <= 0 or seconds <= 0:
            return
        speed = nbytes / seconds
        with self._lock:
            self._piece_speeds.append(speed)
            if len(self._piece_speeds) > PIECE_SPEED_SAMPLES:
                del self._piece_speeds[:-PIECE_SPEED_SAMPLES]

    def _split_piece(self, seg: Segment, target: int) -> tuple[Segment, Segment] | None:
        """Split ``seg`` into a head of ~``target`` bytes plus the remainder.

        The already-downloaded bytes are moved to the right piece so the
        total never changes. Returns ``None`` when the piece is too small to
        split safely."""
        head_size = min(target, seg.size - MIN_SPLIT_SIZE)
        if head_size < MIN_SPLIT_SIZE:
            return None
        mid = seg.start + head_size - 1
        head = Segment(self._next_index, seg.start, mid,
                       downloaded=min(seg.downloaded, head_size))
        tail = Segment(self._next_index + 1, mid + 1, seg.end,
                       downloaded=max(0, seg.downloaded - head_size))
        self._next_index += 2
        try:
            pos = self.segments.index(seg)
        except ValueError:
            pos = -1
        if pos >= 0:
            self.segments[pos:pos + 1] = [head, tail]
        else:
            self.segments.extend((head, tail))
            self.segments.sort(key=lambda s: s.start)
        self.split_count += 1
        return head, tail

    def _claim_piece(self) -> Segment | None:
        """Take the next piece of work, splitting a large one when useful.

        The largest pending piece is always preferred, so the remaining work
        stays evenly divided and no single piece can dominate the tail. When
        that piece is much bigger than the adaptive target it is split and
        the worker takes the small half, leaving the rest for later."""
        with self._lock:
            if not self._pending:
                return None
            seg = max(self._pending.values(), key=lambda s: s.remaining)
            target = self._piece_target()
            if (DYNAMIC_SPLITTING
                    and len(self.segments) < MAX_SEGMENTS
                    and seg.remaining > target
                    and seg.size >= 2 * MIN_SPLIT_SIZE):
                pair = self._split_piece(seg, target)
                if pair is not None:
                    head, tail = pair
                    self._pending.pop(seg.index, None)
                    self._pending[tail.index] = tail
                    return head
            self._pending.pop(seg.index, None)
            return seg

    def _make_segments(self) -> list[Segment]:
        size = self.total_size
        n = self.num_threads
        if size <= MIN_SEGMENT_SIZE:
            n = 1
        else:
            n = min(self.num_threads * 4, max(self.num_threads, size // MIN_SEGMENT_SIZE))
        n = max(1, int(n))
        # N4: no single piece may be larger than MAX_PIECE_SIZE, so a slow
        # connection can only hold back a bounded amount of the file.
        if size > MAX_PIECE_SIZE:
            n = max(n, -(-size // MAX_PIECE_SIZE))

        base = size // n
        segs: list[Segment] = []
        start = 0
        for i in range(n):
            end = size - 1 if i == n - 1 else start + base - 1
            segs.append(Segment(i, start, end))
            start = end + 1
        return segs

    @staticmethod
    def _pieces_are_valid(segs: list[Segment], total_size: int = 0) -> bool:
        """True when the pieces tile the file exactly: no gaps, no overlaps.

        N4 splits pieces while downloading, so a resume must be able to
        trust the stored layout. Anything that does not tile the file is
        refused, which makes the engine restart cleanly instead of
        producing a corrupt file."""
        if not segs:
            return False
        segs = sorted(segs, key=lambda s: s.start)
        if segs[0].start != 0:
            return False
        previous_end = -1
        for s in segs:
            if s.start != previous_end + 1:
                return False
            if s.end < s.start:
                return False
            if s.downloaded < 0 or s.downloaded > s.size:
                return False
            previous_end = s.end
        if total_size and previous_end != total_size - 1:
            return False
        return True
