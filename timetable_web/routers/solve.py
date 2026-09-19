"""تبويب التوليد — يشغّل محرك CP-SAT و/أو يُولّد ملفات PDF المختلفة.

يعكس شريط الأزرار السفلي في gui.py:
- ⚙ توليد البرامج الثلاثة (PDF) — solve + generate_all_pdfs
- 📋 تقرير شروط الأساتذة — بلا حلّ (يقرأ scheduling_constraints فقط)
- 🔢 ترتيب حسب تعقيد الشروط — بلا حلّ
- 📊 تقرير نسبة تحقق الرغبات — solve + generate_fulfillment_report_pdf
"""

from __future__ import annotations

import threading
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from ..core import pdf_gen, scheduler
from ..state.store import OUTPUT_DIR, get_store

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/solve", tags=["solve"])


def _need_data():
    store = get_store()
    if store.data is None:
        raise HTTPException(400, "لا يوجد ملف محمَّل")
    return store


def _set_status(store, status: str, message: str = "", progress: int | None = None) -> None:
    store.solve_status = status
    if message:
        store.solve_message = message
    if progress is not None:
        store.solve_progress = progress


def _relative(paths: dict[str, str] | dict[str, Path]) -> dict[str, str]:
    """Convert absolute paths from pdf_gen into filenames (served via /solve/download/<name>)."""
    return {label: Path(str(p)).name for label, p in paths.items()}


# --------------------------------------------------- page & polling ----

@router.get("", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    store = _need_data()
    return TEMPLATES.TemplateResponse(
        request, "solve.html", {"store": store, "data": store.data}
    )


@router.get("/status", response_class=HTMLResponse)
def status(request: Request) -> HTMLResponse:
    store = _need_data()
    return TEMPLATES.TemplateResponse(
        request, "partials/solve_status.html", {"store": store}
    )


# --------------------------------------------------- workers ----------

def _run_full_solve(store):
    """Solve + generate_all_pdfs. Runs in a background thread."""
    def _prog(msg: str) -> None:
        store.log(msg)
        store.solve_message = msg

    try:
        _set_status(store, "running", "جاري تحميل البيانات وتحضير المتطلبات...", 5)
        _prog("بدء الحلّ (مهلة 5 دقائق)...")

        result = scheduler.solve_timetable(
            store.data,
            max_time_in_seconds=300,
            num_workers=8,
            progress=_prog,
            warm_start=store.last_schedule_result,
        )
        # scheduler returns (status_name, section_sched, constraint_notes, constraint_fulfillment)
        status_name, section_sched, constraint_notes, constraint_fulfillment = result

        store.last_schedule_result = section_sched
        store.last_constraint_notes = constraint_notes
        store.last_constraint_fulfillment = constraint_fulfillment

        _set_status(store, "running", "جاري توليد ملفات PDF...", 80)
        paths = pdf_gen.generate_all_pdfs(
            store.data,
            section_sched,
            str(OUTPUT_DIR),
            progress=_prog,
            constraint_notes=constraint_notes,
            constraint_fulfillment=constraint_fulfillment,
        )
        store.generated_files = _relative(paths)
        _set_status(store, "done", f"تم بنجاح — {len(paths)} ملفات ({status_name})", 100)
        store.log(f"تم توليد {len(paths)} ملفات PDF")

    except Exception as exc:
        _set_status(store, "failed", f"فشل التوليد: {exc}", 100)
        store.log(f"خطأ: {exc}")


def _run_fulfillment_only(store):
    """Solve + generate_fulfillment_report_pdf only."""
    def _prog(msg: str) -> None:
        store.log(msg)
        store.solve_message = msg

    try:
        _set_status(store, "running", "جاري الحلّ لحساب نسبة التحقق...", 5)
        path, section_sched = pdf_gen.generate_fulfillment_report_pdf(
            store.data, str(OUTPUT_DIR),
            progress=_prog,
            warm_start=store.last_schedule_result,
        )
        store.last_schedule_result = section_sched
        # merge into generated files (don't wipe main PDFs if they exist)
        store.generated_files = {**store.generated_files, "fulfillment": Path(path).name}
        _set_status(store, "done", "تم توليد تقرير نسبة التحقق", 100)
        store.log("تم توليد تقرير نسبة التحقق")

    except Exception as exc:
        _set_status(store, "failed", f"فشل التوليد: {exc}", 100)
        store.log(f"خطأ: {exc}")


def _start_thread(store, target) -> None:
    if store.solve_busy:
        raise HTTPException(409, "هناك عملية توليد قيد التشغيل حالياً — الرجاء الانتظار حتى تنتهي")
    store.generated_files = {}
    t = threading.Thread(target=target, args=(store,), name="solve", daemon=True)
    store.solve_thread = t
    t.start()


# --------------------------------------------------- action endpoints -

@router.post("/generate-all", response_class=HTMLResponse)
def generate_all(request: Request) -> HTMLResponse:
    store = _need_data()
    _start_thread(store, _run_full_solve)
    return TEMPLATES.TemplateResponse(
        request, "partials/solve_status.html", {"store": store}
    )


@router.post("/fulfillment-report", response_class=HTMLResponse)
def fulfillment(request: Request) -> HTMLResponse:
    store = _need_data()
    _start_thread(store, _run_fulfillment_only)
    return TEMPLATES.TemplateResponse(
        request, "partials/solve_status.html", {"store": store}
    )


@router.post("/constraints-report", response_class=HTMLResponse)
def constraints_report(request: Request) -> HTMLResponse:
    store = _need_data()
    try:
        path = pdf_gen.generate_constraints_report_pdf(store.data, str(OUTPUT_DIR))
        store.generated_files = {**store.generated_files, "constraints": Path(path).name}
        _set_status(store, "done", "تم توليد تقرير الشروط", 100)
        store.log("تم توليد تقرير شروط الأساتذة")
    except Exception as exc:
        _set_status(store, "failed", f"فشل: {exc}", 100)
    return TEMPLATES.TemplateResponse(
        request, "partials/solve_status.html", {"store": store}
    )


@router.post("/complexity-report", response_class=HTMLResponse)
def complexity_report(request: Request) -> HTMLResponse:
    store = _need_data()
    try:
        path = pdf_gen.generate_complexity_report_pdf(store.data, str(OUTPUT_DIR))
        store.generated_files = {**store.generated_files, "complexity": Path(path).name}
        _set_status(store, "done", "تم توليد ترتيب التعقيد", 100)
        store.log("تم توليد ترتيب تعقيد الشروط")
    except Exception as exc:
        _set_status(store, "failed", f"فشل: {exc}", 100)
    return TEMPLATES.TemplateResponse(
        request, "partials/solve_status.html", {"store": store}
    )


# --------------------------------------------------- downloads --------

@router.get("/download/{filename}")
def download(filename: str):
    # Path traversal protection: only files inside OUTPUT_DIR
    target = (OUTPUT_DIR / filename).resolve()
    if not str(target).startswith(str(OUTPUT_DIR.resolve())) or not target.is_file():
        raise HTTPException(404, "ملف غير موجود")
    return FileResponse(target, media_type="application/pdf", filename=filename)
