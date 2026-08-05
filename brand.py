"""Every outward-facing link and handle the project publishes, in one place.

These strings are not confined to one screen. The handle appears in the
terminal footer, in the events page's linked version of that same footer,
and burnt into every exported GIF and PNG; the links appear in the header
icon row on every page and in the feedback box. Renaming the X account
meant finding six literals across two modules and nine baked-in copies in
the generated demo page, and the way to know you had found them all was to
grep for a string you were in the middle of deleting.

Nothing here is computed and nothing imports anything, so this module can
be imported from anywhere without a cycle.

test_brand.py enforces the one-place rule: it scans the other source files
for these literals and fails if one reappears. Test files are exempt on
purpose, and should keep writing the URL out in full: a test that asserts
brand.X == brand.X passes no matter how wrong brand.X is.
"""

# The account the site posts from, without the "@". Callers add it back:
# the footer wants "@skymapsh" and the URL wants the bare name, and
# storing one form means one of them is always doing surgery on a string.
HANDLE = "skymapsh"

# The domain, as written to a reader. Not a URL: it is a wordmark here, and
# every place it appears is prose (the GIF watermark, the footer sentence).
SITE = "skymap.sh"

GITHUB = "https://github.com/HabibiCodeCH/skymap-sh"
# Deep link to the "new issue" form rather than the issue list. The feedback
# box is aimed at somebody who has just spotted a wrong number and has one
# sentence in mind; the list asks them to find the button first.
ISSUES = GITHUB + "/issues/new"
REDDIT = "https://www.reddit.com/r/skymap/"
# The project's own profile, not a personal one.
BLUESKY = "https://bsky.app/profile/skymap.sh"
X = "https://x.com/" + HANDLE

# "@skymapsh", ready to drop into a sentence.
AT_HANDLE = "@" + HANDLE
