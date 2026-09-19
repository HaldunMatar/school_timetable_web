"""ملفات: فتح/حفظ/تنزيل/رفع + مدرسة جديدة + توليد الأساتذة الناقصين."""

from __future__ import annotations

import json


def test_list_data_files(client):
    r = client.get("/file/list")
    assert r.status_code == 200
    assert "test.json" in r.json()


def test_open_existing(client, store):
    r = client.post("/file/open", data={"name": "test.json"}, follow_redirects=False)
    assert r.status_code == 303  # redirect after
    assert store.current_path.name == "test.json"


def test_open_missing(client):
    r = client.post("/file/open", data={"name": "nowhere.json"}, follow_redirects=False)
    assert r.status_code == 404


def test_save_and_download(client, store, tmp_workspace):
    # mutate then save
    store.data["subjects"][0]["name"] = "الرياضيات-معدَّلة"
    r = client.post("/file/save")
    assert r.status_code == 200

    written = json.loads(tmp_workspace["default_json"].read_text(encoding="utf-8"))
    assert written["subjects"][0]["name"] == "الرياضيات-معدَّلة"

    # download returns JSON with correct content type
    r = client.get("/file/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"


def test_upload_json(client, store, tiny_data, tmp_workspace):
    payload = json.dumps({**tiny_data, "sections": {"ع1": 5, "ع2": 3}}, ensure_ascii=False)
    r = client.post(
        "/file/upload",
        files={"file": ("uploaded.json", payload.encode("utf-8"), "application/json")},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert store.data["sections"]["ع1"] == 5
    assert (tmp_workspace["data_dir"] / "uploaded.json").exists()


def test_upload_invalid_json(client):
    r = client.post(
        "/file/upload",
        files={"file": ("bad.json", b"not-json", "application/json")},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_new_school(client, tmp_workspace, store):
    r = client.post(
        "/file/new",
        data={
            "filename": "brand_new",
            "periods_per_day": "5",
            "nisab_reference": "18",
            "day_الأحد": "on",
            "day_الاثنين": "on",
            "day_الثلاثاء": "on",
            "day_الأربعاء": "on",
            "day_الخميس": "on",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    new_file = tmp_workspace["data_dir"] / "brand_new.json"
    assert new_file.exists()
    assert store.data["meta"]["periods_per_day"] == 5
    assert len(store.data["meta"]["days"]) == 5


def test_new_school_no_days_fails(client):
    r = client.post(
        "/file/new",
        data={"filename": "x", "periods_per_day": "5", "nisab_reference": "18"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_new_school_duplicate_filename(client, tmp_workspace):
    r = client.post(
        "/file/new",
        data={
            "filename": "test",  # tmp_workspace already created data/test.json
            "periods_per_day": "5",
            "nisab_reference": "18",
            "day_الأحد": "on",
        },
        follow_redirects=False,
    )
    assert r.status_code == 409


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
