#!/usr/bin/env python3
"""Tests for the query-parsing and image-generation logic in bsky_bot.py --
the parts that don't need a live Bluesky login.

Run:  python3 test_bsky_bot.py
"""
import tempfile
import unittest
from pathlib import Path

from atproto import models

import bsky_bot


def mention_facet(text, mention_text):
    """A minimal facet marking `mention_text` (as it appears in `text`) as an
    @mention, the same shape Bluesky sends on a real post record."""
    raw = text.encode("utf-8")
    start = raw.index(mention_text.encode("utf-8"))
    end = start + len(mention_text.encode("utf-8"))
    return models.AppBskyRichtextFacet.Main(
        index=models.AppBskyRichtextFacet.ByteSlice(byte_start=start, byte_end=end),
        features=[models.AppBskyRichtextFacet.Mention(did="did:plc:fake")],
    )


class ExtractPlace(unittest.TestCase):
    def test_strips_a_leading_mention(self):
        text = "@skymap.bsky.social Tokyo"
        facets = [mention_facet(text, "@skymap.bsky.social")]
        self.assertEqual(bsky_bot.extract_place(text, facets), "Tokyo")

    def test_bare_mention_with_no_place_is_empty(self):
        text = "@skymap.bsky.social"
        facets = [mention_facet(text, "@skymap.bsky.social")]
        self.assertEqual(bsky_bot.extract_place(text, facets), "")

    def test_no_facets_falls_back_to_the_whole_text(self):
        # Shouldn't happen for a real mention notification, but a missing/
        # empty facets list must not crash the parser.
        self.assertEqual(bsky_bot.extract_place("Zurich", []), "Zurich")

    def test_a_mention_that_is_not_the_only_facet_is_left_alone(self):
        # Only @mention facets get stripped -- a link facet elsewhere in the
        # same post must survive into the place query untouched.
        text = "@skymap.bsky.social Zurich see example.com"
        facets = [
            mention_facet(text, "@skymap.bsky.social"),
            models.AppBskyRichtextFacet.Main(
                index=models.AppBskyRichtextFacet.ByteSlice(
                    byte_start=text.encode().index(b"example.com"),
                    byte_end=text.encode().index(b"example.com") + len(b"example.com"),
                ),
                features=[models.AppBskyRichtextFacet.Link(uri="https://example.com")],
            ),
        ]
        self.assertEqual(bsky_bot.extract_place(text, facets), "Zurich see example.com")


class StatePersistence(unittest.TestCase):
    def setUp(self):
        self._orig_state_file = bsky_bot.STATE_FILE
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.addCleanup(setattr, bsky_bot, "STATE_FILE", self._orig_state_file)
        bsky_bot.STATE_FILE = Path(self._tmpdir.name) / "state.json"

    def test_missing_file_returns_epoch_and_empty_stats(self):
        last_seen, stats = bsky_bot.load_state()
        self.assertEqual(last_seen, bsky_bot.EPOCH)
        self.assertEqual(dict(stats), {})

    def test_round_trips_last_seen_and_stats(self):
        bsky_bot.save_state("2026-08-01T00:00:00.000Z", {"replies": 3, "errors": 1})
        last_seen, stats = bsky_bot.load_state()
        self.assertEqual(last_seen, "2026-08-01T00:00:00.000Z")
        self.assertEqual(stats["replies"], 3)
        self.assertEqual(stats["errors"], 1)


class SkyPng(unittest.TestCase):
    def test_known_place_returns_png_bytes_and_a_resolved_name(self):
        png, name = bsky_bot.sky_png("Zurich")
        self.assertIsNotNone(png)
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertEqual(name, "Zürich")

    def test_unknown_place_returns_nothing(self):
        png, name = bsky_bot.sky_png("Nowhereville Notacity")
        self.assertIsNone(png)
        self.assertIsNone(name)


if __name__ == "__main__":
    unittest.main()
