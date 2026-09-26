"""تبويب "البيانات" — إدارة المواد مع مصفوفة الحصص + قائمة الأساتذة +
الإسناد الإجباري + قيود المادة الصلبة.

مقابل SubjectEditor + قائمة المواد في gui.py (139-812).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from ..core import scheduler
from ..state.store import get_store

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/subjects", tags=["subjects"])

CATEGORIES = ["تربوية", "شرعية"]


def _data():
    store = get_store()
    if store.data is None:
        raise HTTPException(400, "لا يوجد ملف محمَّل")
    return store, store.data


def _subject(idx: int):
    store, data = _data()
    subjects = data.get("subjects", [])
    if idx < 0 or idx >= len(subjects):
        raise HTTPException(404, f"مادة رقم {idx} غير موجودة")
    return store, data, subjects[idx]


def _list_ctx(request: Request, selected: int | None = None):
    store, data = _data()
    subjects = data.get("subjects", [])
    return {
        "request": request,
        "store": store,
        "data": data,
        "subjects": subjects,
        "selected": selected,
        "categories": CATEGORIES,
        "grade_order": data["meta"]["grade_order"],
        "grade_labels": data["meta"].get("grade_labels", {}),
    }


def _editor_ctx(request: Request, idx: int):
    store, data, subj = _subject(idx)
    scheduler.ensure_subject_constraints(subj)
    return {
        "request": request,
        "store": store,
        "data": data,
        "subj": subj,
        "idx": idx,
        "categories": CATEGORIES,
        "grade_order": data["meta"]["grade_order"],
        "grade_labels": data["meta"].get("grade_labels", {}),
        "sections": data.get("sections", {}),
        "roster_names": data.get("teachers", []),
        "current_periods_by_teacher": {
            n: scheduler.teacher_current_periods(data, n) for n in data.get("teachers", [])
        },
    }


# --------------------------------------------------- pages -------------

@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "subjects.html", _list_ctx(request))


@router.get("/{idx}", response_class=HTMLResponse)
def index_selected(idx: int, request: Request) -> HTMLResponse:
    _subject(idx)  # existence check
    return TEMPLATES.TemplateResponse(request, "subjects.html", _list_ctx(request, selected=idx))


# --------------------------------------------------- partials ----------

@router.get("/{idx}/editor", response_class=HTMLResponse)
def editor(idx: int, request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request, "partials/subject_editor.html", _editor_ctx(request, idx)
    )


# --------------------------------------------------- CRUD --------------

@router.post("/new", response_class=HTMLResponse)
def create(request: Request, name: str = Form(...)) -> HTMLResponse:
    store, data = _data()
    name = name.strip()
    if not name:
        raise HTTPException(400, "اسم المادة مطلوب")
    if any(s["name"] == name for s in data.get("subjects", [])):
        raise HTTPException(400, f"مادة باسم '{name}' موجودة بالفعل")
    grade_order = data["meta"]["grade_order"]
    data["subjects"].append({
        "name": name,
        "category": "تربوية",
        "periods": {g: 0 for g in grade_order},
        "names": [],
        "manual_assignments": [],
        "constraints": {
            "max_consecutive_per_day": {"enabled": False, "max": 2},
            "max_daily_per_section": {"enabled": False, "max": 2},
        },
    })
    store.mark_dirty()
    store.log(f"أُضيفت مادة: {name}")
    return TEMPLATES.TemplateResponse(request, "partials/subject_list.html", _list_ctx(request))


@router.post("/{idx}/delete", response_class=HTMLResponse)
def delete(idx: int, request: Request) -> HTMLResponse:
    store, data, subj = _subject(idx)
    name = subj["name"]
    data["subjects"].pop(idx)
    store.mark_dirty()
    store.log(f"حُذفت مادة: {name}")
    return TEMPLATES.TemplateResponse(request, "partials/subject_list.html", _list_ctx(request))


@router.post("/{idx}/basic", response_class=HTMLResponse)
def update_basic(
    idx: int,
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
) -> HTMLResponse:
    store, data, subj = _subject(idx)
    name = name.strip()
    if not name:
        raise HTTPException(400, "الاسم مطلوب")
    if category not in CATEGORIES:
        raise HTTPException(400, "تصنيف غير صالح")
    subj["name"] = name
    subj["category"] = category
    store.mark_dirty()
    store.log(f"تم تعديل: {name}")
    return HTMLResponse(f'<span class="ok-mark">✓ حُفظ</span>')


@router.post("/{idx}/period/{grade}", response_class=HTMLResponse)
def update_period(
    idx: int,
    grade: str,
    count: float = Form(..., ge=0, le=40),
) -> HTMLResponse:
    store, data, subj = _subject(idx)
    if grade not in data["meta"]["grade_order"]:
        raise HTTPException(404, f"صف غير معروف: {grade}")
    subj.setdefault("periods", {})[grade] = count
    store.mark_dirty()
    # Return updated row total
    total = sum(subj["periods"].get(g, 0) or 0 for g in data["meta"]["grade_order"])
    return HTMLResponse(f'<span class="ok-mark">إجمالي: {total}</span>')


# --- names (teachers assigned to this subject) ---

@router.post("/{idx}/name/add", response_class=HTMLResponse)
def add_name(idx: int, request: Request, name: str = Form(...)) -> HTMLResponse:
    store, data, subj = _subject(idx)
    name = name.strip()
    if not name:
        raise HTTPException(400, "اسم مطلوب")
    if name not in data.get("teachers", []):
        raise HTTPException(400, f"'{name}' ليس في القائمة المركزية. أضفه من تبويب قائمة الأساتذة أولاً.")
    if name in subj.get("names", []):
        raise HTTPException(400, f"الاسم '{name}' مضاف بالفعل لهذه المادة")
    subj.setdefault("names", []).append(name)
    store.mark_dirty()
    store.log(f"أُضيف {name} إلى مادة {subj['name']}")
    # يُعاد رسم المحرِّر كاملاً (لا فقط بطاقة الأساتذة) لأن قائمتي "إسناد
    # إجباري" و"دمج شعبتين" أدناه تبنيان خيارات <select> "الأستاذ" الخاصة
    # بهما من نفس subj.names عند الرسم، فتبقيان بلا هذا الاسم الجديد (بل
    # فارغتين بالكامل إن كان هذا أول أستاذ للمادة) حتى تحديث كامل للصفحة
    # لو اقتصر الرد على بطاقة الأساتذة وحدها.
    return TEMPLATES.TemplateResponse(
        request, "partials/subject_editor.html", _editor_ctx(request, idx)
    )


@router.post("/{idx}/name/remove", response_class=HTMLResponse)
def remove_name(idx: int, request: Request, name: str = Form(...)) -> HTMLResponse:
    store, data, subj = _subject(idx)
    names = subj.get("names", [])
    if name not in names:
        raise HTTPException(404, "الاسم غير موجود في هذه المادة")
    names.remove(name)
    # Also drop any manual assignments / merged sections referencing this teacher
    subj["manual_assignments"] = [m for m in subj.get("manual_assignments", []) if m.get("teacher") != name]
    subj["merged_groups"] = [g for g in subj.get("merged_groups", []) if g.get("teacher") != name]
    store.mark_dirty()
    store.log(f"أُزيل {name} من مادة {subj['name']}")
    return TEMPLATES.TemplateResponse(
        request, "partials/subject_editor.html", _editor_ctx(request, idx)
    )


# --- manual assignments ---

@router.post("/{idx}/manual/add", response_class=HTMLResponse)
def add_manual(
    idx: int,
    request: Request,
    teacher: str = Form(...),
    track: str = Form(...),
    section_csv: str = Form(...),
) -> HTMLResponse:
    store, data, subj = _subject(idx)
    if teacher not in subj.get("names", []):
        raise HTTPException(400, "الأستاذ ليس من أساتذة هذه المادة")
    if track not in data["meta"]["grade_order"]:
        raise HTTPException(400, "صف غير معروف")
    try:
        secs = sorted({int(x.strip()) for x in section_csv.split(",") if x.strip()})
    except ValueError:
        raise HTTPException(400, "أرقام الشعب يجب أن تكون أعداداً صحيحة مفصولة بفواصل")
    if not secs:
        raise HTTPException(400, "أدخل رقم شعبة واحداً على الأقل")
    max_sec = data.get("sections", {}).get(track, 0)
    for s in secs:
        if s < 1 or s > max_sec:
            raise HTTPException(400, f"شعبة {s} خارج نطاق صف {track} (1..{max_sec})")
    # Prevent same (track, section) pinned to two teachers
    existing = subj.setdefault("manual_assignments", [])
    for row in existing:
        if row["track"] == track:
            for s in row.get("sections", []):
                if s in secs and row["teacher"] != teacher:
                    raise HTTPException(400,
                        f"شعبة {s} في {track} مُسنَدة بالفعل للأستاذ {row['teacher']}")
    existing.append({"teacher": teacher, "track": track, "sections": secs})
    store.mark_dirty()
    store.log(f"إسناد إجباري: {teacher} → {track} شعب {secs}")
    return TEMPLATES.TemplateResponse(
        request, "partials/manual_list.html", _editor_ctx(request, idx)
    )


@router.post("/{idx}/manual/{mindex}/delete", response_class=HTMLResponse)
def remove_manual(idx: int, mindex: int, request: Request) -> HTMLResponse:
    store, data, subj = _subject(idx)
    manual = subj.setdefault("manual_assignments", [])
    if mindex < 0 or mindex >= len(manual):
        raise HTTPException(404, "إسناد غير موجود")
    manual.pop(mindex)
    store.mark_dirty()
    return TEMPLATES.TemplateResponse(
        request, "partials/manual_list.html", _editor_ctx(request, idx)
    )


# --- merged sections (نفس الأستاذ، نفس الوقت - درس مشترك) ---

@router.post("/{idx}/merge/add", response_class=HTMLResponse)
def add_merge(
    idx: int,
    request: Request,
    teacher: str = Form(...),
    track: str = Form(...),
    section_a: int = Form(...),
    section_b: int = Form(...),
) -> HTMLResponse:
    store, data, subj = _subject(idx)
    if teacher not in subj.get("names", []):
        raise HTTPException(400, "الأستاذ ليس من أساتذة هذه المادة")
    if track not in data["meta"]["grade_order"]:
        raise HTTPException(400, "صف غير معروف")
    if section_a == section_b:
        raise HTTPException(400, "اختر شعبتين مختلفتين للدمج")
    secs = sorted([section_a, section_b])
    max_sec = data.get("sections", {}).get(track, 0)
    for s in secs:
        if s < 1 or s > max_sec:
            raise HTTPException(400, f"شعبة {s} خارج نطاق صف {track} (1..{max_sec})")
    existing = subj.setdefault("merged_groups", [])
    for row in existing:
        if row["track"] == track and set(row.get("sections", [])) & set(secs):
            raise HTTPException(
                400, f"إحدى الشعبتين {secs} مضمومة بالفعل في عملية دمج أخرى في {track}"
            )
    for row in subj.get("manual_assignments", []) or []:
        if row.get("track") == track and set(row.get("sections", [])) & set(secs):
            raise HTTPException(
                400, f"إحدى الشعبتين {secs} لها إسناد إجباري منفصل بالفعل - أزله أولاً"
            )
    existing.append({"teacher": teacher, "track": track, "sections": secs})
    store.mark_dirty()
    store.log(f"دمج شعب: {teacher} ← {track} شعبتا {secs} في نفس الوقت")
    return TEMPLATES.TemplateResponse(
        request, "partials/merge_list.html", _editor_ctx(request, idx)
    )


@router.post("/{idx}/merge/{mindex}/delete", response_class=HTMLResponse)
def remove_merge(idx: int, mindex: int, request: Request) -> HTMLResponse:
    store, data, subj = _subject(idx)
    groups = subj.setdefault("merged_groups", [])
    if mindex < 0 or mindex >= len(groups):
        raise HTTPException(404, "دمج غير موجود")
    groups.pop(mindex)
    store.mark_dirty()
    return TEMPLATES.TemplateResponse(
        request, "partials/merge_list.html", _editor_ctx(request, idx)
    )


# --- subject constraints (hard) ---

@router.post("/{idx}/constraint/{key}", response_class=HTMLResponse)
def update_constraint(
    idx: int,
    key: str,
    request: Request,
    enabled: str = Form(""),
    max_value: int = Form(2, ge=1, le=40),
) -> HTMLResponse:
    store, data, subj = _subject(idx)
    if key not in ("max_consecutive_per_day", "max_daily_per_section"):
        raise HTTPException(400, "مفتاح قيد غير معروف")
    scheduler.ensure_subject_constraints(subj)
    subj["constraints"][key] = {
        "enabled": enabled == "on",
        "max": max_value,
    }
    store.mark_dirty()
    return HTMLResponse('<span class="ok-mark">✓</span>')
