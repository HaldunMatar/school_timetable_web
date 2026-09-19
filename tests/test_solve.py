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
