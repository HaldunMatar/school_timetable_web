"""In-memory state for the currently loaded school-data file.

Single-instance for now (localhost, single admin). Extending to multi-tenant
means keying by (user, school) — the shape below already isolates the state
in one object.
"""

from __future__ import annotations

import copy
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import scheduler

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

DEFAULT_JSON = DATA_DIR / "school_data_default.json"

_lock = threading.RLock()


class Store:
    """Holds everything a single web-session needs: the loaded data, the
    file path it came from, the dirty flag, and the last successful
    schedule for warm-starting the next solve."""

    def __init__(self) -> None:
        self.data: dict[str, Any] | None = None
        self.current_path: Path | None = None
        self.dirty: bool = False
        self.last_schedule_result: dict | None = None
        self.last_constraint_notes: dict | None = None
        self.last_constraint_fulfillment: dict | None = None
        self.solve_status: str = "idle"        # idle | running | done | failed
        self.solve_message: str = ""
        self.solve_progress: int = 0           # 0..100 (best-effort)
        self.solve_thread: threading.Thread | None = None
        self.generated_files: dict[str, str] = {}   # {label: filename}
        self.log_entries: list[tuple[str, str]] = []   # (ts, msg)

    @property
    def solve_busy(self) -> bool:
        t = self.solve_thread
        return t is not None and t.is_alive()

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_entries.append((ts, message))
        if len(self.log_entries) > 500:
            self.log_entries = self.log_entries[-500:]

    def load(self, path: Path, *, is_default: bool = False) -> None:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # Legacy-format migrations (same logic as gui.ensure_scheduling_constraints):
        _ensure_scheduling_constraints(data)
        scheduler.ensure_teacher_roster(data)
        for subj in data.get("subjects", []):
            scheduler.ensure_subject_constraints(subj)
        # اسم المدرسة (يظهر في الشريط العلوي وفي كل تقارير PDF) — حقل
        # اختياري أُضيف لاحقاً، فيُملأ فارغاً تلقائياً لأي ملف قديم لا يحويه.
        data.setdefault("meta", {}).setdefault("school_name", "")

        self.data = data
        self.current_path = path
        self.dirty = False
        self.last_schedule_result = None
        self.last_constraint_notes = None
        self.last_constraint_fulfillment = None
        self.log(f"تم تحميل الملف: {path.name}" + ("  (افتراضي)" if is_default else ""))

    def save(self, path: Path | None = None) -> Path:
        assert self.data is not None
        target = path or self.current_path
        assert target is not None, "لا يوجد ملف حالي للحفظ"
        with target.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        self.current_path = target
        self.dirty = False
        self.log(f"تم الحفظ إلى: {target.name}")
        return target

    def mark_dirty(self) -> None:
        self.dirty = True
        # invalidate warm-start on any mutation (fixes desktop gotcha)
        self.last_schedule_result = None


# Per-user in-memory stores. Keyed by username.
_stores: dict[str, Store] = {}
# Legacy compatibility: some tests still monkeypatch this attribute.
_store = Store()


def _store_for_supervisor(username: str, data_file: str | None) -> Store:
    if username not in _stores:
        st = Store()
        _stores[username] = st
        if data_file:
            path = (DATA_DIR / "schools" / data_file)
            if path.exists():
                st.load(path)
    return _stores[username]


def get_store() -> Store:
    """يعيد الـ Store الخاص بالمستخدم الحالي (المشرف).

    يقرأ current_user من auth.py عبر contextvar. يرفع 401 إن لم يكن هناك
    مستخدم، و 403 إن كان المدير (المدير لا يملك بيانات مدرسة)."""
    # delayed import to avoid circular
    from fastapi import HTTPException
    from ..auth import current_user

    user = current_user()
    if user is None:
        # Tests and legacy paths that predate auth still work via _store
        return _store
    if user.is_admin():
        raise HTTPException(400, "المدير لا يملك بيانات مدرسة — استخدم /admin لإدارة المشرفين")
    return _store_for_supervisor(user.username, user.data_file)


def drop_store(username: str) -> None:
    """يمسح كاش الـ Store لمستخدم — يُستدعى عند حذف/تعديل المستخدم."""
    _stores.pop(username, None)


def _ensure_scheduling_constraints(data: dict) -> None:
    """Mirror of app/gui.py:ensure_scheduling_constraints — ensures the
    scheduling_constraints skeleton exists and legacy shapes are migrated
    for both defaults and per_teacher entries."""
    sc = data.setdefault("scheduling_constraints", {})
    defaults = sc.setdefault("defaults", {})
    per_teacher = sc.setdefault("per_teacher", {})

    for key, base in scheduler.DEFAULT_TEACHER_CONSTRAINTS.items():
        defaults.setdefault(key, copy.deepcopy(base))

    if "day_off" in defaults:
        defaults["day_off"] = scheduler._normalize_day_off_group(defaults["day_off"])
    if "empty_periods" in defaults:
        defaults["empty_periods"] = scheduler._normalize_empty_periods_group(defaults["empty_periods"])

    for teacher_name, override in per_teacher.items():
        if "day_off" in override:
            override["day_off"] = scheduler._normalize_day_off_group(override["day_off"])
        if "empty_periods" in override:
            override["empty_periods"] = scheduler._normalize_empty_periods_group(override["empty_periods"])
