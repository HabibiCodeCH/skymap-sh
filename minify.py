"""Comments out of the CSS and JS the pages ship, once at import time.

The source keeps every comment it has. This file is why it can: the reader
of the code gets the reasoning, and the reader of the page gets none of it.
On a chart page that is about 22 KB gzipped, on every view, spent saying
things to nobody.

Only comments go. Not whitespace, not newlines, not identifiers -- this is
not a minifier and should not become one. A blank line where a paragraph
used to be costs almost nothing once gzip has seen it, and the moment this
starts renaming things or joining lines it becomes a source of bugs that
only appear in production, which is exactly the trade nobody wants for a
few more kilobytes.

Newlines are kept for a reason beyond taste: JavaScript ends statements at
line breaks when it can (automatic semicolon insertion), so a block comment
that spanned three lines has to leave a newline behind or two statements
that were never joined suddenly are.

The JS side is a tokeniser rather than a regular expression because "//"
means nothing on its own. It is a comment in code, two characters of a URL
inside a string, and a pair of empty alternations inside a regex literal --
and a regex literal is itself only distinguishable from division by what
came before it. A regular expression over this either misses comments or
eats code, and which one it does depends on the file.
"""

import re

# What can appear immediately before a `/` that opens a regex literal. After
# a value -- a name, a number, a closing bracket -- a slash is division;
# after an operator or the start of a statement it is a regex. This is the
# standard way to tell them apart without parsing, and it is why the word
# list below exists: `return /x/.test(s)` ends in a letter and would read as
# division without it.
_REGEX_OK_CHARS = set("(,=:[!&|?{};+-*%~^<>\n")
_REGEX_OK_WORDS = {"return", "typeof", "instanceof", "in", "of", "new",
                   "delete", "void", "case", "do", "else", "yield", "await"}


def _regex_can_start(before):
    """Whether a `/` at this point opens a regex literal rather than divides.

    `before` is everything emitted so far. Only its tail matters."""
    tail = before.rstrip()
    if not tail:
        return True
    if tail[-1] in _REGEX_OK_CHARS:
        return True
    m = re.search(r"[A-Za-z_$][\w$]*$", tail)
    return bool(m) and m.group(0) in _REGEX_OK_WORDS


def strip_js_comments(src):
    """JavaScript with its comments removed and everything else untouched.

    Walks the source once, in one of a handful of states: ordinary code, one
    of the three kinds of string, a regex literal, or a comment. Only the
    last is dropped.

    A line comment leaves its newline behind (the line break may be ending a
    statement). A block comment leaves a newline if it spanned one and a
    space if it did not -- a space rather than nothing because `a/**/b` is
    two tokens and must stay two."""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""

        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j        # the newline itself is left in place
            continue

        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            body = src[i:] if j < 0 else src[i:j + 2]
            i = n if j < 0 else j + 2
            out.append("\n" if "\n" in body else " ")
            continue

        if c in "\"'`":
            j, closed = i + 1, False
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == c:
                    closed = True
                    break
                # A quoted string cannot hold a raw newline; only a template
                # literal can. Stopping here is what keeps one stray
                # apostrophe from swallowing the rest of the file -- which
                # is not hypothetical: an unclosed comment left a "doesn't"
                # sitting in the sphere page's CSS, and a scanner without
                # this read the next four kilobytes as one string.
                if src[j] == "\n" and c != "`":
                    break
                j += 1
            if closed:
                out.append(src[i:j + 1])
                i = j + 1
                continue
            out.append(c)
            i += 1
            continue

        if c == "/" and _regex_can_start("".join(out)):
            j, in_class, closed = i + 1, False, False
            while j < n:
                d = src[j]
                if d == "\\":
                    j += 2
                    continue
                if d == "\n":
                    break                # a regex cannot span a line
                if d == "[":
                    in_class = True
                elif d == "]":
                    in_class = False
                elif d == "/" and not in_class:
                    closed = True
                    break
                j += 1
            if closed:
                out.append(src[i:j + 1])
                i = j + 1
                continue

        out.append(c)
        i += 1
    return "".join(out)


def strip_css_comments(src):
    """CSS with its comments removed. Strings are honoured, because a
    `content:"/*"` is content and not the start of anything."""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            body = src[i:] if j < 0 else src[i:j + 2]
            i = n if j < 0 else j + 2
            out.append("\n" if "\n" in body else "")
            continue
        if c in "\"'":
            j, closed = i + 1, False
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == c:
                    closed = True
                    break
                if src[j] == "\n":     # CSS strings never span a line
                    break
                j += 1
            if closed:
                out.append(src[i:j + 1])
                i = j + 1
                continue
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


# Only what is inside a <style> or a <script>. The HTML around them is left
# alone on purpose: "//" is two characters of every absolute URL on the
# page, and an HTML comment can be a conditional or a marker something else
# looks for.
_BLOCK = re.compile(r"(<(style|script)\b([^>]*)>)(.*?)(</\2>)", re.S | re.I)
_TYPE = re.compile(r"""\btype\s*=\s*["']?([^"'\s>]+)""", re.I)
# A <script> only holds JavaScript when it says nothing about its type or
# says one of these. Everything else in a script tag is data wearing a
# script tag: an import map, a JSON-LD block, an HTML template. None of it
# has comments, and all of it would be damaged by a pass that assumed the
# syntax of a language it is not written in.
_JS_TYPES = {"text/javascript", "application/javascript", "module",
             "text/ecmascript", "application/ecmascript"}


def strip_page(html):
    """A whole page with the comments taken out of its CSS and its script.

    Safe to run on a template that still has `{}` format fields in it: this
    only ever deletes comment text, and a field inside a comment was never
    going to be read by anybody."""
    def one(m):
        open_tag, kind, attrs, body, close = m.groups()
        if kind.lower() == "style":
            return open_tag + strip_css_comments(body) + close
        got = _TYPE.search(attrs or "")
        if got and got.group(1).lower() not in _JS_TYPES:
            return m.group(0)
        return open_tag + strip_js_comments(body) + close
    return _BLOCK.sub(one, html)
