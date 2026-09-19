"""مسارات /login و /logout — بلا حاجة لجلسة سابقة."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..auth import find_user, verify_password

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str | None = None) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request, "login.html", {"error": error}
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse:
    user = find_user(username.strip())
    if not user or not verify_password(user, password):
        return TEMPLATES.TemplateResponse(
            request,
            "login.html",
            {"error": "اسم المستخدم أو كلمة المرور غير صحيحة"},
            status_code=401,
        )
    request.session["username"] = user.username
    if user.is_admin():
        return RedirectResponse("/admin", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.pop("username", None)
    return RedirectResponse("/login", status_code=303)
