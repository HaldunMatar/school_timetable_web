"""شريط عدد الشعب لكل صف."""

from __future__ import annotations


def test_update_section_count(client, store):
    r = client.post("/sections/ع1", data={"count": "5"})
    assert r.status_code == 200
    assert store.data["sections"]["ع1"] == 5
    assert store.dirty


def test_update_unknown_grade(client):
    r = client.post("/sections/UNKNOWN", data={"count": "3"})
    assert r.status_code == 404


def test_update_negative_rejected(client):
    r = client.post("/sections/ع1", data={"count": "-1"})
    assert r.status_code == 422  # Form validator (ge=0)


# ---------- تنظيف تلقائي عند تقليل عدد الشعب ----------

def test_reducing_sections_prunes_manual_assignments(client, store):
    # تحضير: ابدأ من 3 شعب في ع1، وأضف إسناد إجباري لشعبتين 2 و 3
    client.post("/sections/ع1", data={"count": "3"})
    client.post(
        "/subjects/0/manual/add",
        data={"teacher": "أحمد", "track": "ع1", "section_csv": "2,3"},
    )
    assert store.data["subjects"][0]["manual_assignments"][0]["sections"] == [2, 3]

    # نُقلّص ع1 إلى شعبة واحدة → شعبتَي 2 و 3 مُلغاتان
    r = client.post("/sections/ع1", data={"count": "1"})
    assert r.status_code == 200
    assert "تنظيف" in r.text  # مؤشر بصري للمستخدم

    # الإسناد يجب أن يُحذف (الشعبتان كلاهما مُلغاتان)
    manual = store.data["subjects"][0]["manual_assignments"]
    assert manual == []


def test_reducing_sections_partial_prune(client, store):
    # 3 شعب، إسناد لشعب [1, 2, 3]
    client.post("/sections/ع1", data={"count": "3"})
    client.post(
        "/subjects/0/manual/add",
        data={"teacher": "أحمد", "track": "ع1", "section_csv": "1,2,3"},
    )

    # نُقلّص إلى 2 → الشعبة 3 تُحذف فقط، الإسناد يبقى مع [1, 2]
    r = client.post("/sections/ع1", data={"count": "2"})
    assert r.status_code == 200

    manual = store.data["subjects"][0]["manual_assignments"]
    assert len(manual) == 1
    assert manual[0]["sections"] == [1, 2]


def test_setting_sections_to_zero_removes_all_assignments_for_grade(client, store):
    # 3 شعب مع إسنادات في ع1 وأيضاً ع2
    client.post("/sections/ع1", data={"count": "3"})
    client.post("/sections/ع2", data={"count": "2"})
    client.post("/subjects/0/manual/add",
                data={"teacher": "أحمد", "track": "ع1", "section_csv": "1,2"})
    client.post("/subjects/0/manual/add",
                data={"teacher": "أحمد", "track": "ع2", "section_csv": "1"})
    assert len(store.data["subjects"][0]["manual_assignments"]) == 2

    # نلغي ع1 كلياً
    r = client.post("/sections/ع1", data={"count": "0"})
    assert r.status_code == 200
    assert "تنظيف" in r.text

    # ع1 كل إسناداته مُزالة، لكن ع2 سليم
    manual = store.data["subjects"][0]["manual_assignments"]
    assert len(manual) == 1
    assert manual[0]["track"] == "ع2"


def test_increasing_sections_never_touches_assignments(client, store):
    client.post("/sections/ع1", data={"count": "2"})
    client.post("/subjects/0/manual/add",
                data={"teacher": "أحمد", "track": "ع1", "section_csv": "1,2"})
    assignments_before = [dict(m) for m in store.data["subjects"][0]["manual_assignments"]]

    # زيادة إلى 5 — لا تنظيف
    r = client.post("/sections/ع1", data={"count": "5"})
    assert r.status_code == 200
    assert "تنظيف" not in r.text  # لا تنظيف عند الزيادة

    assert store.data["subjects"][0]["manual_assignments"] == assignments_before


def test_cleanup_logged(client, store):
    client.post("/sections/ع1", data={"count": "3"})
    client.post("/subjects/0/manual/add",
                data={"teacher": "أحمد", "track": "ع1", "section_csv": "2,3"})
    log_before = len(store.log_entries)

    client.post("/sections/ع1", data={"count": "1"})

    log_after = len(store.log_entries)
    # عدة إدخالات جديدة: التنظيف + التغيير النهائي
    assert log_after > log_before
    # نص التنظيف موجود
    assert any("أُلغي إسناد كامل" in msg or "أُزيلت الشعب" in msg
               for _, msg in store.log_entries[log_before:])
