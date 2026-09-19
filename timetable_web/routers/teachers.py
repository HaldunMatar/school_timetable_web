"""تبويب "قائمة الأساتذة" — القائمة المركزية الوحيدة لكل الأساتذة.

نظير TeacherRosterTab في gui.py — كل CRUD مركزي يتم من هنا.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..core import scheduler
from ..state.store import get_store

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/teachers", tags=["teachers"])


def _ctx(request: Request):
    store = get_store()
    if store.data is None:
        raise HTTPException(400, "لم يُحمَّل أي ملف بيانات بعد")
    # Aggregate central roster: one row per teacher name.
    rows = []
    for name in store.data.get("teachers", []):
        subjects = [s["name"] for s in store.data.get("subjects", []) if name in s.get("names", [])]
        rows.append({
            "name": name,
            "weekly_periods": scheduler.teacher_current_periods(store.data, name),
            "subjects": subjects,
        })
    rows.sort(key=lambda r: r["name"])
    total_weekly = sum(r["weekly_periods"] for r in rows)
    return {
        "request": request,
        "store": store,
        "data": store.data,
        "roster": rows,
        "total_weekly": total_weekly,
    }


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "teachers.html", _ctx(request))


@router.get("/rows", response_class=HTMLResponse)
def rows(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "partials/teacher_rows.html", _ctx(request))


@router.post("/add", response_class=HTMLResponse)
def add(request: Request, name: str = Form(...)) -> HTMLResponse:
    store = get_store()
    name = name.strip()
    if not name:
        raise HTTPException(400, "الاسم مطلوب")
    try:
        scheduler.add_teacher_to_roster(store.data, name)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    store.mark_dirty()
    store.log(f"تمت إضافة الأستاذ: {name}")
    return TEMPLATES.TemplateResponse(request, "partials/teacher_rows.html", _ctx(request))


@router.post("/rename", response_class=HTMLResponse)
def rename(request: Request, old_name: str = Form(...), new_name: str = Form(...)) -> HTMLResponse:
    store = get_store()
    old_name = old_name.strip()
    new_name = new_name.strip()
    if not new_name:
        raise HTTPException(400, "الاسم الجديد مطلوب")
    try:
        scheduler.rename_teacher_in_roster(store.data, old_name, new_name)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    store.mark_dirty()
    store.log(f"تمت إعادة تسمية: {old_name} ← {new_name}")
    return TEMPLATES.TemplateResponse(request, "partials/teacher_rows.html", _ctx(request))


@router.post("/delete", response_class=HTMLResponse)
def delete(request: Request, name: str = Form(...)) -> HTMLResponse:
    store = get_store()
    try:
        scheduler.remove_teacher_from_roster(store.data, name)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc))
    store.mark_dirty()
    store.log(f"تم حذف الأستاذ: {name}")
    return TEMPLATES.TemplateResponse(request, "partials/teacher_rows.html", _ctx(request))
