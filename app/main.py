"""FastAPI app: serves the first screen and the review JSON. No login, no keys, read-only."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from engine import report as report_mod

from . import chat as chat_mod
from engine import bitget_context
from . import judge, mcp_server
from . import record_api
from . import costs
from . import service
from .ratelimit import RateLimitMiddleware
from .security import SecurityHeadersMiddleware

SafeJSONResponse = service.SafeJSONResponse
JSONResponse = SafeJSONResponse                  # the handlers below use the safe class too
app = FastAPI(title="Loop review engine", docs_url=None, redoc_url=None, default_response_class=SafeJSONResponse)
STATIC = Path(__file__).parent / "static"
app.add_middleware(RateLimitMiddleware)          # 429 with Retry-After, 413 over 64 KB, 400 on a malformed X-Session
app.add_middleware(SecurityHeadersMiddleware)    # outermost: every answer, 429s included, carries the headers


@app.exception_handler(service.DataMissing)
async def _data_missing(request: Request, exc: service.DataMissing):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    """422 without echoing the input back: an inf/NaN or undecodable body used to turn this into a 500."""
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": [str(x) for x in e.get("loc", ())], "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
        for e in exc.errors()]})


@app.on_event("startup")
def _startup():
    costs.start_refresher()      # background book refresh; requests only ever read the cache
    bitget_context.start_refresher()   # background Bitget tool calls for the 'context, not evidence' line
    service.warm()               # compute every demo trader's review once, in the background

app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(record_api.router)
app.include_router(judge.router)
from .evidence_api import router as evidence_router  # noqa: E402
app.include_router(evidence_router)
app.include_router(mcp_server.router)
from .status_api import router as status_router; app.include_router(status_router)  # noqa: E402,E702
from .trade_page import router as trade_router; app.include_router(trade_router)  # noqa: E402,E702
from .cards_api import router as cards_router; app.include_router(cards_router)  # noqa: E402,E702  (before /api/report/{tid})


from . import home_api  # noqa: E402
app.include_router(home_api.router)
from . import thesis_api  # noqa: E402
app.include_router(thesis_api.router)
from . import validation_note  # noqa: E402
app.include_router(validation_note.router())
from . import whitepaper  # noqa: E402
app.include_router(whitepaper.router())
from . import runs_api  # noqa: E402
app.include_router(runs_api.router)


@app.get("/")
def index():
    return home_api.index_response()      # index.html plus the server-rendered verdict banner and fills tile


@app.get("/video")
def video_page():
    return FileResponse(STATIC / "video.html")


MEDIA = Path(__file__).resolve().parent.parent / "deploy_data" / "media"
_MEDIA_TYPES = {".webm": "video/webm", ".mp4": "video/mp4"}


@app.get("/media/{name}")
def media(name: str, request: Request):
    """Read-only media (flat directory, allow-listed extensions, Range requests so the video seeks)."""
    ext = Path(name).suffix.lower()
    p = (MEDIA / name)
    if (name != Path(name).name or name.startswith(".") or ext not in _MEDIA_TYPES or not p.is_file()
            or p.resolve().parent != MEDIA.resolve()):
        raise HTTPException(404, "not found")
    size = p.stat().st_size
    ctype = _MEDIA_TYPES[ext]
    start, end, status = 0, size - 1, 200
    rng = request.headers.get("range")
    if rng:
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
        if not m or not (m.group(1) or m.group(2)):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        else:                                            # suffix range: the last N bytes
            start = max(size - int(m.group(2)), 0)
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status = 206
    length = end - start + 1
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(length), "Cache-Control": "public, max-age=3600"}
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    def chunks():
        left = length
        with p.open("rb") as f:
            f.seek(start)
            while left > 0:
                b = f.read(min(1 << 16, left))
                if not b:
                    break
                left -= len(b)
                yield b
    return StreamingResponse(chunks(), status_code=status, media_type=ctype, headers=headers)


@app.get("/api/traders")
def traders(x_session: str = Header(default="default")):
    return service.traders(x_session)


@app.get("/api/review/{tid}")
def review(tid: str):
    try:
        rv = service.review(tid)
    except StopIteration:
        raise HTTPException(404, "unknown trader")
    note = validation_note.note_for(tid, rv["headline"]["priced"].get("all_history_effect"))
    return {**rv, "validation_note": note} if note else rv


@app.get("/api/toggle/{tid}")
def toggle(tid: str, rule: str = Query("halt", pattern="^(halt|cap)$"), n_losses: int = Query(2, ge=1, le=5)):
    try:
        return service.toggle(tid, rule, n_losses)
    except StopIteration:
        raise HTTPException(404, "unknown trader")


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "read-only", "writes": False}


class ChatIn(BaseModel):
    trader: str
    message: str
    history: list[dict] = Field(default_factory=list, max_length=50)     # only the last intent is read


@app.post("/api/chat")
def chat(body: ChatIn, x_session: str = Header(default="default")):
    if len(body.message) > 500:
        raise HTTPException(400, "message too long")
    try:
        return chat_mod.answer(body.trader, body.message, body.history, x_session)
    except StopIteration:
        raise HTTPException(404, "unknown trader")


@app.get("/api/report/{tid}")
def report(tid: str, lang: str = Query("en", pattern="^(en|zh)$"), save: bool = False):
    try:
        rv = service.review(tid)
    except StopIteration:
        raise HTTPException(404, "unknown trader")
    prev = report_mod.previous_snapshot(tid)
    out = report_mod.build(rv, prev, lang)
    if save:
        report_mod.save_snapshot(tid, out["facts"])
    return out


class ProposeIn(BaseModel):
    multiple: float


class RuleRef(BaseModel):
    rule_id: str


class GateIn(BaseModel):
    text: str
    after_loss: bool | None = None
    scenario: list[str] | None = Field(default=None, max_length=4)


@app.get("/api/rulebook/{tid}")
def rulebook(tid: str, x_session: str = Header(default="default")):
    try:
        return service.rulebook_view(x_session, tid)
    except StopIteration:
        raise HTTPException(404, "unknown trader")


@app.get("/api/rulebook/{tid}/walkforward")
def rb_walkforward(tid: str, multiple: float = 1.5, x_session: str = Header(default="default")):
    if not (0.5 <= multiple <= 10):
        raise HTTPException(400, "multiple must be between 0.5 and 10")
    try:
        return service.walkforward_view(x_session, tid, multiple)
    except StopIteration:
        raise HTTPException(404, "unknown trader")


@app.get("/api/cohort_card")
def cohort_card():
    from . import cohort_card as cc
    d = cc.facts()
    if d is None:
        raise HTTPException(404, "cohort results not available")
    return d


@app.post("/api/rulebook/{tid}/propose")
def rb_propose(tid: str, body: ProposeIn, x_session: str = Header(default="default")):
    if not (0.5 <= body.multiple <= 10):
        raise HTTPException(400, "multiple must be between 0.5 and 10")
    try:
        return service.propose_rule(x_session, tid, body.multiple)
    except StopIteration:
        raise HTTPException(404, "unknown trader")


@app.post("/api/rulebook/{tid}/{action}")
def rb_action(tid: str, action: str, body: RuleRef, x_session: str = Header(default="default")):
    if action not in ("arm", "retire_propose", "retire_confirm", "keep", "revert"):
        raise HTTPException(404, "unknown action")
    try:
        return service.transition(x_session, tid, action, body.rule_id)
    except StopIteration:
        raise HTTPException(404, "unknown trader")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/gate/{tid}")
def gate(tid: str, body: GateIn, x_session: str = Header(default="default")):
    if len(body.text) > 300:
        raise HTTPException(400, "text too long")
    try:
        return service.gate_check(x_session, tid, body.text, body.after_loss, **({"scenario": body.scenario} if body.scenario else {}))
    except StopIteration:
        raise HTTPException(404, "unknown trader")


@app.get("/api/cost")
def cost(symbol: str, size: float = Query(5000, ge=10, le=10_000_000), side: str = Query("buy", pattern="^(buy|sell)$")):
    return costs.cost_line(symbol, size, side)


class ImportIn(BaseModel):
    text: str


@app.post("/api/import")
def import_history(body: ImportIn, x_session: str = Header(default="default")):
    from . import importer
    try:
        fills, note = importer.parse(body.text, x_session)
        out = service.register_import(x_session, fills, note)
    except importer.ImportRefused as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(422, f"{e}. Nothing was stored.")
    return out


@app.get("/verify", include_in_schema=False)
def verify_page():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/record")
