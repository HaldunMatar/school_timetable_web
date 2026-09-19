"""AuthMiddleware — يقرأ الجلسة، يحدّد المستخدم الحالي، يوجّه التسجيل/التفعيل."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

from .auth import find_user, set_current_user

# مسارات مسموحة بلا تسجيل دخول
PUBLIC_PATHS = {"/login", "/logout", "/healthz"}
PUBLIC_PREFIXES = ("/static/",)

_TPL = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        set_current_user(None)  # default

        # 1. مسارات عامة
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # 2. اقرأ الجلسة
        username = request.session.get("username")
        user = find_user(username) if username else None
        set_current_user(user)

        # 3. غير مسجَّل → توجيه إلى /login
        if user is None:
            if request.session.get("username"):
                # الجلسة تشير لحساب محذوف — امسحها
                request.session.pop("username", None)
            return RedirectResponse("/login", status_code=303)

        # 4. حساب غير مفعَّل → صفحة "معطَّل"
        if not user.active:
            return _TPL.TemplateResponse(
                request, "inactive.html", {"user": user}, status_code=403
            )

        # 5. مضبوط — أكمل
        return await call_next(request)
