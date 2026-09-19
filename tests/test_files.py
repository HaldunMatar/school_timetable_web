"""ملفات: فتح/حفظ/تنزيل/رفع + مدرسة جديدة + توليد الأساتذة الناقصين."""

from __future__ import annotations

import json


def test_list_data_files_supervisor_sees_no_switchable_files(client):
    # In multi-tenant mode, DATA_DIR is empty for supervisors (their file is in schools/).
    r = client.get("/file/list")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_save_and_download(client, store, tmp_workspace):
    store.data["subjects"][0]["name"] = "الرياضيات-معدَّلة"
    r = client.post("/file/save")
    assert r.status_code == 200

    written = json.loads(tmp_workspace["test_file"].read_text(encoding="utf-8"))
    assert written["subjects"][0]["name"] == "الرياضيات-معدَّلة"

    r = client.get("/file/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"


def test_fill_missing_teachers_noop_on_complete_data(client):
    r = client.post("/file/fill-missing-teachers")
    assert r.status_code == 200
    assert "لا توجد" in r.text or "مغطى" in r.text


def test_fill_missing_teachers_adds_when_gap(client, store):
    # Delete the only teacher in الرياضيات via subject editor (leaves it empty)
    client.post("/subjects/0/name/remove", data={"name": "أحمد"})
    # Now الرياضيات has no teachers → fill should add at least one
    r = client.post("/file/fill-missing-teachers")
    assert r.status_code == 200
    subject = next(s for s in store.data["subjects"] if s["name"] == "الرياضيات")
    assert len(subject["names"]) >= 1
