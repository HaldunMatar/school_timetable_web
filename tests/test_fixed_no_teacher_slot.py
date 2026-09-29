"""حصة ثابتة بلا أستاذ (fixed_no_teacher_slots) - مادة معينة بلا أستاذ في
رقم حصة ثابت (أي يوم يختاره الحل)، لشعبة معينة أو لكل الشعب. تُحسَب ضمن
نفس حصص المادة الأسبوعية المدخلة، ولا تدخل نصاب أي أستاذ."""

from __future__ import annotations

import pytest

from timetable_web.core import scheduler


def _subject(name, periods_track_value, names, fixed_rules=None):
    return {
        "name": name, "category": "تربوية",
        "periods": {"ع1": periods_track_value},
        "names": names, "manual_assignments": [],
        "merged_groups": [],
        "fixed_no_teacher_slots": fixed_rules or [],
        "constraints": {
            "max_consecutive_per_day": {"enabled": False, "max": 2},
            "max_daily_per_section": {"enabled": False, "max": 2},
        },
    }


def _instance(fixed_rules, sports_periods=1, math_periods=7, sections=1):
    """يومان × 4 حصص = 8 خانة/شعبة. "رياضة" بلا أستاذ إطلاقاً، حصة واحدة
    ثابتة بالحصة الرابعة (آخر حصة) - أي يوم. "الرياضيات" تملأ الباقي."""
    return {
        "meta": {
            "days": ["يوم1", "يوم2"], "periods_per_day": 4,
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": sections},
        "teachers": ["أحمد"],
        "subjects": [
            _subject("رياضة", sports_periods, [], fixed_rules),
            _subject("الرياضيات", math_periods, ["أحمد"]),
        ],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {},
        },
    }


def _rule(sections="all", period_index=4):
    return {"track": "ع1", "sections": sections, "period_index": period_index}


# ------------------------------------------------- pack_subject / totals

def test_pack_subject_excludes_fixed_no_teacher_periods_from_atoms():
    data = _instance([_rule()])
    math_subj = data["subjects"][1]
    slots = scheduler.pack_subject(data, math_subj)
    ahmad = next(s for s in slots if s["name"] == "أحمد")
    assert ahmad["total"] == 7  # 8 خانات - 1 حصة رياضة ثابتة = 7 للرياضيات


def test_pack_subject_returns_nothing_for_fully_teacherless_subject():
    data = _instance([_rule()], sports_periods=1)
    sports_subj = data["subjects"][0]
    assert scheduler.pack_subject(data, sports_subj) == []  # names=[] أصلاً


def test_subject_teacher_required_periods_excludes_fixed_slot():
    data = _instance([_rule()])
    sports_subj = data["subjects"][0]
    assert scheduler.subject_teacher_required_periods(data, sports_subj) == 0


def test_ensure_min_teachers_does_not_invent_a_teacher_for_teacherless_subject():
    data = _instance([_rule()])
    scheduler.ensure_min_teachers(data)
    sports_subj = data["subjects"][0]
    assert sports_subj["names"] == []  # لم يُضَف أي أستاذ افتراضي


# ------------------------------------------------- validate_fixed_no_teacher_slots

def test_validate_accepts_valid_rule():
    data = _instance([_rule()])
    scheduler.validate_fixed_no_teacher_slots(data)  # لا يرفع استثناء


def test_validate_rejects_unknown_track():
    data = _instance([{"track": "غير_موجود", "sections": "all", "period_index": 4}])
    with pytest.raises(RuntimeError, match="غير معروف"):
        scheduler.validate_fixed_no_teacher_slots(data)


def test_validate_rejects_period_index_out_of_range():
    data = _instance([_rule(period_index=99)])
    with pytest.raises(RuntimeError, match="رقم الحصة"):
        scheduler.validate_fixed_no_teacher_slots(data)


def test_validate_rejects_section_out_of_range():
    data = _instance([_rule(sections=[99])])
    with pytest.raises(RuntimeError, match="غير موجودة"):
        scheduler.validate_fixed_no_teacher_slots(data)


def test_validate_rejects_exceeding_subject_periods():
    # "رياضة" حصة واحدة فقط أسبوعياً، لكن قاعدتان ثابتتان = حصتان مطلوبتان
    data = _instance([_rule(period_index=1), _rule(period_index=4)], sports_periods=1)
    with pytest.raises(RuntimeError, match="أكبر من عدد حصص"):
        scheduler.validate_fixed_no_teacher_slots(data)


def test_validate_rejects_empty_sections_list():
    data = _instance([_rule(sections=[])])
    with pytest.raises(RuntimeError, match="شعبة واحدة"):
        scheduler.validate_fixed_no_teacher_slots(data)


# ------------------------------------------------- CP-SAT solve ---------

@pytest.mark.slow
def test_solver_always_places_fixed_slot_at_the_right_period_index():
    """الاختبار الحاسم: بلا قيد تثبيت رقم الحصة، لا شيء يمنع الحلّ من وضع
    "رياضة" في أي من الحصص الأربع بأي يوم (الشعبة معبأة بالكامل بينها
    وبين "الرياضيات" بغضّ النظر عن الترتيب) - فيفشل هذا الاختبار لو
    أُزيلت آلية التثبيت."""
    data = _instance([_rule(period_index=4)])
    _status, section_sched, _notes, _fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=2,
    )
    sched = section_sched["ع1|1"]
    sports_slots = [i for i, c in enumerate(sched) if c and c["subject"] == "رياضة"]
    assert len(sports_slots) == 1
    slot = sports_slots[0]
    assert slot % 4 == 3, f"يجب أن تقع (الحصة الرابعة، فهرس 3) - وقعت في الفهرس {slot}"
    assert sched[slot]["teacher"] is None


@pytest.mark.slow
def test_solver_respects_per_section_independence_for_all_sections():
    """"لجميع الشعب" - كل شعبة تحصل على الحصة الثابتة بشكل مستقل (قد
    تختلف باليوم عن الأخرى)، وليست حصة مشتركة بالضرورة."""
    data = _instance([_rule(sections="all", period_index=4)], sections=2)
    _status, section_sched, _notes, _fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=2,
    )
    for sec in (1, 2):
        sched = section_sched[f"ع1|{sec}"]
        sports_slots = [i for i, c in enumerate(sched) if c and c["subject"] == "رياضة"]
        assert len(sports_slots) == 1
        assert sports_slots[0] % 4 == 3


def test_no_fixed_no_teacher_slots_field_is_a_pure_noop():
    data = _instance([])
    for subj in data["subjects"]:
        subj.pop("fixed_no_teacher_slots", None)
    scheduler.validate_fixed_no_teacher_slots(data)  # لا يرفع استثناء


# ------------------------------------------------- HTTP router ---------

def test_add_fixed_slot_via_http_all_sections(client, store):
    r = client.post(
        "/subjects/0/fixed-slot/add",
        data={"track": "ع1", "period_index": "4", "all_sections": "on"},
    )
    assert r.status_code == 200, r.text
    rules = store.data["subjects"][0]["fixed_no_teacher_slots"]
    assert len(rules) == 1
    assert rules[0] == {"track": "ع1", "period_index": 4, "sections": "all"}


def test_add_fixed_slot_via_http_specific_sections(client, store):
    r = client.post(
        "/subjects/0/fixed-slot/add",
        data={"track": "ع1", "period_index": "1", "sections": ["1"]},
    )
    assert r.status_code == 200, r.text
    rules = store.data["subjects"][0]["fixed_no_teacher_slots"]
    assert rules[0]["sections"] == [1]


def test_add_fixed_slot_rejects_unknown_track(client):
    r = client.post(
        "/subjects/0/fixed-slot/add",
        data={"track": "غير_موجود", "period_index": "1", "all_sections": "on"},
    )
    assert r.status_code == 400


def test_add_fixed_slot_rejects_period_index_out_of_range(client):
    r = client.post(
        "/subjects/0/fixed-slot/add",
        data={"track": "ع1", "period_index": "99", "all_sections": "on"},
    )
    assert r.status_code == 400


def test_add_fixed_slot_rolls_back_on_validation_failure(client, store):
    """طلب فاشل (تجاوز عدد حصص المادة) يجب ألا يترك أي أثر جزئي محفوظ."""
    # ع1 عند tiny_data لديها 3 حصص فقط لـ"الرياضيات" (subjects[0]) - نطلب 4 قواعد
    for p in range(1, 4):
        r = client.post(
            "/subjects/0/fixed-slot/add",
            data={"track": "ع1", "period_index": str(p), "all_sections": "on"},
        )
        assert r.status_code == 200, r.text
    r = client.post(
        "/subjects/0/fixed-slot/add",
        data={"track": "ع1", "period_index": "4", "all_sections": "on"},
    )
    assert r.status_code == 400
    assert len(store.data["subjects"][0]["fixed_no_teacher_slots"]) == 3  # لم يُضَف الرابع


def test_remove_fixed_slot_via_http(client, store):
    client.post(
        "/subjects/0/fixed-slot/add",
        data={"track": "ع1", "period_index": "4", "all_sections": "on"},
    )
    r = client.post("/subjects/0/fixed-slot/0/delete")
    assert r.status_code == 200
    assert store.data["subjects"][0]["fixed_no_teacher_slots"] == []


def test_remove_fixed_slot_missing_index_404(client):
    r = client.post("/subjects/0/fixed-slot/0/delete")
    assert r.status_code == 404


def test_subject_editor_page_shows_fixed_slot_section(client):
    r = client.get("/subjects/0/editor")
    assert r.status_code == 200
    assert "حصة ثابتة بلا أستاذ" in r.text
    assert 'name="period_index"' in r.text
