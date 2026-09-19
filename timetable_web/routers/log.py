"""تبويب "سجل العمليات" — مسار مستقل لعرض السجل بحجم أكبر."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..state.store import get_store

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/log", tags=["log"])


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request, "log.html", {"store": get_store()}
    )


@router.get("/tail", response_class=HTMLResponse)
def tail(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request, "partials/log_tail.html", {"store": get_store()}
    )
