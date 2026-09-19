"""Shared pytest fixtures — isolated tmp workspace + fresh users/store per test.

Since the app now requires auth, `client` is auto-logged-in as a supervisor
whose data file (test.json) contains `tiny_data`. Admin-only tests can use
`admin_client` instead.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _tiny_data() -> dict[str, Any]:
    return {
        "meta": {
            "days": ["الأحد", "الاثنين", "الثلاثاء"],
            "periods_per_day": 4,
            "grade_order": ["ع1", "ع2"],
            "grade_labels": {"ع1": "سابع", "ع2": "ثامن"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1, "ع2": 1},
        "teachers": ["أحمد", "بشير"],
        "subjects": [
            {"name": "الرياضيات", "category": "تربوية",
             "periods": {"ع1": 3, "ع2": 3}, "names": ["أحمد"],
             "manual_assignments": [],
             "constraints": {"max_consecutive_per_day": {"enabled": False, "max": 2},
                             "max_daily_per_section": {"enabled": False, "max": 2}}},
            {"name": "اللغة", "category": "تربوية",
             "periods": {"ع1": 3, "ع2": 3}, "names": ["بشير"],
             "manual_assignments": [],
             "constraints": {"max_consecutive_per_day": {"enabled": False, "max": 2},
                             "max_daily_per_section": {"enabled": False, "max": 2}}},
        ],
        "scheduling_constraints": {
            "defaults": {
                "empty_periods": {"enabled": False,
                                  "start": {"enabled": False, "count": 1},
                                  "end": {"enabled": False, "count": 1},
                                  "days_mode": "all", "days": []},
                "day_off": {"enabled": False, "mode": "specific", "days": [], "count": 1},
                "max_gap_windows": {"enabled": False, "max": 1},
                "start_from_beginning": {"enabled": False},
            },
            "per_teacher": {},
        },
    }


@pytest.fixture
def tiny_data() -> dict[str, Any]:
    return _tiny_data()


SUPERVISOR_USER = "test_supervisor"
SUPERVISOR_PW = "test_pw"


@pytest.fixture
def tmp_workspace(tmp_path: Path, monkeypatch, tiny_data) -> dict[str, Path]:
    data_dir = tmp_path / "data"
    schools_dir = data_dir / "schools"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    schools_dir.mkdir()
    output_dir.mkdir()

    # Supervisor's data file
    test_file = schools_dir / "test.json"
    test_file.write_text(json.dumps(tiny_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Redirect all path constants BEFORE importing app
    from timetable_web.state import store as store_mod
    monkeypatch.setattr(store_mod, "DATA_DIR", data_dir)
    monkeypatch.setattr(store_mod, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(store_mod, "_stores", {})
    monkeypatch.setattr(store_mod, "_store", store_mod.Store())

    from timetable_web import auth as auth_mod
    users_file = data_dir / "users.json"
    monkeypatch.setattr(auth_mod, "USERS_FILE", users_file)
    monkeypatch.setattr(auth_mod, "SCHOOLS_DIR", schools_dir)

    from timetable_web import app as app_mod
    monkeypatch.setattr(app_mod, "DATA_DIR", data_dir)

    from timetable_web.routers import files as files_mod
    monkeypatch.setattr(files_mod, "DATA_DIR", data_dir)
    from timetable_web.routers import solve as solve_mod
    monkeypatch.setattr(solve_mod, "OUTPUT_DIR", output_dir)
    from timetable_web.routers import admin as admin_mod
    monkeypatch.setattr(admin_mod, "SCHOOLS_DIR", schools_dir)

    # Seed users: bootstrap admin + a test supervisor pointed at test.json
    admin = auth_mod.make_user("admin", "admin", auth_mod.ROLE_ADMIN)
    supervisor = auth_mod.make_user(
        SUPERVISOR_USER, SUPERVISOR_PW, auth_mod.ROLE_SUPERVISOR,
        data_file="test.json", active=True,
    )
    users_file.write_text(
        json.dumps({"users": [asdict(admin), asdict(supervisor)]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {"data_dir": data_dir, "schools_dir": schools_dir, "output_dir": output_dir,
            "test_file": test_file, "users_file": users_file, "default_json": test_file}


def _login_client(tmp_workspace, username: str, password: str) -> TestClient:
    from timetable_web.app import create_app
    app = create_app()
    ctx = TestClient(app)
    ctx.__enter__()  # trigger lifespan
    r = ctx.post("/login", data={"username": username, "password": password},
                 follow_redirects=False)
    assert r.status_code == 303, f"login failed: {r.status_code} {r.text[:200]}"
    return ctx


@pytest.fixture
def client(tmp_workspace) -> TestClient:
    """مصادَق كمُشرِف — للاختبارات على تبويبات البيانات."""
    c = _login_client(tmp_workspace, SUPERVISOR_USER, SUPERVISOR_PW)
    try:
        yield c
    finally:
        c.__exit__(None, None, None)


@pytest.fixture
def admin_client(tmp_workspace) -> TestClient:
    """مصادَق كمدير — لاختبارات /admin."""
    c = _login_client(tmp_workspace, "admin", "admin")
    try:
        yield c
    finally:
        c.__exit__(None, None, None)


@pytest.fixture
def anon_client(tmp_workspace) -> TestClient:
    """بلا تسجيل دخول — لاختبار middleware."""
    from timetable_web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def store(client):
    """The supervisor's Store — force-instantiated & data-loaded."""
    from timetable_web.state.store import _store_for_supervisor, _stores
    if SUPERVISOR_USER not in _stores:
        _store_for_supervisor(SUPERVISOR_USER, "test.json")
    return _stores[SUPERVISOR_USER]
