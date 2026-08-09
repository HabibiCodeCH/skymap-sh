"""Comments come out of the wire, never out of the meaning.

The risk this file exists for is not that a comment survives -- that costs
bytes. It is that something which looks like a comment and is not gets
removed: two slashes inside a URL, a regex literal, a `/*` inside a string.
Every one of those is real in this codebase's own pages.
"""

import os
import re
import subprocess
import tempfile
import unittest

import minify


class SlashesThatAreNotComments(unittest.TestCase):
    """"//" is a comment in code, half of every absolute URL inside a
    string, and an empty alternation inside a regex. A regular expression
    over JavaScript cannot tell those apart; that is why this is not one."""

    def test_a_url_inside_a_string_survives(self):
        src = 'var u="http://skymap.sh//x";// gone\nvar a=1;'
        got = minify.strip_js_comments(src)
        self.assertIn('"http://skymap.sh//x"', got)
        self.assertNotIn("gone", got)

    def test_a_regex_holding_slashes_survives(self):
        src = "var re=/a\\/\\/b/;// gone\n"
        got = minify.strip_js_comments(src)
        self.assertIn("/a\\/\\/b/", got)
        self.assertNotIn("gone", got)

    def test_a_regex_after_return_is_not_read_as_division(self):
        """The classic trap: the character before the slash is a letter, so
        a naive reading calls it division and then loses its place."""
        src = "function f(s){return /ab\\/cd/.test(s);}// gone"
        got = minify.strip_js_comments(src)
        self.assertIn("/ab\\/cd/.test(s)", got)
        self.assertNotIn("gone", got)

    def test_division_on_both_sides_of_a_comment(self):
        got = minify.strip_js_comments("var q=a/b;/* gone */var r=c/d;")
        self.assertIn("a/b", got)
        self.assertIn("c/d", got)
        self.assertNotIn("gone", got)

    def test_a_comment_marker_inside_a_string_survives(self):
        for src in ('var s="/* not a comment */";',
                    "var s='// not a comment';"):
            self.assertEqual(minify.strip_js_comments(src), src)

    def test_an_escaped_quote_does_not_end_the_string(self):
        src = "var t='don\\'t // stop';// gone"
        got = minify.strip_js_comments(src)
        self.assertIn("don\\'t // stop", got)
        self.assertNotIn("gone", got)

    def test_a_template_literal_keeps_its_contents(self):
        src = "var t=`a // b ${x} c`;// gone"
        got = minify.strip_js_comments(src)
        self.assertIn("a // b ${x} c", got)
        self.assertNotIn("gone", got)


class WhatIsLeftBehindMatters(unittest.TestCase):
    """JavaScript ends statements at line breaks when it can, so what a
    comment leaves behind is not cosmetic."""

    def test_a_line_comment_leaves_its_newline(self):
        """Without it the next line joins the one before, and two statements
        that were never one suddenly are."""
        got = minify.strip_js_comments("var a=1;// note\nvar b=2;")
        self.assertEqual(got, "var a=1;\nvar b=2;")

    def test_a_block_that_spanned_lines_leaves_one(self):
        got = minify.strip_js_comments("var a=1;/* one\ntwo */var b=2;")
        self.assertIn("\n", got)
        self.assertNotIn("one", got)

    def test_a_block_between_two_tokens_leaves_a_space(self):
        """`a/**/b` is two tokens and has to stay two."""
        self.assertEqual(minify.strip_js_comments("a/**/b"), "a b")

    def test_an_unterminated_block_takes_the_rest(self):
        """Malformed either way -- but it must not raise."""
        self.assertEqual(minify.strip_js_comments("a;/* never closed"), "a; ")

    def test_a_stray_apostrophe_does_not_swallow_the_file(self):
        """Not hypothetical. A CSS comment in the sphere page closed early,
        which left prose containing "doesn't" sitting in the stylesheet as
        if it were code -- and a scanner that let a quoted string run past a
        newline read the next four kilobytes as one string, comments and
        all. Neither language lets a quoted string hold a raw newline."""
        css = "a{b:c}\n it doesn't matter\n /* gone */\n d{e:f}"
        self.assertNotIn("gone", minify.strip_css_comments(css))
        js = "var a=1;\n// it doesn't matter\n/* gone */\nvar b=2;"
        got = minify.strip_js_comments(js)
        self.assertNotIn("gone", got)
        self.assertIn("var b=2;", got)

    def test_a_template_literal_may_hold_a_newline(self):
        """The one string that can, so the rule above does not apply."""
        src = "var t=`line one\nline two`;// gone"
        got = minify.strip_js_comments(src)
        self.assertIn("line one\nline two", got)
        self.assertNotIn("gone", got)


class CssKeepsItsContent(unittest.TestCase):
    def test_comments_go(self):
        got = minify.strip_css_comments("a{color:red}/* gone */b{x:1}")
        self.assertNotIn("gone", got)
        self.assertIn("a{color:red}", got)
        self.assertIn("b{x:1}", got)

    def test_a_marker_inside_a_string_survives(self):
        """`content:"/*"` is content, not the start of anything."""
        src = 'b{content:"/*"}'
        self.assertEqual(minify.strip_css_comments(src), src)


class OnlyStyleAndScriptAreTouched(unittest.TestCase):
    """The HTML around them is left alone: "//" is two characters of every
    absolute URL on the page."""

    def test_html_is_untouched(self):
        page = '<p>see http://x//y</p><style>a{b:c}/*x*/</style>'
        got = minify.strip_page(page)
        self.assertIn("http://x//y", got)
        self.assertNotIn("/*x*/", got)

    def test_an_html_comment_is_left_alone(self):
        """It can be a marker something else looks for, and it is not ours
        to decide about."""
        page = "<!-- kept --><script>var a=1;//gone\n</script>"
        got = minify.strip_page(page)
        self.assertIn("<!-- kept -->", got)
        self.assertNotIn("gone", got)

    def test_a_script_that_is_not_javascript_is_left_alone(self):
        """An import map, a JSON-LD block, an HTML template -- data wearing
        a script tag. None of it has comments, and all of it would be
        damaged by a pass assuming a syntax it is not written in."""
        page = ('<script type="importmap">{"imports":{"three":"/v/t.js"}}'
                '</script>')
        self.assertEqual(minify.strip_page(page), page)

    def test_a_module_is_javascript(self):
        page = '<script type="module">var a=1;//gone\n</script>'
        self.assertNotIn("gone", minify.strip_page(page))

    def test_format_fields_are_not_disturbed(self):
        """The pages are stripped while they are still templates."""
        page = "<style>a{{b:c}}/* x */</style>{title}"
        got = minify.strip_page(page)
        self.assertIn("{title}", got)
        self.assertIn("a{{b:c}}", got)


def _node():
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


class ThePagesWeActuallyShipStillParse(unittest.TestCase):
    """The end of it. Every inline script on every page template, through a
    real JavaScript parser, after stripping."""

    @unittest.skipUnless(_node(), "node not available")
    def test_every_inline_script_parses(self):
        import api
        for name in ("PAGE", "SPHERE_PAGE"):
            page = getattr(api, name)
            found = 0
            for m in re.finditer(r"<script([^>]*)>(.*?)</script>", page, re.S):
                attrs, body = m.groups()
                kind = re.search(r'type\s*=\s*["\']?([^"\'\s>]+)', attrs or "")
                if kind and kind.group(1).lower() not in ("module", "text/javascript"):
                    continue
                if not body.strip():
                    continue
                found += 1
                # The templates carry {{ }} where the rendered page has { }.
                src = body.replace("{{", "{").replace("}}", "}")
                src = re.sub(r"\{[A-Za-z_][\w]*\}", "0", src)
                fh = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False)
                fh.write(src)
                fh.close()
                try:
                    got = subprocess.run(["node", "--check", fh.name],
                                         capture_output=True, text=True)
                    self.assertEqual(got.returncode, 0,
                                     f"{name}: {got.stderr[:400]}")
                finally:
                    os.unlink(fh.name)
            self.assertTrue(found, f"{name} had no script to check")

    def test_the_shipped_pages_carry_no_comments(self):
        import api
        for name in ("PAGE", "SPHERE_PAGE", "OBJECT_CSS"):
            page = getattr(api, name)
            for m in re.finditer(r"<style[^>]*>(.*?)</style>", page, re.S):
                self.assertNotIn("/*", m.group(1), name)

    def test_stripping_twice_changes_nothing_more(self):
        """Anything that survives one pass is not a comment."""
        import api
        self.assertEqual(minify.strip_page(api.PAGE), api.PAGE)


if __name__ == "__main__":
    unittest.main()
