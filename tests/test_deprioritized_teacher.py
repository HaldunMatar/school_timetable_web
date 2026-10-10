"""أستاذ غير مفضَّل: رغباته (القيد الليّن: حد نوافذ الفراغ) تُحاوَل أخيراً
ويُضحّى بها أولاً."""

from __future__ import annotations

import json

import pytest

from timetable_web.core import scheduler

from ._gap_contest import gap_contest, loser


@pytest.mark.slow
@pytest.mark.parametrize("low", ["A", "B"])
def test_deprioritized_teacher_is_the_one_sacrificed(low):
    _s, sched, _n, f = scheduler.solve_timetable(
        gap_contest(deprioritized_teachers=[low]), max_time_in_seconds=10, num_workers=1)
    assert loser(sched) == low


@pytest.mark.slow
def test_preferred_wins_over_deprioritized_listing():
    _s, sched, _n, _f = scheduler.solve_timetable(
        gap_contest(priority_teachers=["A"], deprioritized_teachers=["A"]),
        max_time_in_seconds=10, num_workers=1)
    assert loser(sched) == "B"


def test_unknown_names_ignored():
    scheduler.solve_timetable(gap_contest(deprioritized_teachers=["غير_موجود"]),
                              max_time_in_seconds=5, num_workers=1)


def test_admin_route_saves_and_excludes_preferred(admin_client, tmp_workspace):
    f = tmp_workspace["test_file"]
    d = json.loads(f.read_text(encoding="utf-8"))
    d["priority_teachers"] = ["أحمد"]
    f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r = admin_client.post("/admin/users/test_supervisor/deprioritized-teachers",
                          data={"deprioritized_teachers": ["أحمد", "بشير", "وهمي"]},
                          follow_redirects=False)
    assert r.status_code == 303
    assert json.loads(f.read_text(encoding="utf-8"))["deprioritized_teachers"] == ["بشير"]
    page = admin_client.get("/admin")
    assert page.status_code == 200 and "أستاذ غير مفضَّل" in page.text
