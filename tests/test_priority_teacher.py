"""أستاذ مفضَّل (من لوحة الأدمن) - تفضيل خفيف (كسر تعادل فقط) في تحقيق رغباته
(القيد الليّن: حد نوافذ الفراغ)."""

from __future__ import annotations

import pytest

from timetable_web.core import scheduler

from ._gap_contest import gap_contest, loser


@pytest.mark.slow
@pytest.mark.parametrize("preferred,expected_loser", [("A", "B"), ("B", "A")])
def test_priority_teacher_wins_the_tie(preferred, expected_loser):
    data = gap_contest(priority_teachers=[preferred])
    for _ in range(2):
        _s, sched, _n, _f = scheduler.solve_timetable(data, max_time_in_seconds=10, num_workers=1)
        assert loser(sched) == expected_loser


def test_no_priority_teachers_field_is_a_pure_noop():
    scheduler.solve_timetable(gap_contest(), max_time_in_seconds=5, num_workers=1)


def test_priority_teacher_not_in_school_is_silently_ignored():
    scheduler.solve_timetable(gap_contest(priority_teachers=["غير_موجود"]),
                              max_time_in_seconds=5, num_workers=1)
