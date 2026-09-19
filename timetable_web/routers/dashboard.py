"""تبويب "لوحة المعلومات" — KPIs + مقياس السعة + تنبيهات ما قبل التوليد."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..core import scheduler
from ..state.store import get_store

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _compute(data: dict) -> dict:
    days = data["meta"]["days"]
    ppd = data["meta"]["periods_per_day"]
    nslots = len(days) * ppd
    sections = data.get("sections", {})
    total_sections = sum(sections.values())
    subjects = data.get("subjects", [])
    teachers_roster = data.get("teachers", [])

    # capacity
    total_slots = total_sections * nslots
    needed = 0
    for subj in subjects:
        needed += scheduler.subject_required_periods(data, subj)

    capacity_pct = int(100 * needed / total_slots) if total_slots else 0

    # warnings
    warnings: list[str] = []

    # 1. subjects without teachers
    for s in subjects:
        if not s.get("names"):
            warnings.append(f"مادة «{s['name']}» بلا أساتذة — سيولّد البرنامج أساتذة افتراضيين لها عند التوليد.")

    # 2. incomplete grades (informational)
    for g, gap in scheduler.incomplete_grades(data):
        label = data["meta"].get("grade_labels", {}).get(g, g)
        warnings.append(f"صف {label}: مجموع حصصه ينقص {gap} حصة عن السعة الأسبوعية الكاملة (سيولَّد جدول بها فراغات).")

    # 3. teachers exceeding capacity
    for name in teachers_roster:
        needed_t = scheduler.teacher_current_periods(data, name)
        cap = scheduler.teacher_capacity(data, name)
        if needed_t > cap:
            warnings.append(f"الأستاذ {name} يحتاج {needed_t} حصة لكن السعة القصوى {cap} — التوليد سيفشل.")

    # 4. constraint validation
    try:
        scheduler.validate_teacher_constraints(data)
    except Exception as exc:
        warnings.append(f"قيد أستاذ غير صالح: {exc}")
    try:
        scheduler.validate_manual_assignments(data)
    except Exception as exc:
        warnings.append(f"إسناد إجباري غير صالح: {exc}")

    # roster stats
    _, multi, unique_count = scheduler.teacher_roster(data)

    return {
        "kpi_subjects": len(subjects),
        "kpi_sections": total_sections,
        "kpi_teachers": unique_count,
        "kpi_multi": len(multi),
        "capacity_needed": needed,
        "capacity_total": total_slots,
        "capacity_pct": capacity_pct,
        "capacity_bar_pct": min(capacity_pct, 100),  # clamp for display
        "warnings": warnings,
        "days": days,
        "periods_per_day": ppd,
        "nslots": nslots,
        "multi_teachers": sorted(multi.keys()),
    }


@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    store = get_store()
    if store.data is None:
        raise HTTPException(400, "لا يوجد ملف محمَّل")
    return TEMPLATES.TemplateResponse(
        request,
        "dashboard.html",
        {"store": store, "data": store.data, **_compute(store.data)},
    )
