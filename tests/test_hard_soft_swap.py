"""تبديل الصلابة: "تفريغ حصص بداية/نهاية اليوم" صلب، و"حد نوافذ الفراغ" ليّن."""

from __future__ import annotations

import pytest

from timetable_web.core import scheduler

from ._gap_contest import _subj, gap_contest


def _ep(start=0, end=0):
    return {"enabled": True,
            "start": {"enabled": bool(start), "count": start or 1},
            "end": {"enabled": bool(end), "count": end or 1},
            "days_mode": "all", "days": [], "per_day": {}}


def _single(periods_needed, per_teacher, ppd=3):
    return {
        "meta": {"days": ["يوم1"], "periods_per_day": ppd, "grade_order": ["ع1"],
                 "grade_labels": {"ع1": "سابع"}, "nisab_reference": 8},
        "sections": {"ع1": 1}, "teachers": ["A"],
        "subjects": [_subj("م1", periods_needed, "A")],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": per_teacher},
        },
    }


@pytest.mark.slow
def test_empty_periods_is_hard_never_violated():
    _s, sched, notes, f = scheduler.solve_timetable(
        _single(2, {"empty_periods": _ep(end=1)}), max_time_in_seconds=10, num_workers=1)
    assert sched["ع1|1"][2] is None and "A" not in notes


@pytest.mark.slow
def test_empty_periods_infeasible_fails_instead_of_violating():
    with pytest.raises(RuntimeError):
        scheduler.solve_timetable(_single(3, {"empty_periods": _ep(end=1)}),
                                  max_time_in_seconds=10, num_workers=1)


def test_empty_periods_overload_caught_by_friendly_precheck():
    with pytest.raises(RuntimeError, match="يستحيل توليد جدول"):
        scheduler.solve_timetable(_single(3, {"empty_periods": _ep(end=1)}),
                                  max_time_in_seconds=10, num_workers=1)


@pytest.mark.slow
def test_gap_windows_is_soft_with_note_not_failure():
    _s, sched, notes, f = scheduler.solve_timetable(
        gap_contest(), max_time_in_seconds=10, num_workers=1)
    assert sum(1 for t in ("A", "B") if t in notes) == 1
    loser_t = next(t for t in ("A", "B") if t in notes)
    assert "نوافذ الفراغ" in notes[loser_t][0]
    assert f[loser_t]["achieved"] < f[loser_t]["requested"]
