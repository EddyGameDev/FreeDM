"""Batch URL parsing and clipboard link detection (Milestone 2, goal N2).

Deliberately headless - no Tkinter, no network - so the GUI and the tests share
one definition of "which pasted lines are links". The GUI calls
:func:`parse_urls` when adding from the URL box and :func:`find_url` when
watching the clipboard.

Design rules:
- Never silently drop input: anything that is not an http(s) URL comes back in
  the ``invalid`` list so the caller can tell the user.
- Splitting accepts pasted text where the newlines were converted to spaces
  (a Tk ``Entry`` keeps ``\\n`` today, but other widgets/platforms may not).
- Duplicates inside one paste are counted and skipped, so a repeated line does
  not create two identical jobs.
"""
from __future__ import annotations

import re

#: An http(s) URL inside arbitrary text. Stops at whitespace and at characters
#: that normally delimit a URL in prose, HTML or markdown.
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

#: Trailing characters stripped from a captured URL (sentence punctuation).
_TRAILING = ".,;:!?\"'"


def _is_url(token: str) -> bool:
    low = token.lower()
    return low.startswith("http://") or low.startswith("https://")


def _normalise(token: str) -> str:
    """Trim quotes/brackets/punctuation that wrap a URL in pasted text."""
    t = token.strip().strip("\"'`")
    # Unwrap a bracket/quote wrapper around a URL, e.g. "(https://x/y)".
    for opener, closer in (("(", ")"), ("[", "]"), ("{", "}"), ("<", ">")):
        if t.startswith(opener) and t.endswith(closer):
            inner = t[1:-1].strip().strip("\"'`")
            if _is_url(_trim(inner)):
                t = inner
                break
    return t.rstrip(_TRAILING)


def _trim(url: str) -> str:
    """Drop trailing punctuation, keeping balanced parentheses/brackets."""
    url = url.rstrip(_TRAILING)
    for opener, closer in (("(", ")"), ("[", "]")):
        while url.endswith(closer) and url.count(opener) < url.count(closer):
            url = url[:-1]
    return url


def parse_urls(text: str) -> tuple[list[str], list[str], int]:
    """Split pasted ``text`` into downloads.

    Returns ``(valid, invalid, duplicates)``:

    - ``valid`` - ordered, de-duplicated http(s) URLs to add.
    - ``invalid`` - entries that were not http(s) URLs, so they can be
      reported instead of ignored. A line with no usable URL is reported whole;
      on a mixed line the odd tokens are reported.
    - ``duplicates`` - how many valid URLs were repeats and were skipped.
    """
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    duplicates = 0

    for line in re.split(r"[\r\n]+", text or ""):
        stripped = line.strip()
        if not stripped:
            continue
        line_urls: list[str] = []
        line_bad: list[str] = []
        for token in stripped.split():
            cleaned = _normalise(token)
            if not cleaned:
                continue
            if _is_url(cleaned):
                line_urls.append(cleaned)
            else:
                line_bad.append(cleaned)

        if line_urls:
            for url in line_urls:
                if url in seen:
                    duplicates += 1
                else:
                    seen.add(url)
                    valid.append(url)
            invalid.extend(line_bad)
        else:
            # Nothing usable on this line: report it as the user typed it.
            invalid.append(stripped)

    return valid, invalid, duplicates


def find_url(text: str, exclude: frozenset[str] | set[str] = frozenset()) -> str | None:
    """Return the first http(s) URL in ``text`` (skipping ``exclude``), or None.

    Trailing sentence punctuation and unmatched closing brackets are trimmed,
    so ``See (https://example.com/x).`` yields ``https://example.com/x``.
    """
    if not text:
        return None
    for match in _URL_RE.finditer(text):
        url = _trim(match.group(0))
        if url and url not in exclude:
            return url
    return None
