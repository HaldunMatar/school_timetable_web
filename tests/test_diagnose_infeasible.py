"""رسالة INFEASIBLE التشخيصية: تسمّي الأساتذة/المواد/الصفوف المتعارضة وتقترح الحل."""

from __future__ import annotations

import pytest

from timetable_web.core import scheduler

from ._gap_contest import _subj


def _inst(subjects, per_teacher, ppd=5, teachers=("A", "B"), days=("يوم1",), sections=1):
    return {
        "meta": {"days": list(days), "periods_per_day": ppd, "grade_order": ["ع1"],
                 "grade_labels": {"ع1": "سابع"}, "nisab_reference": 8},
        "sections": {"ع1": sections}, "teachers": list(teachers),
        "subjects": subjects,
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": per_teacher,
        },
    }


def _fixed(periods):
    f = _subj("ثابتة", len(periods), None)
    f["fixed_no_teacher_slots"] = [
        {"track": "ع1", "sections": "all", "period_index": i} for i in periods]
    return f


def _msg(data):
    with pytest.raises(RuntimeError) as e:
        scheduler.solve_timetable(data, max_time_in_seconds=10, num_workers=2)
    return str(e.value)


@pytest.mark.slow
def test_names_the_conflicting_teacher():
    # A مجبَر على الحصتين 0 و4 (الثابتة تشغل 1..3) ويطلب max_consecutive_empty=1.
    data = _inst(
        [_subj("م1", 2, "A"), _fixed([2, 3, 4])],
        {"A": {"max_consecutive_empty": {"enabled": True, "max": 1}}},
        teachers=("A",),
    )
    m = _msg(data)
    assert "الأستاذ A" in m and "الحد الأقصى لعدد الحصص الفارغة المتتالية" in m
    assert "الحل" in m


@pytest.mark.slow
def test_names_the_subject_constraint():
    s1 = _subj("م1", 2, "A")
    s1["constraints"]["max_daily_per_section"] = {"enabled": True, "max": 1}
    m = _msg(_inst([s1], {}, ppd=3, teachers=("A",)))
    assert "قيود المواد" in m and "م1" in m


def test_overfull_grade_is_reported():
    data = _inst([_subj("م1", 2, "A"), _subj("م2", 2, "B")], {}, ppd=3)  # 4 > 3 خانات
    m = _msg(data)
    assert "أكبر من حصص الأسبوع" in m and "سابع" in m


@pytest.mark.slow
def test_no_recursion_and_plain_message_when_no_constraints_are_to_blame():
    data = _inst([_subj("م1", 2, "A")], {}, ppd=3, teachers=("A",))
    data["subjects"][0]["manual_assignments"] = []
    m = _msg(_inst([_subj("م1", 4, "A")], {}, ppd=3, teachers=("A",)))
    assert "INFEASIBLE" in m or "يستحيل" in m
