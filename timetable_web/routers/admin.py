"""مسارات الإدارة — /admin — إدارة حسابات المشرفين."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import (
    ROLE_SUPERVISOR,
    SCHOOLS_DIR,
    User,
    delete_user,
    find_user,
    load_users,
    make_user,
    require_admin,
    save_users,
    update_user,
)
from ..core import scheduler
from ..state.store import drop_store

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("", response_class=HTMLResponse)
def index(request: Request, admin: User = Depends(require_admin)) -> HTMLResponse:
    users = [u for u in load_users() if not u.is_admin()]
    admins = [u for u in load_users() if u.is_admin()]
    return TEMPLATES.TemplateResponse(
        request,
        "admin/users.html",
        {"users": users, "admins": admins, "me": admin},
    )


@router.post("/users/create")
def create_user(
    request: Request,
    admin: User = Depends(require_admin),
    username: str = Form(...),
    password: str = Form(...),
    periods_per_day: int = Form(7, ge=1, le=12),
    nisab_reference: int = Form(19, ge=1, le=60),
    day_الأحد: str = Form(""),
    day_الاثنين: str = Form(""),
    day_الثلاثاء: str = Form(""),
    day_الأربعاء: str = Form(""),
    day_الخميس: str = Form(""),
    day_الجمعة: str = Form(""),
    day_السبت: str = Form(""),
) -> RedirectResponse:
    username = username.strip()
    if not username or not password:
        raise HTTPException(400, "المستخدم وكلمة المرور مطلوبان")
    if len(password) < 4:
        raise HTTPException(400, "كلمة المرور يجب ألا تقل عن 4 حروف")
    if find_user(username):
        raise HTTPException(400, f"مستخدم باسم '{username}' موجود مسبقاً")

    day_flags = {
        "الأحد": day_الأحد, "الاثنين": day_الاثنين, "الثلاثاء": day_الثلاثاء,
        "الأربعاء": day_الأربعاء, "الخميس": day_الخميس,
        "الجمعة": day_الجمعة, "السبت": day_السبت,
    }
    days = [d for d, v in day_flags.items() if v == "on"]
    if not days:
        raise HTTPException(400, "اختر يوماً واحداً على الأقل")

    data_file = f"{username}.json"
    target = SCHOOLS_DIR / data_file
    if target.exists():
        raise HTTPException(409, f"ملف بيانات {data_file} موجود مسبقاً")
    SCHOOLS_DIR.mkdir(parents=True, exist_ok=True)

    blank = scheduler.new_blank_data(days, periods_per_day, nisab_reference)
    with target.open("w", encoding="utf-8") as f:
        json.dump(blank, f, ensure_ascii=False, indent=2)

    new_user = make_user(username, password, ROLE_SUPERVISOR, data_file=data_file, active=True)
    users = load_users()
    users.append(new_user)
    save_users(users)

    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{username}/toggle")
def toggle_active(
    username: str,
    admin: User = Depends(require_admin),
) -> RedirectResponse:
    user = find_user(username)
    if not user:
        raise HTTPException(404, "غير موجود")
    if user.is_admin():
        raise HTTPException(400, "لا يمكن تعطيل حساب مدير")
    update_user(username, active=not user.active)
    drop_store(username)  # invalidate their cached in-memory state
    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{username}/reset-password")
def reset_password(
    username: str,
    admin: User = Depends(require_admin),
    password: str = Form(...),
) -> RedirectResponse:
    if len(password) < 4:
        raise HTTPException(400, "كلمة المرور يجب ألا تقل عن 4 حروف")
    user = find_user(username)
    if not user:
        raise HTTPException(404, "غير موجود")
    new_user = make_user(username, password, user.role, data_file=user.data_file, active=user.active)
    new_user.created_at = user.created_at
    users = [new_user if u.username == username else u for u in load_users()]
    save_users(users)
    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{username}/upload-data")
async def upload_data_for_user(
    username: str,
    request: Request,
    admin: User = Depends(require_admin),
    file: UploadFile = None,
) -> RedirectResponse:
    """يستبدل ملف بيانات المشرف بملف JSON مرفوع من admin.
    يمسح كاش المشرف فوراً — الطلب التالي منه يقرأ الملف الجديد."""
    user = find_user(username)
    if not user or not user.data_file:
        raise HTTPException(404, "غير موجود أو لا يملك ملف بيانات")
    if file is None or not file.filename:
        raise HTTPException(400, "لم يُرفَع أي ملف")
    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(400, f"ملف JSON غير صالح: {exc}")
    # فحوص هيكلية أساسية — الحقول الجوهرية موجودة
    required = ["meta", "sections", "subjects"]
    missing = [k for k in required if k not in data]
    if missing:
        raise HTTPException(400, f"ملف JSON مفقود فيه الحقول: {', '.join(missing)}")
    meta = data.get("meta", {})
    if not meta.get("days") or not meta.get("periods_per_day"):
        raise HTTPException(400, "meta.days و meta.periods_per_day مطلوبان")

    target = SCHOOLS_DIR / user.data_file
    target.write_bytes(raw)
    drop_store(username)  # المشرف يقرأ الجديد على الطلب التالي
    return RedirectResponse("/admin", status_code=303)


@router.get("/users/{username}/download-data")
def download_data_for_user(username: str, admin: User = Depends(require_admin)) -> FileResponse:
    """تنزيل ملف بيانات مشرف (نسخة احتياطية للإدارة)."""
    user = find_user(username)
    if not user or not user.data_file:
        raise HTTPException(404, "غير موجود أو لا يملك ملف بيانات")
    target = SCHOOLS_DIR / user.data_file
    if not target.exists():
        raise HTTPException(404, "ملف البيانات غير موجود على القرص")
    return FileResponse(target, media_type="application/json", filename=user.data_file)


@router.post("/users/{username}/delete")
def delete_user_route(
    username: str,
    admin: User = Depends(require_admin),
    also_delete_data: str = Form(""),
) -> RedirectResponse:
    user = find_user(username)
    if not user:
        raise HTTPException(404, "غير موجود")
    if user.is_admin():
        raise HTTPException(400, "لا يمكن حذف حساب مدير من هنا")
    if also_delete_data == "on" and user.data_file:
        target = SCHOOLS_DIR / user.data_file
        if target.exists():
            target.unlink()
    delete_user(username)
    drop_store(username)
    return RedirectResponse("/admin", status_code=303)
