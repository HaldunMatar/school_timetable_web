"""Shared pytest fixtures — isolated tmp workspace + fresh store per test."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Sample data — deliberately tiny so tests are fast and CP-SAT solves in <5s.
# 2 subjects × 2 teachers × 2 grades × 1 section × 3 days × 4 periods.
# ---------------------------------------------------------------------------

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
            {
                "name": "الرياضيات",
                "category": "تربوية",
                "periods": {"ع1": 3, "ع2": 3},
                "names": ["أحمد"],
                "manual_assignments": [],
                "constraints": {
                    "max_consecutive_per_day": {"enabled": False, "max": 2},
                    "max_daily_per_section": {"enabled": False, "max": 2},
                },
            },
            {
                "name": "اللغة",
                "category": "تربوية",
                "periods": {"ع1": 3, "ع2": 3},
                "names": ["بشير"],
                "manual_assignments": [],
                "constraints": {
                    "max_consecutive_per_day": {"enabled": False, "max": 2},
                    "max_daily_per_section": {"enabled": False, "max": 2},
                },
            },
        ],
        "scheduling_constraints": {
            "defaults": {
                "empty_periods": {
                    "enabled": False,
                    "start": {"enabled": False, "count": 1},
                    "end": {"enabled": False, "count": 1},
                    "days_mode": "all",
                    "days": [],
                },
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


@pytest.fixture
def tmp_workspace(tmp_path: Path, monkeypatch, tiny_data) -> dict[str, Path]:
    """Redirect DATA_DIR / OUTPUT_DIR / DEFAULT_JSON to tmp_path, write tiny data,
    and swap in a fresh Store singleton. Every test starts clean."""
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    output_dir.mkdir()

    fake_default = data_dir / "test.json"
    fake_default.write_text(json.dumps(tiny_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Patch state.store — the source of truth
    from timetable_web.state import store as store_mod
    monkeypatch.setattr(store_mod, "DATA_DIR", data_dir)
    monkeypatch.setattr(store_mod, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(store_mod, "DEFAULT_JSON", fake_default)
    monkeypatch.setattr(store_mod, "_store", store_mod.Store())

    # Patch the from-imports done at module load in the routers/app
    from timetable_web import app as app_mod
    monkeypatch.setattr(app_mod, "DEFAULT_JSON", fake_default)

    from timetable_web.routers import files as files_mod
    monkeypatch.setattr(files_mod, "DATA_DIR", data_dir)
    monkeypatch.setattr(files_mod, "DEFAULT_JSON", fake_default)

    from timetable_web.routers import solve as solve_mod
    monkeypatch.setattr(solve_mod, "OUTPUT_DIR", output_dir)

    return {"data_dir": data_dir, "output_dir": output_dir, "default_json": fake_default}


@pytest.fixture
def client(tmp_workspace) -> TestClient:
    """Fresh TestClient. Lifespan loads the tiny data automatically."""
    from timetable_web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def store():
    """Direct access to the fresh Store instance (post-patch)."""
    from timetable_web.state.store import get_store
    return get_store()
