"""تبويب قائمة الأساتذة."""

from __future__ import annotations


def test_add_teacher(client, store):
    r = client.post("/teachers/add", data={"name": "خالد"})
    assert r.status_code == 200
    assert "خالد" in store.data["teachers"]
    assert store.dirty


def test_add_empty_name_fails(client):
    r = client.post("/teachers/add", data={"name": "   "})
    assert r.status_code == 400


def test_add_duplicate_fails(client):
    r = client.post("/teachers/add", data={"name": "أحمد"})  # already exists
    assert r.status_code == 400
    assert "موجود" in r.text or "already" in r.text.lower()


def test_rename_teacher_updates_subjects(client, store):
    r = client.post("/teachers/rename", data={"old_name": "أحمد", "new_name": "أحمد المُعدَّل"})
    assert r.status_code == 200
    assert "أحمد" not in store.data["teachers"]
    assert "أحمد المُعدَّل" in store.data["teachers"]
    # scheduler.rename_teacher_in_roster should propagate to subject names too
    for subj in store.data["subjects"]:
        assert "أحمد" not in subj["names"]


def test_rename_empty_fails(client):
    r = client.post("/teachers/rename", data={"old_name": "أحمد", "new_name": ""})
    # Either FastAPI's Form validator (422) or our explicit check (400) can win.
    assert r.status_code in (400, 422)


def test_delete_assigned_teacher_forbidden(client, store):
    # أحمد is assigned to الرياضيات — deletion must be rejected
    r = client.post("/teachers/delete", data={"name": "أحمد"})
    assert r.status_code == 409
    assert "أحمد" in store.data["teachers"]


def test_delete_unassigned_teacher_ok(client, store):
    # add then delete a new teacher not tied to any subject
    client.post("/teachers/add", data={"name": "زيد"})
    r = client.post("/teachers/delete", data={"name": "زيد"})
    assert r.status_code == 200
    assert "زيد" not in store.data["teachers"]


def test_rows_partial(client):
    r = client.get("/teachers/rows")
    assert r.status_code == 200
    assert "أحمد" in r.text
    assert "بشير" in r.text
