"""شريط "عدد الشعب لكل صف" — SectionsEditor equivalent."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from ..state.store import get_store

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/sections", tags=["sections"])


@router.post("/{grade}", response_class=HTMLResponse)
def update(grade: str, request: Request, count: int = Form(..., ge=0, le=99)) -> HTMLResponse:
    store = get_store()
    if store.data is None:
        raise HTTPException(400, "لا يوجد ملف محمَّل")
    if grade not in store.data.get("sections", {}):
        raise HTTPException(404, f"صف غير معروف: {grade}")
    store.data["sections"][grade] = count
    store.mark_dirty()
    store.log(f"عدد شعب {grade} أصبح {count}")
    return HTMLResponse(f'<span class="ok-mark">✓</span>')
