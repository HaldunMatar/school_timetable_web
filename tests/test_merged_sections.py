"""دمج شعبتين بنفس الأستاذ ونفس الوقت (درس مشترك) - اختبارات pack_subject،
محرك الحل CP-SAT مباشرة، validate_merged_groups، ومسارات /subjects HTTP."""

from __future__ import annotations

import pytest

from timetable_web.core import scheduler


# --------------------------------------------------- pack_subject -----

def _subject_with_merge(sections_count=2):
    return {
        "name": "الرياضيات",
        "category": "تربوية",
        "periods": {"ع1": 4, "ع2": 3},
        "names": ["أحمد", "بشير"],
        "manual_assignments": [],
        "merged_groups": [{"teacher": "أحمد", "track": "ع1", "sections": [1, 2]}],
        "constraints": {
            "max_consecutive_per_day": {"enabled": False, "max": 2},
            "max_daily_per_section": {"enabled": False, "max": 2},
        },
    }


def _data_with_merge():
    return {
        "meta": {
            "days": ["الأحد", "الاثنين"], "periods_per_day": 4,
            "grade_order": ["ع1", "ع2"], "grade_labels": {"ع1": "سابع", "ع2": "ثامن"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 2, "ع2": 1},
        "teachers": ["أحمد", "بشير"],
        "subjects": [_subject_with_merge()],
    }


def test_pack_subject_pins_same_teacher_on_both_merged_sections():
    data = _data_with_merge()
    slots = scheduler.pack_subject(data, data["subjects"][0])
    ahmad = next(s for s in slots if s["name"] == "أحمد")
    claimed_sections = {(a["track"], a["section"]) for a in ahmad["atoms"]}
    assert ("ع1", 1) in claimed_sections
    assert ("ع1", 2) in claimed_sections


def test_pack_subject_shadow_atom_excluded_from_teacher_total():
    data = _data_with_merge()
    slots = scheduler.pack_subject(data, data["subjects"][0])
    ahmad = next(s for s in slots if s["name"] == "أحمد")
    # المدمجة: ع1 شعبة 1+2 (كل منهما 4 حصص) - لكن كلاهما في نفس الوقت، فيجب
    # أن يُحتسب 4 مرة واحدة فقط ضمن "total" (نصاب الأستاذ الفعلي)، وليس 8.
    assert ahmad["total"] == 4


def test_teacher_current_periods_does_not_double_count_merged_pair():
    data = _data_with_merge()
    total = scheduler.teacher_current_periods(data, "أحمد")
    # 4 (ع1، مدموجة - تُحتسب مرة واحدة) + 0 (لا يدرّس ع2 هنا) = 4
    assert total == 4


# --------------------------------------------------- CP-SAT solve ------

def _tiny_merge_solve_instance():
    """يومان × 4 حصص = 8 خانة، صف واحد فيه شعبتان، مادة واحدة يدرّسها أستاذ
    واحد لكلا الشعبتين، مدموجتان معاً - 4 حصص أسبوعياً (نصف السعة، مساحة
    كافية كي لا يُجبَر الحل على توزيع طبيعي بلا خيارات)."""
    return {
        "meta": {
            "days": ["الأحد", "الاثنين"], "periods_per_day": 4,
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 2},
        "teachers": ["معلم1"],
        "subjects": [{
            "name": "مادة1", "category": "تربوية",
            "periods": {"ع1": 4},
            "names": ["معلم1"],
            "manual_assignments": [],
            "merged_groups": [{"teacher": "معلم1", "track": "ع1", "sections": [1, 2]}],
            "constraints": {
                "max_consecutive_per_day": {"enabled": False, "max": 2},
                "max_daily_per_section": {"enabled": False, "max": 2},
            },
        }],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {},
        },
    }


@pytest.mark.slow
def test_solver_forces_identical_schedule_for_merged_sections():
    """الاختبار الحاسم: بدون قيد الدمج (model.Add(x[i,s] == x[j,s]))، لا شيء
    يمنع الحلّ من وضع حصص الشعبة 1 والشعبة 2 في أوقات مختلفة تماماً (كل
    قسم exclusivity له مستقل) رغم اشتراكهما بنفس الأستاذ - فيفشل هذا
    الاختبار لو أُزيلت آلية الربط."""
    data = _tiny_merge_solve_instance()
    status_name, section_sched, _notes, _fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=2,
    )
    assert status_name in ("OPTIMAL", "FEASIBLE")
    sched_a = section_sched["ع1|1"]
    sched_b = section_sched["ع1|2"]
    assert sched_a == sched_b, "الشعبتان المدموجتان يجب أن تحملا نفس الجدول بالضبط في كل خانة"
    occupied = [slot for slot in sched_a if slot is not None]
    assert len(occupied) == 4
    assert all(slot["teacher"] == "معلم1" and slot["subject"] == "مادة1" for slot in occupied)


# --------------------------------------------------- validate_merged_groups

def _valid_merge_data():
    data = _data_with_merge()
    return data


def test_validate_merged_groups_accepts_valid_config():
    data = _valid_merge_data()
    scheduler.validate_merged_groups(data)  # لا يرفع استثناء


def test_validate_merged_groups_rejects_unknown_teacher():
    data = _valid_merge_data()
    data["subjects"][0]["merged_groups"][0]["teacher"] = "غير موجود"
    with pytest.raises(RuntimeError, match="ليس ضمن قائمة أساتذة"):
        scheduler.validate_merged_groups(data)


def test_validate_merged_groups_rejects_unknown_track():
    data = _valid_merge_data()
    data["subjects"][0]["merged_groups"][0]["track"] = "صف_غريب"
    with pytest.raises(RuntimeError, match="غير معروف"):
        scheduler.validate_merged_groups(data)


def test_validate_merged_groups_rejects_wrong_section_count():
    data = _valid_merge_data()
    data["subjects"][0]["merged_groups"][0]["sections"] = [1, 2, 3]
    with pytest.raises(RuntimeError, match="شعبتين مختلفتين بالضبط"):
        scheduler.validate_merged_groups(data)


def test_validate_merged_groups_rejects_section_out_of_range():
    data = _valid_merge_data()
    data["subjects"][0]["merged_groups"][0]["sections"] = [1, 99]
    with pytest.raises(RuntimeError, match="غير موجودة"):
        scheduler.validate_merged_groups(data)


def test_validate_merged_groups_rejects_overlapping_groups():
    data = _valid_merge_data()
    data["teachers"].append("سامي")
    data["subjects"][0]["names"].append("سامي")
    data["subjects"][0]["merged_groups"].append(
        {"teacher": "سامي", "track": "ع1", "sections": [2, 1]}
    )
    with pytest.raises(RuntimeError, match="أكثر من عملية دمج"):
        scheduler.validate_merged_groups(data)


def test_validate_merged_groups_rejects_conflict_with_manual_assignment():
    data = _valid_merge_data()
    data["subjects"][0]["manual_assignments"] = [
        {"teacher": "بشير", "track": "ع1", "sections": [1]}
    ]
    with pytest.raises(RuntimeError, match="إسناد إجباري منفصل"):
        scheduler.validate_merged_groups(data)


# --------------------------------------------------- HTTP router -------

def _bump_ع1_to_2_sections(client):
    r = client.post("/sections/ع1", data={"count": "2"})
    assert r.status_code == 200


def test_add_merge_via_http(client, store):
    _bump_ع1_to_2_sections(client)
    r = client.post(
        "/subjects/0/merge/add",
        data={"teacher": "أحمد", "track": "ع1", "section_a": "1", "section_b": "2"},
    )
    assert r.status_code == 200, r.text
    groups = store.data["subjects"][0]["merged_groups"]
    assert len(groups) == 1
    assert groups[0]["teacher"] == "أحمد"
    assert sorted(groups[0]["sections"]) == [1, 2]


def test_add_merge_rejects_same_section_twice(client):
    _bump_ع1_to_2_sections(client)
    r = client.post(
        "/subjects/0/merge/add",
        data={"teacher": "أحمد", "track": "ع1", "section_a": "1", "section_b": "1"},
    )
    assert r.status_code == 400


def test_add_merge_rejects_teacher_not_in_subject(client):
    _bump_ع1_to_2_sections(client)
    r = client.post(
        "/subjects/0/merge/add",
        data={"teacher": "غير_موجود", "track": "ع1", "section_a": "1", "section_b": "2"},
    )
    assert r.status_code == 400


def test_add_merge_rejects_duplicate_section_claim(client):
    _bump_ع1_to_2_sections(client)
    client.post("/subjects/0/manual/add", data={"teacher": "أحمد", "track": "ع1", "section_csv": "1"})
    r = client.post(
        "/subjects/0/merge/add",
        data={"teacher": "أحمد", "track": "ع1", "section_a": "1", "section_b": "2"},
    )
    assert r.status_code == 400


def test_remove_merge_via_http(client, store):
    _bump_ع1_to_2_sections(client)
    client.post(
        "/subjects/0/merge/add",
        data={"teacher": "أحمد", "track": "ع1", "section_a": "1", "section_b": "2"},
    )
    r = client.post("/subjects/0/merge/0/delete")
    assert r.status_code == 200
    assert store.data["subjects"][0]["merged_groups"] == []


def test_removing_teacher_from_subject_drops_their_merge_group(client, store):
    _bump_ع1_to_2_sections(client)
    client.post(
        "/subjects/0/merge/add",
        data={"teacher": "أحمد", "track": "ع1", "section_a": "1", "section_b": "2"},
    )
    r = client.post("/subjects/0/name/remove", data={"name": "أحمد"})
    assert r.status_code == 200
    assert store.data["subjects"][0]["merged_groups"] == []


def test_reducing_section_count_drops_stale_merge_group(client, store):
    _bump_ع1_to_2_sections(client)
    client.post(
        "/subjects/0/merge/add",
        data={"teacher": "أحمد", "track": "ع1", "section_a": "1", "section_b": "2"},
    )
    r = client.post("/sections/ع1", data={"count": "1"})
    assert r.status_code == 200
    assert store.data["subjects"][0]["merged_groups"] == []


def test_dashboard_warns_on_invalid_merged_group(client, store):
    _bump_ع1_to_2_sections(client)
    client.post(
        "/subjects/0/merge/add",
        data={"teacher": "أحمد", "track": "ع1", "section_a": "1", "section_b": "2"},
    )
    # نُفسد الإعداد يدوياً (تعارض مع أستاذ غير موجود في المادة)
    store.data["subjects"][0]["names"].remove("أحمد")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "دمج شعب غير صالح" in r.text
