"""Per-trade detail page: /trade/<trader>/<index>. UI over the existing /api/trip/{tid}/{index} endpoint; no new numbers."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
STATIC = Path(__file__).parent / "static"


@router.get("/trade/{tid}/{index}", include_in_schema=False)
def trade_page(tid: str, index: int):
    from . import service
    try:
        service._load(tid)
    except StopIteration:
        raise HTTPException(404, "unknown trader")
    if index < 0:
        raise HTTPException(404, "no trip with that index")
    return FileResponse(STATIC / "trade.html")
