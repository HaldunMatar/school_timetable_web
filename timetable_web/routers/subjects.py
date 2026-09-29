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

def _validate_manual_row(data, subj, teacher, track, secs, exclude_index=None):
    if teacher not in subj.get("names", []):
        raise HTTPException(400, "الأستاذ ليس من أساتذة هذه المادة")
    if track not in data["meta"]["grade_order"]:
        raise HTTPException(400, "صف غير معروف")
    if not secs:
        raise HTTPException(400, "اختر شعبة واحدة على الأقل")
    max_sec = data.get("sections", {}).get(track, 0)
    for s in secs:
        if s < 1 or s > max_sec:
            raise HTTPException(400, f"شعبة {s} خارج نطاق صف {track} (1..{max_sec})")
    # Prevent same (track, section) pinned to two teachers
    existing = subj.get("manual_assignments", []) or []
    for i, row in enumerate(existing):
        if exclude_index is not None and i == exclude_index:
            continue
        if row["track"] == track:
            for s in row.get("sections", []):
                if s in secs and row["teacher"] != teacher:
                    raise HTTPException(400,
                        f"شعبة {s} في {track} مُسنَدة بالفعل للأستاذ {row['teacher']}")


@router.post("/{idx}/manual/add", response_class=HTMLResponse)
def add_manual(
    idx: int,
    request: Request,
    teacher: str = Form(...),
    track: str = Form(...),
    sections: list[int] = Form(...),
) -> HTMLResponse:
    store, data, subj = _subject(idx)
    secs = sorted(set(sections))
    _validate_manual_row(data, subj, teacher, track, secs)
    subj.setdefault("manual_assignments", []).append(
        {"teacher": teacher, "track": track, "sections": secs}
    )
    store.mark_dirty()
    store.log(f"إسناد إجباري: {teacher} → {track} شعب {secs}")
    return TEMPLATES.TemplateResponse(
        request, "partials/manual_list.html", _editor_ctx(request, idx)
    )


@router.get("/{idx}/manual/{mindex}/edit", response_class=HTMLResponse)
def edit_manual_form(idx: int, mindex: int, request: Request) -> HTMLResponse:
    store, data, subj = _subject(idx)
    manual = subj.get("manual_assignments", []) or []
    if mindex < 0 or mindex >= len(manual):
        raise HTTPException(404, "إسناد غير موجود")
    ctx = _editor_ctx(request, idx)
    ctx["mindex"] = mindex
    ctx["row"] = manual[mindex]
    return TEMPLATES.TemplateResponse(request, "partials/manual_edit_row.html", ctx)


@router.post("/{idx}/manual/{mindex}/update", response_class=HTMLResponse)
def update_manual(
    idx: int,
    mindex: int,
    request: Request,
    teacher: str = Form(...),
    track: str = Form(...),
    sections: list[int] = Form(...),
) -> HTMLResponse:
    store, data, subj = _subject(idx)
    manual = subj.get("manual_assignments", []) or []
    if mindex < 0 or mindex >= len(manual):
        raise HTTPException(404, "إسناد غير موجود")
    secs = sorted(set(sections))
    _validate_manual_row(data, subj, teacher, track, secs, exclude_index=mindex)
    manual[mindex] = {"teacher": teacher, "track": track, "sections": secs}
    store.mark_dirty()
    store.log(f"تعديل إسناد إجباري: {teacher} → {track} شعب {secs}")
    return TEMPLATES.TemplateResponse(
        request, "partials/manual_list.html", _editor_ctx(request, idx)
    )


@router.get("/{idx}/manual-list", response_class=HTMLResponse)
def manual_list_partial(idx: int, request: Request) -> HTMLResponse:
    """يُعيد عرض القائمة فقط - يستخدمه زر "إلغاء" أثناء التعديل السطري
    للتراجع دون حفظ، بلا الحاجة لإعادة جلب المحرِّر بالكامل."""
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

def _validate_merge_row(data, subj, teacher, track, secs, exclude_index=None):
    if teacher not in subj.get("names", []):
        raise HTTPException(400, "الأستاذ ليس من أساتذة هذه المادة")
    if track not in data["meta"]["grade_order"]:
        raise HTTPException(400, "صف غير معروف")
    if len(secs) != 2 or secs[0] == secs[1]:
        raise HTTPException(400, "اختر شعبتين مختلفتين للدمج")
    max_sec = data.get("sections", {}).get(track, 0)
    for s in secs:
        if s < 1 or s > max_sec:
            raise HTTPException(400, f"شعبة {s} خارج نطاق صف {track} (1..{max_sec})")
    existing = subj.get("merged_groups", []) or []
    for i, row in enumerate(existing):
        if exclude_index is not None and i == exclude_index:
            continue
        if row["track"] == track and set(row.get("sections", [])) & set(secs):
            raise HTTPException(
                400, f"إحدى الشعبتين {secs} مضمومة بالفعل في عملية دمج أخرى في {track}"
            )
    for row in subj.get("manual_assignments", []) or []:
        if row.get("track") == track and set(row.get("sections", [])) & set(secs):
            raise HTTPException(
                400, f"إحدى الشعبتين {secs} لها إسناد إجباري منفصل بالفعل - أزله أولاً"
            )


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
    secs = sorted([section_a, section_b])
    _validate_merge_row(data, subj, teacher, track, secs)
    subj.setdefault("merged_groups", []).append(
        {"teacher": teacher, "track": track, "sections": secs}
    )
    store.mark_dirty()
    store.log(f"دمج شعب: {teacher} ← {track} شعبتا {secs} في نفس الوقت")
    return TEMPLATES.TemplateResponse(
        request, "partials/merge_list.html", _editor_ctx(request, idx)
    )


@router.get("/{idx}/merge/{mindex}/edit", response_class=HTMLResponse)
def edit_merge_form(idx: int, mindex: int, request: Request) -> HTMLResponse:
    store, data, subj = _subject(idx)
    groups = subj.get("merged_groups", []) or []
    if mindex < 0 or mindex >= len(groups):
        raise HTTPException(404, "دمج غير موجود")
    ctx = _editor_ctx(request, idx)
    ctx["mindex"] = mindex
    ctx["row"] = groups[mindex]
    return TEMPLATES.TemplateResponse(request, "partials/merge_edit_row.html", ctx)


@router.post("/{idx}/merge/{mindex}/update", response_class=HTMLResponse)
def update_merge(
    idx: int,
    mindex: int,
    request: Request,
    teacher: str = Form(...),
    track: str = Form(...),
    section_a: int = Form(...),
    section_b: int = Form(...),
) -> HTMLResponse:
    store, data, subj = _subject(idx)
    groups = subj.get("merged_groups", []) or []
    if mindex < 0 or mindex >= len(groups):
        raise HTTPException(404, "دمج غير موجود")
    secs = sorted([section_a, section_b])
    _validate_merge_row(data, subj, teacher, track, secs, exclude_index=mindex)
    groups[mindex] = {"teacher": teacher, "track": track, "sections": secs}
    store.mark_dirty()
    store.log(f"تعديل دمج شعب: {teacher} ← {track} شعبتا {secs}")
    return TEMPLATES.TemplateResponse(
        request, "partials/merge_list.html", _editor_ctx(request, idx)
    )


@router.get("/{idx}/merge-list", response_class=HTMLResponse)
def merge_list_partial(idx: int, request: Request) -> HTMLResponse:
    """للتراجع أثناء التعديل السطري - انظر manual_list_partial أعلاه."""
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


# --- حصة ثابتة بلا أستاذ (fixed_no_teacher_slots) ---
# مادة معينة (مثل الرياضة) تُوضَع دائماً برقم حصة ثابت (أي يوم يختاره
# الحل) لشعبة معينة أو لكل الشعب، بلا أي أستاذ - يظهر اسم المادة فقط في
# البرنامج. من حساب المشرف (مدير المدرسة) نفسه، على عكس priority_teachers
# أعلاه الذي هو من لوحة الأدمن الكبير حصراً.

@router.post("/{idx}/fixed-slot/add", response_class=HTMLResponse)
def add_fixed_slot(
    idx: int,
    request: Request,
    track: str = Form(...),
    period_index: int = Form(...),
    all_sections: str = Form(""),
    sections: list[int] = Form([]),
) -> HTMLResponse:
    store, data, subj = _subject(idx)
    if track not in data["meta"]["grade_order"]:
        raise HTTPException(400, "صف غير معروف")
    rule = {
        "track": track,
        "period_index": period_index,
        "sections": "all" if all_sections == "on" else sorted(set(sections)),
    }
    subj.setdefault("fixed_no_teacher_slots", []).append(rule)
    try:
        scheduler.validate_fixed_no_teacher_slots(data)
    except RuntimeError as exc:
        subj["fixed_no_teacher_slots"].pop()  # تراجع - لا نحفظ إعداداً غير صالح
        raise HTTPException(400, str(exc))
    store.mark_dirty()
    sec_desc = "كل الشعب" if rule["sections"] == "all" else f"شعب {rule['sections']}"
    store.log(f"حصة ثابتة بلا أستاذ: {subj['name']} ← {track} ({sec_desc}) — الحصة {period_index}")
    return TEMPLATES.TemplateResponse(
        request, "partials/fixed_slot_list.html", _editor_ctx(request, idx)
    )


@router.post("/{idx}/fixed-slot/{findex}/delete", response_class=HTMLResponse)
def remove_fixed_slot(idx: int, findex: int, request: Request) -> HTMLResponse:
    store, data, subj = _subject(idx)
    rules = subj.setdefault("fixed_no_teacher_slots", [])
    if findex < 0 or findex >= len(rules):
        raise HTTPException(404, "غير موجود")
    rules.pop(findex)
    store.mark_dirty()
    return TEMPLATES.TemplateResponse(
        request, "partials/fixed_slot_list.html", _editor_ctx(request, idx)
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
