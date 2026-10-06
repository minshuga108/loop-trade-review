"""Daily anchoring of the record's Merkle root with OpenTimestamps (OTS).

A minimal OTS client written against the public protocol (python-opentimestamps):
  1. commitment = SHA256(root || nonce16)            (the nonce keeps the root private on the calendar)
  2. POST <calendar>/digest  body = commitment (32 raw bytes)
     -> a serialized Timestamp starting at `commitment`, ending in a PendingAttestation(uri)
  3. hours later: GET <uri>/timestamp/<hex of the pending node's digest>
     -> the rest of the path, ending in a BitcoinBlockHeaderAttestation(height)

What each stage proves (be exact about it):
  * pending  : the calendar operator(s) promised to include the commitment in a Bitcoin
               transaction. Trust in the calendar only. Nothing on-chain yet.
  * bitcoin  : running the operations from the root gives a value that must equal the
               merkle root of Bitcoin block <height>. Offline we can compute that value;
               checking it against the real block header needs a header (a Bitcoin node or
               any block explorer). Once checked: the root existed before that block was mined.
Neither stage proves the decisions were GOOD, only that they existed by that time and were
not rewritten afterwards.

No network here: every call goes through a `transport(method, url, body, headers) -> (status, bytes)`
that the caller supplies (scripts/anchor_today.py uses urllib; tests use a mock).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

CALENDARS = (
    "https://alice.btc.calendar.opentimestamps.org",
    "https://bob.btc.calendar.opentimestamps.org",
    "https://finney.calendar.eternitywall.com",
)
HEADERS = {"Accept": "application/vnd.opentimestamps.v1", "User-Agent": "loop-record/1",
           "Content-Type": "application/x-www-form-urlencoded"}
OTS_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
TAG_PENDING = bytes.fromhex("83dfe30d2ef90c8e")
TAG_BITCOIN = bytes.fromhex("0588960d73d71901")
OP_SHA256, OP_SHA1, OP_RIPEMD160, OP_KECCAK = 0x08, 0x02, 0x03, 0x67
OP_APPEND, OP_PREPEND, OP_REVERSE, OP_HEXLIFY = 0xF0, 0xF1, 0xF2, 0xF3
MAX_DEPTH = 256


class AnchorError(ValueError):
    pass


# ---- varints / reader -----------------------------------------------------------------------
def write_varuint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def write_varbytes(b: bytes) -> bytes:
    return write_varuint(len(b)) + b


class _R:
    def __init__(self, data: bytes):
        self.d, self.i = data, 0

    def byte(self) -> int:
        if self.i >= len(self.d):
            raise AnchorError("truncated timestamp")
        self.i += 1
        return self.d[self.i - 1]

    def bytes(self, n: int) -> bytes:
        if self.i + n > len(self.d):
            raise AnchorError("truncated timestamp")
        self.i += n
        return self.d[self.i - n:self.i]

    def varuint(self) -> int:
        n, shift = 0, 0
        while True:
            b = self.byte()
            n |= (b & 0x7F) << shift
            if not b & 0x80:
                return n
            shift += 7
            if shift > 63:
                raise AnchorError("varuint too long")

    def varbytes(self, maxlen: int = 8192) -> bytes:
        n = self.varuint()
        if n > maxlen:
            raise AnchorError("varbytes too long")
        return self.bytes(n)


# ---- timestamp tree --------------------------------------------------------------------------
# A node is a list of items; an item is ("att", tag, payload) or ("op", opcode, arg, child_node).
def _apply(op: int, arg: bytes | None, msg: bytes) -> bytes:
    if op == OP_SHA256:
        return hashlib.sha256(msg).digest()
    if op == OP_SHA1:
        return hashlib.sha1(msg).digest()
    if op == OP_RIPEMD160:
        return hashlib.new("ripemd160", msg).digest()
    if op == OP_KECCAK:
        raise AnchorError("keccak256 is not supported by this minimal client")
    if op == OP_APPEND:
        return msg + arg
    if op == OP_PREPEND:
        return arg + msg
    if op == OP_REVERSE:
        return msg[::-1]
    if op == OP_HEXLIFY:
        return msg.hex().encode()
    raise AnchorError(f"unknown op 0x{op:02x}")


def _parse_item(r: _R, tag: int, depth: int):
    if tag == 0x00:
        atag = r.bytes(8)
        return ("att", atag, r.varbytes())
    if tag in (OP_APPEND, OP_PREPEND):
        arg = r.varbytes(4096)
        return ("op", tag, arg, parse_node(r, depth + 1))
    if tag in (OP_SHA256, OP_SHA1, OP_RIPEMD160, OP_KECCAK, OP_REVERSE, OP_HEXLIFY):
        return ("op", tag, None, parse_node(r, depth + 1))
    raise AnchorError(f"unknown tag 0x{tag:02x}")


def parse_node(r: _R, depth: int = 0) -> list:
    if depth > MAX_DEPTH:
        raise AnchorError("timestamp too deep")
    items = []
    tag = r.byte()
    while tag == 0xFF:
        items.append(_parse_item(r, r.byte(), depth))
        tag = r.byte()
    items.append(_parse_item(r, tag, depth))
    return items


def parse_timestamp(data: bytes) -> list:
    r = _R(data)
    node = parse_node(r)
    if r.i != len(data):
        raise AnchorError("trailing bytes after timestamp")
    return node


def serialize_node(node: list) -> bytes:
    out = bytearray()
    for k, it in enumerate(node):
        if k < len(node) - 1:
            out.append(0xFF)
        if it[0] == "att":
            out += b"\x00" + it[1] + write_varbytes(it[2])
        else:
            out.append(it[1])
            if it[1] in (OP_APPEND, OP_PREPEND):
                out += write_varbytes(it[2])
            out += serialize_node(it[3])
    return bytes(out)


def walk(node: list, msg: bytes, upgrades: dict[str, bytes] | None = None, out: list | None = None) -> list[dict]:
    """Execute every path; return attestations with the digest they attest to."""
    out = [] if out is None else out
    for it in node:
        if it[0] == "att":
            _, tag, payload = it
            if tag == TAG_PENDING:
                uri = _R(payload).varbytes().decode("utf-8", "replace")
                out.append({"type": "pending", "uri": uri, "digest": msg.hex()})
                up = (upgrades or {}).get(msg.hex())
                if up:
                    walk(parse_timestamp(up), msg, None, out)
            elif tag == TAG_BITCOIN:
                h = _R(payload).varuint()
                out.append({"type": "bitcoin", "height": h, "digest": msg.hex(),
                            "merkleroot_display": msg[::-1].hex()})
            else:
                out.append({"type": "unknown", "tag": tag.hex(), "digest": msg.hex()})
        else:
            _, op, arg, child = it
            walk(child, _apply(op, arg, msg), upgrades, out)
    return out


# ---- anchoring ----------------------------------------------------------------------------------
def commitment(root_hex: str, nonce: bytes) -> bytes:
    return hashlib.sha256(bytes.fromhex(root_hex) + nonce).digest()


def submit(root_hex: str, transport, calendars=CALENDARS, nonce: bytes | None = None, day: str | None = None) -> dict:
    """Send today's root to the calendars. Returns a receipt dict (JSON-safe)."""
    nonce = nonce if nonce is not None else os.urandom(16)
    c = commitment(root_hex, nonce)
    cals = []
    for url in calendars:
        try:
            status, body = transport("POST", url.rstrip("/") + "/digest", c, HEADERS)
            if status != 200:
                raise AnchorError(f"HTTP {status}")
            parse_timestamp(body)                     # refuse junk before storing it
            cals.append({"url": url, "ok": True, "response_hex": body.hex()})
        except Exception as e:                        # one calendar down must not stop the others
            cals.append({"url": url, "ok": False, "error": f"{type(e).__name__}: {e}"[:200]})
    return {"version": 1, "method": "opentimestamps", "day": day, "root": root_hex, "nonce_hex": nonce.hex(),
            "commitment_hex": c.hex(), "submitted_ms": int(time.time() * 1000), "calendars": cals, "upgrades": {}}


def upgrade(receipt: dict, transport) -> dict:
    """Ask each pending calendar for the finished path; store whatever is ready."""
    for a in verify_anchor(receipt["root"], receipt)["attestations"]:
        if a["type"] != "pending" or a["digest"] in receipt["upgrades"]:
            continue
        try:
            status, body = transport("GET", a["uri"].rstrip("/") + "/timestamp/" + a["digest"], None, HEADERS)
            if status == 200:
                parse_timestamp(body)
                receipt["upgrades"][a["digest"]] = body.hex()
        except Exception:
            pass
    return receipt


def verify_anchor(root_hex: str, receipt: dict) -> dict:
    """Offline check that the receipt commits to `root_hex` and what it attests.

    Returns {"ok", "reason", "attestations", "bitcoin", "pending", "proves"}. A Bitcoin
    attestation gives a block height and the merkle root that block must have; confirming
    that value against a real block header is a separate (online or node) step.
    """
    fail = lambda why: {"ok": False, "reason": why, "attestations": [], "bitcoin": [], "pending": [], "proves": "nothing"}
    if receipt.get("root") != root_hex:
        return fail("receipt is for a different root")
    try:
        c = commitment(root_hex, bytes.fromhex(receipt["nonce_hex"]))
    except (KeyError, ValueError):
        return fail("receipt has no valid nonce")
    if c.hex() != receipt.get("commitment_hex"):
        return fail("commitment does not equal SHA256(root || nonce)")
    ups = {k: bytes.fromhex(v) for k, v in receipt.get("upgrades", {}).items()}
    atts: list[dict] = []
    for cal in receipt.get("calendars", []):
        if not cal.get("ok"):
            continue
        try:
            atts += walk(parse_timestamp(bytes.fromhex(cal["response_hex"])), c, ups)
        except AnchorError as e:
            return fail(f"calendar response from {cal['url']} does not parse: {e}")
    btc, seen = [], set()
    for a in atts:                                   # two calendars may share one upgraded path
        if a["type"] == "bitcoin" and (a["height"], a["digest"]) not in seen:
            seen.add((a["height"], a["digest"]))
            btc.append(a)
    pend = [a for a in atts if a["type"] == "pending"]
    if not atts:
        return fail("no calendar accepted the root")
    proves = ("The root is committed to Bitcoin block(s) " + ", ".join(str(b["height"]) for b in btc) +
              " once the listed merkle root matches that block header.") if btc else \
        f"{len(pend)} calendar(s) promised to timestamp the root; not yet on Bitcoin."
    return {"ok": True, "reason": "receipt commits to this root", "attestations": atts, "bitcoin": btc, "pending": pend, "proves": proves}


def check_bitcoin_header(att: dict, transport, explorer: str = "https://blockstream.info/api") -> dict:
    """Online step (script only): compare the attested value with the real block's merkle root."""
    st, h = transport("GET", f"{explorer}/block-height/{att['height']}", None, {})
    if st != 200:
        return {"ok": False, "reason": f"explorer HTTP {st}"}
    st, blk = transport("GET", f"{explorer}/block/{h.decode().strip()}", None, {})
    if st != 200:
        return {"ok": False, "reason": f"explorer HTTP {st}"}
    mr = json.loads(blk)["merkle_root"]
    return {"ok": mr == att["merkleroot_display"], "height": att["height"], "block_merkle_root": mr,
            "block_time": json.loads(blk).get("timestamp")}


def to_ots_file(receipt: dict) -> bytes:
    """A standard detached .ots proof for the root (verify with: ots verify -d <root> file.ots)."""
    subs = []
    for cal in receipt["calendars"]:
        if cal.get("ok"):
            subs += parse_timestamp(bytes.fromhex(cal["response_hex"]))
    if not subs:
        raise AnchorError("nothing to write: no calendar accepted the root")
    tree = [("op", OP_APPEND, bytes.fromhex(receipt["nonce_hex"]), [("op", OP_SHA256, None, subs)])]
    return OTS_MAGIC + write_varuint(1) + bytes([OP_SHA256]) + bytes.fromhex(receipt["root"]) + serialize_node(tree)


def anchors_dir() -> Path:
    env = os.environ.get("LOOP_ANCHOR_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[1] / "data" / "anchors"


def save_receipt(receipt: dict, folder: Path | None = None) -> Path:
    folder = folder or anchors_dir()
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{receipt['day']}.json"
    p.write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    try:
        (folder / f"{receipt['day']}.ots").write_bytes(to_ots_file(receipt))
    except AnchorError:
        pass
    return p


def latest_receipt(folder: Path | None = None) -> dict | None:
    folder = folder or anchors_dir()
    files = sorted(folder.glob("????-??-??.json")) if folder.exists() else []
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None
