"""brand.py is the only place these strings are allowed to be written out.

A constants module is a convention until something enforces it. Nothing
stops the next hand-written link from going straight into api.py, and it
would work, and it would be found the next time somebody renames an
account and misses one. So this scans the source for the literals and
fails if one turns up outside brand.py.

Test files are exempt and should keep spelling the URLs out in full. A
test that asserts brand.X is in the page, using brand.X, passes whatever
brand.X happens to say -- including a typo. The point of the assertions
in test_server.py is that a human wrote the expected URL by hand.
"""
import pathlib
import re
import unittest

import brand

HERE = pathlib.Path(__file__).parent

# Whole strings, and the fragments a hand-written link is likely to use:
# somebody adding a second Bluesky link will type "bsky.app", not the full
# profile URL, so matching only the exact constant would let it through.
FORBIDDEN = {
    "bsky.app": brand.BLUESKY,
    "x.com/": brand.X,
    "reddit.com/r/": brand.REDDIT,
    "github.com/HabibiCodeCH": f"{brand.GITHUB} / brand.ISSUES",
    brand.AT_HANDLE: "brand.AT_HANDLE",
}

# brand.py holds them by definition. Test files assert on them by design.
# build_*.py are one-shot catalogue builders that talk to VizieR and JPL,
# not to anything with a social account, but they are excluded by the same
# rule as the tests: they are not what a reader sees.
EXEMPT = {"brand.py", "test_brand.py"}


def _sources():
    for p in sorted(HERE.glob("*.py")):
        if p.name in EXEMPT or p.name.startswith(("test_", "build_")):
            continue
        yield p


class LinksLiveInBrandOnly(unittest.TestCase):

    def test_no_source_file_hardcodes_a_link(self):
        # Comments are stripped first. api.py's icon block explains what the
        # links replaced, naming the handle that used to be there, and a
        # sentence about history is not a link somebody has to maintain.
        offenders = []
        for path in _sources():
            for n, line in enumerate(path.read_text().split("\n"), 1):
                code = re.sub(r"#.*$", "", line)
                if code.lstrip().startswith(('"""', "'''")):
                    continue
                for literal, use in FORBIDDEN.items():
                    if literal in code:
                        offenders.append(
                            f"{path.name}:{n} writes {literal!r} -- use {use}")
        self.assertEqual(offenders, [], "\n".join([""] + offenders))

    def test_the_constants_are_actually_the_published_accounts(self):
        # Hand-written, so a fat-fingered edit to brand.py fails here rather
        # than shipping a dead link on every page of the site.
        self.assertEqual(brand.HANDLE, "skymapsh")
        self.assertEqual(brand.AT_HANDLE, "@skymapsh")
        self.assertEqual(brand.SITE, "skymap.sh")
        self.assertEqual(brand.X, "https://x.com/skymapsh")
        self.assertEqual(brand.BLUESKY, "https://bsky.app/profile/skymap.sh")
        self.assertEqual(brand.REDDIT, "https://www.reddit.com/r/skymap/")
        self.assertEqual(brand.GITHUB,
                         "https://github.com/HabibiCodeCH/skymap-sh")
        self.assertEqual(brand.ISSUES,
                         "https://github.com/HabibiCodeCH/skymap-sh/issues/new")

    def test_every_link_is_https_and_has_no_trailing_space(self):
        for name in ("GITHUB", "ISSUES", "REDDIT", "BLUESKY", "X"):
            url = getattr(brand, name)
            self.assertTrue(url.startswith("https://"), name)
            self.assertEqual(url, url.strip(), name)


if __name__ == "__main__":
    unittest.main()
