"""تبويب البيانات — مواد + مصفوفة حصص + إسنادات + قيود مادة."""

from __future__ import annotations


def test_new_subject(client, store):
    r = client.post("/subjects/new", data={"name": "الفيزياء"})
    assert r.status_code == 200
    names = [s["name"] for s in store.data["subjects"]]
    assert "الفيزياء" in names


def test_new_subject_duplicate_fails(client):
    r = client.post("/subjects/new", data={"name": "الرياضيات"})  # already exists
    assert r.status_code == 400


def test_delete_subject(client, store):
    before = len(store.data["subjects"])
    r = client.post("/subjects/1/delete")
    assert r.status_code == 200
    assert len(store.data["subjects"]) == before - 1


def test_update_basic(client, store):
    r = client.post("/subjects/0/basic", data={"name": "الرياضيات المتقدمة", "category": "شرعية"})
    assert r.status_code == 200
    assert store.data["subjects"][0]["name"] == "الرياضيات المتقدمة"
    assert store.data["subjects"][0]["category"] == "شرعية"


def test_update_basic_invalid_category(client):
    r = client.post("/subjects/0/basic", data={"name": "X", "category": "unknown"})
    assert r.status_code == 400


def test_update_period(client, store):
    r = client.post("/subjects/0/period/ع1", data={"count": "5"})
    assert r.status_code == 200
    assert store.data["subjects"][0]["periods"]["ع1"] == 5


def test_update_period_unknown_grade(client):
    r = client.post("/subjects/0/period/UNKNOWN", data={"count": "3"})
    assert r.status_code == 404


def test_add_name_ok(client, store):
    r = client.post("/subjects/0/name/add", data={"name": "بشير"})
    assert r.status_code == 200
    assert "بشير" in store.data["subjects"][0]["names"]


def test_add_name_not_in_roster_fails(client):
    r = client.post("/subjects/0/name/add", data={"name": "لا_يوجد"})
    assert r.status_code == 400


def test_add_name_duplicate_fails(client):
    # أحمد already in subject 0
    r = client.post("/subjects/0/name/add", data={"name": "أحمد"})
    assert r.status_code == 400


def test_add_name_refreshes_manual_and_merge_teacher_dropdowns(client):
    """انحدار: /name/add كان يُعيد رسم بطاقة الأساتذة فقط، فتبقى قائمتا
    "الأستاذ" في نموذجَي الإسناد الإجباري والدمج (المبنيتان من نفس
    subj.names) بلا الاسم المُضاف حتى تحديث كامل للصفحة - فارغتين بالكامل
    لو كان هذا أول أستاذ للمادة."""
    r = client.post("/subjects/0/name/add", data={"name": "بشير"})
    assert r.status_code == 200
    assert r.text.count('value="بشير"') >= 2


def test_remove_name(client, store):
    r = client.post("/subjects/0/name/remove", data={"name": "أحمد"})
    assert r.status_code == 200
    assert "أحمد" not in store.data["subjects"][0]["names"]


def test_add_manual_assignment(client, store):
    r = client.post(
        "/subjects/0/manual/add",
        data={"teacher": "أحمد", "track": "ع1", "sections": ["1"]},
    )
    assert r.status_code == 200
    mans = store.data["subjects"][0]["manual_assignments"]
    assert any(m["teacher"] == "أحمد" and m["track"] == "ع1" and 1 in m["sections"] for m in mans)


def test_add_manual_bad_teacher(client):
    r = client.post(
        "/subjects/0/manual/add",
        data={"teacher": "بشير", "track": "ع1", "sections": ["1"]},  # بشير not in subject 0
    )
    assert r.status_code == 400


def test_add_manual_section_out_of_range(client):
    r = client.post(
        "/subjects/0/manual/add",
        data={"teacher": "أحمد", "track": "ع1", "sections": ["99"]},
    )
    assert r.status_code == 400


def test_manual_conflict_between_teachers(client):
    # Add بشير to subject 0 so both teach it
    client.post("/subjects/0/name/add", data={"name": "بشير"})
    client.post(
        "/subjects/0/manual/add",
        data={"teacher": "أحمد", "track": "ع1", "sections": ["1"]},
    )
    r = client.post(
        "/subjects/0/manual/add",
        data={"teacher": "بشير", "track": "ع1", "sections": ["1"]},  # same section
    )
    assert r.status_code == 400
    assert "أحمد" in r.text or "مُسنَدة" in r.text


def test_remove_manual(client, store):
    client.post(
        "/subjects/0/manual/add",
        data={"teacher": "أحمد", "track": "ع1", "sections": ["1"]},
    )
    r = client.post("/subjects/0/manual/0/delete")
    assert r.status_code == 200
    assert len(store.data["subjects"][0]["manual_assignments"]) == 0


# ---------- تعديل سطري لإسناد إجباري قائم (بدل حذف وإعادة إضافة) ----------

def test_edit_manual_form_prefills_current_values(client):
    client.post("/sections/ع1", data={"count": "2"})
    client.post("/subjects/0/manual/add", data={"teacher": "أحمد", "track": "ع1", "sections": ["1", "2"]})
    r = client.get("/subjects/0/manual/0/edit")
    assert r.status_code == 200
    assert 'value="أحمد" selected' in r.text
    assert 'value="ع1"' in r.text and "selected" in r.text


def test_update_manual_changes_sections(client, store):
    client.post("/sections/ع1", data={"count": "4"})
    client.post("/subjects/0/manual/add", data={"teacher": "أحمد", "track": "ع1", "sections": ["1"]})
    r = client.post(
        "/subjects/0/manual/0/update",
        data={"teacher": "أحمد", "track": "ع1", "sections": ["3", "4"]},
    )
    assert r.status_code == 200, r.text
    row = store.data["subjects"][0]["manual_assignments"][0]
    assert row["sections"] == [3, 4]


def test_update_manual_does_not_conflict_with_its_own_previous_value(client, store):
    """تحديث صف بدون تغيير الشعب فعلياً يجب ألا يُرفض كتعارض مع نفسه."""
    client.post("/subjects/0/manual/add", data={"teacher": "أحمد", "track": "ع1", "sections": ["1"]})
    r = client.post(
        "/subjects/0/manual/0/update",
        data={"teacher": "أحمد", "track": "ع1", "sections": ["1"]},
    )
    assert r.status_code == 200, r.text


def test_update_manual_still_rejects_conflict_with_other_row(client):
    client.post("/sections/ع1", data={"count": "2"})
    client.post("/subjects/0/name/add", data={"name": "بشير"})
    client.post("/subjects/0/manual/add", data={"teacher": "أحمد", "track": "ع1", "sections": ["1"]})
    client.post("/subjects/0/manual/add", data={"teacher": "بشير", "track": "ع1", "sections": ["2"]})
    r = client.post(
        "/subjects/0/manual/1/update",
        data={"teacher": "بشير", "track": "ع1", "sections": ["1"]},  # already claimed by أحمد
    )
    assert r.status_code == 400


def test_manual_list_partial_for_cancel_button(client):
    r = client.get("/subjects/0/manual-list")
    assert r.status_code == 200
    assert 'id="manual-list"' in r.text


def test_update_subject_constraint_hard(client, store):
    r = client.post(
        "/subjects/0/constraint/max_consecutive_per_day",
        data={"enabled": "on", "max_value": "3"},
    )
    assert r.status_code == 200
    c = store.data["subjects"][0]["constraints"]["max_consecutive_per_day"]
    assert c["enabled"] is True
    assert c["max"] == 3


def test_update_subject_constraint_disabled(client, store):
    r = client.post(
        "/subjects/0/constraint/max_daily_per_section",
        data={"max_value": "4"},  # no enabled flag → treated as disabled
    )
    assert r.status_code == 200
    c = store.data["subjects"][0]["constraints"]["max_daily_per_section"]
    assert c["enabled"] is False
    assert c["max"] == 4


def test_missing_subject_returns_404(client):
    r = client.get("/subjects/99/editor")
    assert r.status_code == 404
