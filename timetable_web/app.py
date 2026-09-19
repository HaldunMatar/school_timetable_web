from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__
from .state.store import DEFAULT_JSON, get_store

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
TEMPLATES.env.globals["app_version"] = __version__


@asynccontextmanager
async def _lifespan(app: FastAPI):
    store = get_store()
    if store.data is None and DEFAULT_JSON.exists():
        store.load(DEFAULT_JSON, is_default=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="برنامج توزيع الأساتذة والحصص — نسخة الويب",
        version=__version__,
        lifespan=_lifespan,
    )
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> HTMLResponse:
        store = get_store()
        from .state.store import DATA_DIR
        file_names = sorted(p.name for p in DATA_DIR.glob("*.json"))
        return TEMPLATES.TemplateResponse(
            request,
            "home.html",
            {"store": store, "data": store.data, "file_names": file_names},
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    from .routers import constraints, dashboard, files, log, sections, solve, subjects, teachers

    app.include_router(files.router)
    app.include_router(teachers.router)
    app.include_router(sections.router)
    app.include_router(subjects.router)
    app.include_router(constraints.router)
    app.include_router(solve.router)
    app.include_router(dashboard.router)
    app.include_router(log.router)

    return app
