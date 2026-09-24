"""تبويب التوليد + مسارات PDF.

الاختبارات السريعة (بلا CP-SAT) تعمل افتراضياً.
اختبار التوليد الكامل ('generate-all') مُعلَّم @pytest.mark.slow ويحتاج مهلة أطول.
"""

from __future__ import annotations

import time

import pytest


def test_index(client):
    r = client.get("/solve")
    assert r.status_code == 200
    assert "توليد البرامج الثلاثة" in r.text


def test_solve_page_shows_time_limit_select(client):
    r = client.get("/solve")
    assert r.status_code == 200
    assert 'name="max_time"' in r.text
    for seconds in ("60", "180", "300", "600", "900"):
        assert f'value="{seconds}"' in r.text


# ---------- التحكم بمهلة الحلّ (max_time) ----------

def test_clean_time_limit_allowlist():
    from timetable_web.routers.solve import DEFAULT_TIME_LIMIT, _clean_time_limit
    assert _clean_time_limit(60) == 60
    assert _clean_time_limit(300) == 300
    assert _clean_time_limit(900) == 900
    assert _clean_time_limit(999999) == DEFAULT_TIME_LIMIT
    assert _clean_time_limit(-5) == DEFAULT_TIME_LIMIT


def test_generate_all_passes_selected_max_time_to_solver(client, store, tmp_workspace, monkeypatch):
    captured = {}

    def fake_solve(data, max_time_in_seconds=300, num_workers=8, progress=None, warm_start=None):
        captured["max_time_in_seconds"] = max_time_in_seconds
        return "OPTIMAL", {}, {}, {}

    monkeypatch.setattr("timetable_web.core.scheduler.solve_timetable", fake_solve)
    monkeypatch.setattr("timetable_web.core.pdf_gen.generate_all_pdfs", lambda *a, **k: {})

    r = client.post("/solve/generate-all", data={"max_time": "60"})
    assert r.status_code == 200
    for _ in range(50):
        if store.solve_status in ("done", "failed"):
            break
        time.sleep(0.1)

    assert store.solve_status == "done", store.solve_message
    assert captured["max_time_in_seconds"] == 60


def test_generate_all_clamps_tampered_max_time(client, store, tmp_workspace, monkeypatch):
    """قيمة خارج القائمة المسموحة (مثلاً مُعدَّلة يدوياً في الطلب) تُرجَع للافتراضي، لا تُمرَّر كما هي."""
    captured = {}

    def fake_solve(data, max_time_in_seconds=300, num_workers=8, progress=None, warm_start=None):
        captured["max_time_in_seconds"] = max_time_in_seconds
        return "OPTIMAL", {}, {}, {}

    monkeypatch.setattr("timetable_web.core.scheduler.solve_timetable", fake_solve)
    monkeypatch.setattr("timetable_web.core.pdf_gen.generate_all_pdfs", lambda *a, **k: {})

    r = client.post("/solve/generate-all", data={"max_time": "999999"})
    assert r.status_code == 200
    for _ in range(50):
        if store.solve_status in ("done", "failed"):
            break
        time.sleep(0.1)

    assert captured["max_time_in_seconds"] == 300


def test_fulfillment_report_passes_selected_max_time(client, store, tmp_workspace, monkeypatch):
    captured = {}

    def fake_gen(data, out_dir, progress=None, warm_start=None, max_time_in_seconds=300):
        captured["max_time_in_seconds"] = max_time_in_seconds
        return "/tmp/fake.pdf", {}

    monkeypatch.setattr("timetable_web.core.pdf_gen.generate_fulfillment_report_pdf", fake_gen)

    r = client.post("/solve/fulfillment-report", data={"max_time": "180"})
    assert r.status_code == 200
    for _ in range(50):
        if store.solve_status in ("done", "failed"):
            break
        time.sleep(0.1)

    assert store.solve_status == "done", store.solve_message
    assert captured["max_time_in_seconds"] == 180


def test_status_initial(client):
    r = client.get("/solve/status")
    assert r.status_code == 200


def test_constraints_report_generates_pdf(client, tmp_workspace):
    r = client.post("/solve/constraints-report")
    assert r.status_code == 200
    # Even with no constraints active, the endpoint returns a Response with error text
    # inside — but the PDF only writes if any constraint is on. So we enable one first.


def test_constraints_report_with_active_constraint(client, tmp_workspace):
    # Enable a default constraint so the report has content
    client.post(
        "/constraints/defaults/max_gap_windows",
        data={"enabled": "on", "max": "1"},
    )
    r = client.post("/solve/constraints-report")
    assert r.status_code == 200
    files = list(tmp_workspace["output_dir"].glob("*.pdf"))
    assert any("تقرير_الشروط" in p.name for p in files), [p.name for p in files]


def test_complexity_report(client, tmp_workspace):
    # Enable a constraint so complexity report has content
    client.post(
        "/constraints/defaults/max_gap_windows",
        data={"enabled": "on", "max": "1"},
    )
    r = client.post("/solve/complexity-report")
    assert r.status_code == 200
    files = list(tmp_workspace["output_dir"].glob("*.pdf"))
    assert any("ترتيب" in p.name for p in files)


def test_download_pdf(client, tmp_workspace):
    # Generate one first
    client.post(
        "/constraints/defaults/max_gap_windows",
        data={"enabled": "on", "max": "1"},
    )
    client.post("/solve/constraints-report")
    files = list(tmp_workspace["output_dir"].glob("*.pdf"))
    assert files, "expected at least one PDF"
    fname = files[0].name
    r = client.get(f"/solve/download/{fname}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_download_traversal_blocked(client):
    r = client.get("/solve/download/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (404, 400)


def test_download_missing_file(client):
    r = client.get("/solve/download/nonexistent.pdf")
    assert r.status_code == 404


@pytest.mark.slow
def test_full_solve_generates_all_pdfs(client, store, tmp_workspace):
    """End-to-end: CP-SAT solve + generate_all_pdfs on the tiny dataset.
    Takes ~5-10 seconds on tiny data (no soft constraints, no big search space)."""
    r = client.post("/solve/generate-all")
    assert r.status_code == 200

    # Poll status until done or failed (max 60s for tiny data)
    for _ in range(60):
        time.sleep(1)
        if store.solve_status in ("done", "failed"):
            break

    assert store.solve_status == "done", f"solve did not finish: {store.solve_message}"
    assert store.generated_files, "no PDFs produced"
    # Sanity-check the expected file names for a full run
    names = list(store.generated_files.values())
    assert any("برنامج_الشعب" in n for n in names)
    assert any("برنامج_الأساتذة" in n for n in names)
    assert any("قائمة_الأساتذة" in n for n in names)
