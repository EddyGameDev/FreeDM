"""Tests for the release-notes tooling (CHANGELOG.md -> GitHub release notes).

The changelog is the single source of truth for the patch notes of every
build, so the tool that extracts a section must be reliable.

Run with:  python tests/test_changelog.py
       or:  python -m pytest tests/test_changelog.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

import release_notes                     # noqa: E402

SAMPLE = """# Changelog

## [Unreleased]

Nothing yet.

## [v1.0.0] - 2026-10-19

First public build.

### Build

- `FreeDM-1.0.0.exe` (17.5 MB)

### Fixed

- Something

## [v1.1.0] - unreleased

Automation.

### Added

- Scheduled starts
"""


class ChangelogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freedm_notes_")
        self.path = os.path.join(self.tmp, "CHANGELOG.md")
        with open(self.path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(SAMPLE)
        self.text = release_notes.read_changelog(self.path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lists_the_versions(self):
        found = release_notes.versions(self.text)
        self.assertEqual(found, ["Unreleased", "v1.0.0", "v1.1.0"])

    def test_extracts_a_section(self):
        body = release_notes.section(self.text, "v1.0.0")
        self.assertIn("First public build.", body)
        self.assertIn("### Build", body)
        self.assertNotIn("Automation.", body)

    def test_sections_do_not_run_into_each_other(self):
        self.assertIn("Scheduled starts",
                      release_notes.section(self.text, "v1.1.0"))
        self.assertNotIn("First public build.",
                         release_notes.section(self.text, "v1.1.0"))

    def test_unknown_version_returns_none(self):
        self.assertIsNone(release_notes.section(self.text, "v9.9.9"))
        self.assertIsNone(release_notes.notes(self.text, "v9.9.9"))

    def test_heading_can_be_included(self):
        with_heading = release_notes.notes(self.text, "v1.0.0", True)
        self.assertTrue(with_heading.startswith("## [v1.0.0]"))
        without = release_notes.notes(self.text, "v1.0.0", False)
        self.assertFalse(without.startswith("## ["))

    def test_cli_writes_a_file(self):
        out = os.path.join(self.tmp, "notes.md")
        code = release_notes.main(["v1.0.0", "--file", out,
                                   "--changelog", self.path])
        self.assertEqual(code, 0)
        with open(out, "r", encoding="utf-8") as fh:
            self.assertIn("First public build.", fh.read())

    def test_cli_reports_an_unknown_version(self):
        code = release_notes.main(["v9.9.9", "--changelog", self.path])
        self.assertEqual(code, 1)

    def test_cli_lists_versions(self):
        self.assertEqual(
            release_notes.main(["--list", "--changelog", self.path]), 0)

    def test_hash_helper(self):
        import hashlib
        target = os.path.join(self.tmp, "blob.bin")
        with open(target, "wb") as fh:
            fh.write(b"freedm" * 1000)
        expected = hashlib.sha256(b"freedm" * 1000).hexdigest()
        self.assertEqual(release_notes.sha256_of(target), expected)


class ProjectChangelogTests(unittest.TestCase):
    """The project's own changelog must stay usable."""

    def setUp(self):
        self.path = os.path.join(os.path.dirname(_HERE), "CHANGELOG.md")
        self.text = release_notes.read_changelog(self.path)

    def test_the_project_changelog_exists(self):
        self.assertTrue(os.path.exists(self.path))

    def test_it_has_a_section_for_the_published_release(self):
        self.assertIn("v1.0.0", release_notes.versions(self.text))
        body = release_notes.section(self.text, "v1.0.0")
        self.assertIn("### Build", body)
        self.assertIn("FreeDM-1.0.0.exe", body)
        self.assertIn("SHA-256", body)

    def test_every_section_lists_its_build(self):
        for version in release_notes.versions(self.text):
            if version == "Unreleased":
                continue
            body = release_notes.section(self.text, version)
            self.assertIn("### Build", body, version)


if __name__ == "__main__":
    unittest.main(verbosity=2)
