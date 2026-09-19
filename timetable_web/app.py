from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .auth import bootstrap_admin, current_user
from .middleware import AuthMiddleware
from .state.store import DATA_DIR, get_store

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
TEMPLATES.env.globals["app_version"] = __version__
TEMPLATES.env.globals["current_user"] = current_user


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # ينشئ حساب admin/admin تلقائياً عند غياب أي مستخدم
    bootstrap_admin()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="برنامج توزيع الأساتذة والحصص — نسخة الويب",
        version=__version__,
        lifespan=_lifespan,
    )

    # ملاحظة: Starlette ينفّذ الـ middleware بعكس ترتيب الإضافة —
    # آخر ما يُضاف = أول ما يُنفَّذ. لذا نضيف AuthMiddleware أولاً
    # (يصبح الداخلي) ثم SessionMiddleware (يصبح الخارجي وينفَّذ أولاً
    # فيوفّر request.session لـ AuthMiddleware).
    app.add_middleware(AuthMiddleware)
    secret = os.environ.get("TIMETABLE_SESSION_SECRET") or secrets.token_urlsafe(32)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="timetable_session",
        same_site="lax",
        https_only=False,
        max_age=60 * 60 * 24 * 7,  # أسبوع
    )

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        user = current_user()
        if user and user.is_admin():
            return RedirectResponse("/admin", status_code=303)
        store = get_store()
        # إن كان المشرف بلا ملف بيانات محمَّل بعد (كاش فارغ)، حاول تحميله
        if store.data is None and user and user.data_file:
            from .auth import SCHOOLS_DIR
            p = SCHOOLS_DIR / user.data_file
            if p.exists():
                store.load(p)
        return TEMPLATES.TemplateResponse(
            request,
            "home.html",
            {"store": store, "data": store.data, "file_names": []},
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    from .routers import (
        admin,
        auth_routes,
        constraints,
        dashboard,
        files,
        log,
        sections,
        solve,
        subjects,
        teachers,
    )

    # Every router file has its own Jinja2Templates instance; expose current_user
    # + app_version to all of them so `base.html` can render.
    _router_modules = (admin, auth_routes, constraints, dashboard, files, log,
                       sections, solve, subjects, teachers)
    for mod in _router_modules:
        tpl = getattr(mod, "TEMPLATES", None)
        if tpl is not None:
            tpl.env.globals["current_user"] = current_user
            tpl.env.globals["app_version"] = __version__

    app.include_router(auth_routes.router)
    app.include_router(admin.router)
    app.include_router(files.router)
    app.include_router(teachers.router)
    app.include_router(sections.router)
    app.include_router(subjects.router)
    app.include_router(constraints.router)
    app.include_router(solve.router)
    app.include_router(dashboard.router)
    app.include_router(log.router)

    return app
