#!/usr/bin/env python3
"""
skymap.sh's Bluesky bot: reply to any post that mentions the bot's handle
with a night-sky image for whatever place is left in the text.

    @skymap.bsky.social Tokyo   -> replies with Tokyo's current sky
    @skymap.bsky.social         -> replies with a usage hint

Long-lived polling loop. Reuses api.py/gif.py directly -- the same engine
cli.py and server.py already share -- so a mention never makes an HTTP round
trip through skymap.sh's own rate limiter.

Env vars (set on the server, never committed):
    BSKY_HANDLE          bot's Bluesky handle, e.g. skymap.bsky.social
    BSKY_APP_PASSWORD    an app password from Bluesky settings -- not the
                          account password
    BSKY_POLL_SECONDS    how often to check for new mentions (default 30)
    BSKY_STATE_FILE       where to persist the last-seen timestamp
                          (default bsky_bot_state.json, next to this file)

Run:  python3 bsky_bot.py
"""
import datetime as dt
import json
import logging
import os
import sys
import time
from pathlib import Path

from atproto import Client, models

import api
import gif
import tle

HANDLE = os.environ.get("BSKY_HANDLE")
APP_PASSWORD = os.environ.get("BSKY_APP_PASSWORD")
POLL_SECONDS = int(os.environ.get("BSKY_POLL_SECONDS", "30"))
STATE_FILE = Path(os.environ.get("BSKY_STATE_FILE") or Path(__file__).parent / "bsky_bot_state.json")
EPOCH = "1970-01-01T00:00:00.000Z"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bsky_bot")


def extract_place(text, facets):
    """Strip every @mention out of a post's text, byte-range accurate (a
    display name can contain the substring "@handle" without being a real
    mention facet), and return whatever's left as the place query. Empty
    string if nothing's left -- that's a bare mention, not a query."""
    if not facets:
        return text.strip()
    mention_ranges = sorted(
        (f.index.byte_start, f.index.byte_end)
        for f in facets
        if any(isinstance(feat, models.AppBskyRichtextFacet.Mention) for feat in f.features)
    )
    raw = text.encode("utf-8")
    out, cursor = b"", 0
    for start, end in mention_ranges:
        out += raw[cursor:start]
        cursor = end
    out += raw[cursor:]
    return out.decode("utf-8").strip(" :,")


def sky_png(place_query):
    """(png_bytes, resolved_name), or (None, None) if the query doesn't
    resolve to anywhere skymap.sh knows."""
    if api.lookup_place(place_query) is None:
        return None, None
    r = api.Request(place=place_query, tle=tle.current() or f"{api.sky.BASE}/demo.tle")
    art = api.compose_chart_only(r)
    return gif.frame_to_png(art), r.place.name


def load_last_seen():
    try:
        return json.loads(STATE_FILE.read_text())["last_seen"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return EPOCH


def save_last_seen(when):
    STATE_FILE.write_text(json.dumps({"last_seen": when}))


def reply_to(client, notif, text, png=None, alt=None):
    parent_ref = models.create_strong_ref(notif)
    root_ref = models.create_strong_ref(notif.record.reply.root) if notif.record.reply else parent_ref
    embed = None
    if png:
        blob = client.upload_blob(png).blob
        embed = models.AppBskyEmbedImages.Main(images=[models.AppBskyEmbedImages.Image(alt=alt or "", image=blob)])
    client.send_post(
        text=text,
        reply_to=models.AppBskyFeedPost.ReplyRef(root=root_ref, parent=parent_ref),
        embed=embed,
    )


def handle_mention(client, notif):
    place_query = extract_place(notif.record.text, notif.record.facets)
    if not place_query:
        reply_to(client, notif, f'Tell me a place: "@{HANDLE} Tokyo"')
        return
    png, name = sky_png(place_query)
    if png is None:
        reply_to(client, notif, f'Don\'t know "{place_query}". Try a city name or lat,lon.')
        return
    reply_to(client, notif, f"The sky above {name} right now.", png=png, alt=f"Star chart for {name}")


def poll_once(client, last_seen):
    resp = client.app.bsky.notification.list_notifications()
    mentions = sorted(
        (n for n in resp.notifications if n.reason == "mention" and n.indexed_at > last_seen),
        key=lambda n: n.indexed_at,
    )
    newest = last_seen
    for notif in mentions:
        try:
            handle_mention(client, notif)
        except Exception:
            log.exception("failed to handle mention %s", notif.uri)
        newest = max(newest, notif.indexed_at)
    if mentions:
        client.app.bsky.notification.update_seen({"seen_at": dt.datetime.now(dt.timezone.utc).isoformat()})
    return newest


def main():
    if not HANDLE or not APP_PASSWORD:
        sys.exit("Set BSKY_HANDLE and BSKY_APP_PASSWORD")
    client = Client()
    client.login(HANDLE, APP_PASSWORD)
    log.info("logged in as %s, polling every %ss", HANDLE, POLL_SECONDS)
    last_seen = load_last_seen()
    while True:
        try:
            last_seen = poll_once(client, last_seen)
            save_last_seen(last_seen)
        except Exception:
            log.exception("poll failed")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
