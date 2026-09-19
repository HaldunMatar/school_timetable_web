"""تبويب "قيود الجدولة" — ConstraintsTab + ConstraintGroupFrame equivalents.

- Defaults: scheduling_constraints.defaults[key]
- Per-teacher override: scheduling_constraints.per_teacher[name][key]
"""

from __future__ import annotations

import copy
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..core import scheduler
from ..state.store import get_store

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/constraints", tags=["constraints"])

CONSTRAINT_KEYS = ["empty_periods", "day_off", "max_gap_windows", "start_from_beginning"]
CONSTRAINT_TITLES = scheduler.CONSTRAINT_TITLES  # {"empty_periods": "...", ...}


def _data():
    store = get_store()
    if store.data is None:
        raise HTTPException(400, "لا يوجد ملف محمَّل")
    return store, store.data


def _defaults_group(data: dict, key: str) -> dict:
    return data["scheduling_constraints"]["defaults"][key]


def _teacher_override(data: dict, name: str, key: str) -> dict | None:
    return data["scheduling_constraints"]["per_teacher"].get(name, {}).get(key)


def _has_override(data: dict, name: str, key: str) -> bool:
    return _teacher_override(data, name, key) is not None


def _effective_group(data: dict, name: str | None, key: str) -> dict:
    if name is None:
        return _defaults_group(data, key)
    override = _teacher_override(data, name, key)
    return override if override is not None else _defaults_group(data, key)


def _ctx_page(request: Request, selected_teacher: str | None = None) -> dict:
    store, data = _data()
    scheduler.ensure_teacher_roster(data)
    teachers = sorted(data.get("teachers", []))
    days = data["meta"]["days"]
    return {
        "request": request,
        "store": store,
        "data": data,
        "teachers": teachers,
        "days": days,
        "selected_teacher": selected_teacher,
        "constraint_keys": CONSTRAINT_KEYS,
        "constraint_titles": CONSTRAINT_TITLES,
    }


def _ctx_group(data: dict, key: str, scope: str, teacher: str | None) -> dict:
    """Context for a single constraint card partial (used by both panes)."""
    days = data["meta"]["days"]
    if scope == "defaults":
        group = _defaults_group(data, key)
        has_override = False
        effective = group
    else:
        override = _teacher_override(data, teacher, key) if teacher else None
        has_override = override is not None
        effective = override if has_override else _defaults_group(data, key)
        group = effective
    return {
        "key": key,
        "title": CONSTRAINT_TITLES[key],
        "group": group,
        "scope": scope,           # "defaults" or "teacher"
        "teacher": teacher,
        "days": days,
        "has_override": has_override,
    }


def _teacher_info(data: dict, name: str) -> dict:
    """Return effective constraints + workload snapshot for the selected teacher."""
    periods = scheduler.teacher_current_periods(data, name)
    subjects = []
    for s in data.get("subjects", []):
        if name in s.get("names", []):
            subjects.append(s["name"])
    return {"weekly_periods": periods, "subjects": subjects}


# --------------------------------------------------- pages -------------

@router.get("", response_class=HTMLResponse)
def index(request: Request, teacher: str | None = Query(None)) -> HTMLResponse:
    ctx = _ctx_page(request, selected_teacher=teacher)
    _, data = _data()
    if teacher:
        ctx["teacher_info"] = _teacher_info(data, teacher)
    return TEMPLATES.TemplateResponse(request, "constraints.html", ctx)


@router.get("/teacher/{name}/panel", response_class=HTMLResponse)
def teacher_panel(name: str, request: Request) -> HTMLResponse:
    _, data = _data()
    if name not in data.get("teachers", []):
        raise HTTPException(404, "أستاذ غير معروف")
    ctx = _ctx_page(request, selected_teacher=name)
    ctx["teacher_info"] = _teacher_info(data, name)
    return TEMPLATES.TemplateResponse(request, "partials/constraints_teacher_pane.html", ctx)


# --------------------------------------------------- mutations ---------

def _parse_group_from_form(key: str, form: dict, days: list[str]) -> dict:
    """Reconstruct a constraint group from the flat form fields."""
    def _b(name: str) -> bool:
        return form.get(name) == "on"

    def _int(name: str, default: int) -> int:
        raw = form.get(name)
        try:
            return int(raw) if raw not in (None, "") else default
        except ValueError:
            return default

    if key == "empty_periods":
        return {
            "enabled": _b("enabled"),
            "start": {"enabled": _b("start_enabled"), "count": _int("start_count", 1)},
            "end":   {"enabled": _b("end_enabled"),   "count": _int("end_count", 1)},
            "days_mode": form.get("days_mode", "all") if form.get("days_mode") in ("all", "specific") else "all",
            "days": [d for d in days if form.get(f"day_{d}") == "on"],
        }
    if key == "day_off":
        return {
            "enabled": _b("enabled"),
            "mode": form.get("mode", "specific") if form.get("mode") in ("specific", "random") else "specific",
            "days": [d for d in days if form.get(f"day_{d}") == "on"],
            "count": _int("count", 1),
        }
    if key == "max_gap_windows":
        return {"enabled": _b("enabled"), "max": _int("max", 1)}
    if key == "start_from_beginning":
        return {"enabled": _b("enabled")}
    raise HTTPException(400, f"مفتاح قيد غير معروف: {key}")


def _write_group(data: dict, key: str, scope: str, teacher: str | None, group: dict) -> None:
    sc = data["scheduling_constraints"]
    if scope == "defaults":
        sc["defaults"][key] = group
    else:
        assert teacher is not None
        sc["per_teacher"].setdefault(teacher, {})[key] = group


@router.post("/defaults/{key}", response_class=HTMLResponse)
async def update_default(key: str, request: Request) -> HTMLResponse:
    store, data = _data()
    if key not in CONSTRAINT_KEYS:
        raise HTTPException(400, "مفتاح قيد غير معروف")
    form = dict(await request.form())
    group = _parse_group_from_form(key, form, data["meta"]["days"])
    _write_group(data, key, "defaults", None, group)
    store.mark_dirty()
    store.log(f"قيد افتراضي محدَّث: {CONSTRAINT_TITLES[key]}")
    return TEMPLATES.TemplateResponse(
        request, "partials/constraint_group.html",
        _ctx_group(data, key, "defaults", None) | {"request": request},
    )


@router.post("/teacher/{name}/{key}/override", response_class=HTMLResponse)
def toggle_override(name: str, key: str, request: Request, on: str = Form("")) -> HTMLResponse:
    store, data = _data()
    if key not in CONSTRAINT_KEYS:
        raise HTTPException(400, "مفتاح قيد غير معروف")
    per = data["scheduling_constraints"]["per_teacher"]
    if on == "on":
        per.setdefault(name, {})[key] = copy.deepcopy(_defaults_group(data, key))
        store.log(f"تخصيص قيد {CONSTRAINT_TITLES[key]} للأستاذ {name}")
    else:
        if name in per and key in per[name]:
            per[name].pop(key)
            if not per[name]:
                per.pop(name)
        store.log(f"إزالة تخصيص قيد {CONSTRAINT_TITLES[key]} من الأستاذ {name}")
    store.mark_dirty()
    return TEMPLATES.TemplateResponse(
        request, "partials/constraint_group.html",
        _ctx_group(data, key, "teacher", name) | {"request": request},
    )


@router.post("/teacher/{name}/{key}", response_class=HTMLResponse)
async def update_teacher(name: str, key: str, request: Request) -> HTMLResponse:
    store, data = _data()
    if key not in CONSTRAINT_KEYS:
        raise HTTPException(400, "مفتاح قيد غير معروف")
    if not _has_override(data, name, key):
        raise HTTPException(400, "لا يوجد تخصيص مفعَّل لهذا القيد لهذا الأستاذ")
    form = dict(await request.form())
    group = _parse_group_from_form(key, form, data["meta"]["days"])
    _write_group(data, key, "teacher", name, group)
    store.mark_dirty()
    return TEMPLATES.TemplateResponse(
        request, "partials/constraint_group.html",
        _ctx_group(data, key, "teacher", name) | {"request": request},
    )
