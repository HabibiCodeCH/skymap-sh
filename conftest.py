"""Keep the suite off the two files server.py persists next to itself.

Every TestClient context manager is a startup and a shutdown, and shutdown
writes: the cumulative counters to stats_state.json, and -- since the hour in
progress started being flushed there too -- a row of whatever the suite just
tallied to stats_hourly.jsonl. Running pytest in a checkout would overwrite
the developer's saved counters and add fake traffic to their charts.

Redirected at collection time, before any test module imports server, so
there is no window where a test could touch the real ones.
"""
import os
import tempfile

import server

_TMP = tempfile.mkdtemp(prefix="skymap-tests-")
server.STATS_STATE_FILE = os.path.join(_TMP, "stats_state.json")
server.HOURLY_LOG = os.path.join(_TMP, "stats_hourly.jsonl")
