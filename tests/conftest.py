import os

os.environ.setdefault("LOOP_NO_REFRESH", "1")      # tests never start the live book refresher or touch the network

os.environ.setdefault("LOOP_RATELIMIT", "off")     # the suite fires hundreds of requests from one client; test_http turns it on

import tempfile

os.environ.setdefault("LOOP_RECORD_PATH", os.path.join(tempfile.mkdtemp(prefix="loop-record-"), "record.jsonl"))   # tests never touch the real log
