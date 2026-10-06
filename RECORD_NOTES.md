# Public forward record (R21, M5, R7)

## What it is
- `engine/record.py`: append-only JSONL log, one canonical JSON line per entry:
  `{"hash","kind","payload","prev_hash","seq","ts_ms"}` (keys sorted, no spaces, UTF-8).
  `hash = SHA256(canonical(entry without "hash"))`; `prev_hash` of seq 1 is 64 zeros.
  Because `"hash"` sorts first, the hashed body is the stored line minus its `"hash":"<64>",` prefix,
  so the browser re-hashes the raw bytes (no float re-serialisation risk).
- Kinds: `gate_decision` (provenance forced to `SIM_PAPER`), `rule_event`, `outcome`.
- Outcomes: must reference an earlier `gate_decision` seq, at most one per decision, never dated before it.
  The decision line is never touched. `verify_file` also rejects a forged log where an outcome precedes its decision.
- Sessions: stored only as `HMAC-SHA256(salt, sid)` (20 hex chars). Salt from `LOOP_RECORD_SALT` or a
  random `record.jsonl.salt` next to the log (gitignored). Keep the salt secret.
- `verify_file(path)` -> intact/broken, first bad seq, reason (edited, relinked, deleted/reordered line,
  non-canonical line, time went backwards, bad outcome reference).
- Day root: RFC 6962-style Merkle tree over the day's entry hashes (UTC day; leaf `0x00||h`, node
  `0x01||l||r`, odd node promoted, empty day = SHA256("")). `merkle_proof` / `verify_merkle_proof` prove one entry is in an anchored root.
- Counter: days running (first entry's UTC day to today, inclusive), decisions, rule events, outcomes resolved, pending.

## Anchoring (`engine/anchor.py`, `scripts/anchor_today.py`)
- A minimal OpenTimestamps client written to the public protocol: `commitment = SHA256(root || 16-byte nonce)`,
  POST to alice/bob (opentimestamps.org) and finney (eternitywall), store each calendar's binary reply,
  later `GET <calendar>/timestamp/<digest>` to fetch the Bitcoin path (`--upgrade-all`).
- Writes `data/anchors/<day>.json` (receipt) and `<day>.ots`, a standard detached proof. The official
  `opentimestamps` Python library parsed our first real `.ots` (2026-10-05, 3 of 3 calendars accepted), so
  `ots verify -d <root> <day>.ots` should work with the stock client.
- `verify_anchor(root, receipt)` runs offline: checks the nonce commitment, replays every operation, and
  lists pending and Bitcoin attestations. `check_bitcoin_header` (script only) compares the attested value
  with the block's merkle root from blockstream.info.
- No network in engine or tests: all HTTP goes through a `transport` callable; tests use a mock calendar.

### What each anchor proves (say exactly this, no more)
- Pending: three calendar operators received the commitment and promised to put it into Bitcoin. Trust in them only.
- Bitcoin attestation that matches the block header: the day's root existed before that block was mined, so
  no entry of that day can have been added, removed or edited after that time without the root changing.
- It does NOT prove the decisions were good, that the log holds every decision ever made (an operator could
  skip logging), or anything about entries after the last anchored day.

## Limitations (honest)
- Single process only: appends are guarded by a thread lock, not a cross-process file lock. Two app workers
  writing the same file could interleave; run one worker or move to a DB with a unique seq.
- The operator can still delete the whole file, or rewrite everything after the last anchor. Defence: anchor
  daily and keep the receipts somewhere public (commit `<day>.json`/`.ots` to a public repo or gist). No
  second independent witness is wired yet; OpenTimestamps worked on the first run so the fallback was not built.
- A day anchored more than once keeps the older receipt as `<day>.<root8>.json` and anchors the new root; the
  counter page flags when the latest receipt's root no longer matches the log for that day.
- Serverless disks are ephemeral: on Vercel-style hosting the log must live on a persistent volume or store.
- Outcome resolver not built: nothing yet writes `outcome` entries automatically (e.g. price after 24h). Until it
  exists every decision stays "pending", and the counter says so.
- Wiring (owner): `app.include_router(record_api.router)` in `app/main.py`; call
  `record_api.log_gate_decision(sid, tid, out)` at the end of `service.gate_check`, and
  `record_api.log_rule_event(sid, tid, rb.log[-1])` after `propose_rule` / `transition`. Both hooks swallow errors.
- `ts_ms` is the server clock; the record says when the server claims it wrote a line, bounded only by the anchors.
- Keccak256 OTS operations are not supported (public calendars do not use them today).
