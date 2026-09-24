"""File operations: open / save / restore-default (disabled) / new-school (later)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..core import scheduler
from ..state.store import DATA_DIR, DEFAULT_JSON, get_store

router = APIRouter(prefix="/file", tags=["file"])


@router.get("/list")
def list_data_files() -> list[str]:
    return sorted(p.name for p in DATA_DIR.glob("*.json"))


@router.post("/open")
def open_named(name: str = Form(...)) -> RedirectResponse:
    target = DATA_DIR / name
    if not target.exists():
        raise HTTPException(404, f"لا يوجد ملف باسم {name}")
    get_store().load(target)
    return RedirectResponse("/", status_code=303)


@router.post("/upload")
async def upload(file: UploadFile) -> RedirectResponse:
    import json
    raw = await file.read()
    try:
        data: Any = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400, f"ملف JSON غير صالح: {exc}")
    target = DATA_DIR / (file.filename or "uploaded.json")
    target.write_bytes(raw)
    get_store().load(target)
    return RedirectResponse("/", status_code=303)


@router.post("/save")
def save() -> Response:
    path = get_store().save()
    return Response(f"تم الحفظ: {path.name}")


@router.post("/school-name")
def update_school_name(name: str = Form("")) -> Response:
    """يُحدَّث اسم المدرسة (يظهر في الشريط العلوي وكل تقارير PDF). لا يحفظ
    على القرص فوراً — كأي تعديل آخر، يحتاج زر "حفظ"."""
    store = get_store()
    if store.data is None:
        raise HTTPException(400, "لا يوجد ملف محمَّل")
    store.data.setdefault("meta", {})["school_name"] = name.strip()
    store.mark_dirty()
    return Response('<span class="ok-mark">✓ تم التحديث (لا تنسَ الحفظ)</span>')


@router.post("/new")
async def new_school(request: Request) -> RedirectResponse:
    import json
    form = dict(await request.form())
    all_weekdays = scheduler.ALL_WEEKDAYS  # ordered
    days = [d for d in all_weekdays if form.get(f"day_{d}") == "on"]
    if not days:
        raise HTTPException(400, "اختر يوماً واحداً على الأقل")
    try:
        periods_per_day = int(form.get("periods_per_day", 7))
        nisab_reference = int(form.get("nisab_reference", 19))
    except ValueError:
        raise HTTPException(400, "قيم عددية غير صالحة")
    filename = (form.get("filename") or "").strip()
    if not filename:
        raise HTTPException(400, "اسم الملف مطلوب")
    if not filename.endswith(".json"):
        filename += ".json"
    target = DATA_DIR / filename
    if target.exists():
        raise HTTPException(409, f"ملف باسم {filename} موجود بالفعل")
    data = scheduler.new_blank_data(days, periods_per_day, nisab_reference)
    with target.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    get_store().load(target)
    return RedirectResponse("/", status_code=303)


@router.post("/fill-missing-teachers")
def fill_missing_teachers() -> Response:
    store = get_store()
    if store.data is None:
        raise HTTPException(400, "لا يوجد ملف محمَّل")
    added = scheduler.ensure_min_teachers(store.data)
    if added:
        store.mark_dirty()
        for subject_name, names in added:
            store.log(f"مادة {subject_name}: أُضيف {len(names)} أستاذ افتراضي")
        summary = " · ".join(f"{s}: +{len(n)}" for s, n in added)
        return Response(f"تم إضافة أساتذة افتراضيين — {summary}")
    return Response("لا توجد مواد تحتاج أساتذة إضافيين — الجميع مغطى.")


@router.get("/download")
def download() -> Response:
    import json
    store = get_store()
    if store.data is None or store.current_path is None:
        raise HTTPException(404, "لا يوجد ملف محمَّل")
    body = json.dumps(store.data, ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{store.current_path.name}"'},
    )
