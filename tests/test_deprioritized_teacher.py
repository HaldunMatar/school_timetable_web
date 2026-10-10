"""أستاذ غير مفضَّل: رغباته (تفريغ حصص) تُحاوَل أخيراً ويُضحّى بها أولاً، حتى
لو كلّف ذلك مخالفات أكثر إجمالاً - لا يُضحّى بعاديّ لأجله."""

from __future__ import annotations

import pytest

from timetable_web.core import scheduler


def _subj(name, n, teacher):
    return {
        "name": name, "category": "تربوية", "periods": {"ع1": n},
        "names": [teacher], "manual_assignments": [],
        "constraints": {
            "max_consecutive_per_day": {"enabled": False, "max": 2},
            "max_daily_per_section": {"enabled": False, "max": 2},
        },
    }


def _ep(end_count):
    return {"enabled": True, "start": {"enabled": False, "count": 1},
            "end": {"enabled": True, "count": end_count},
            "days_mode": "all", "days": [], "per_day": {}}


def _data(**extra):
    """يوم بحصتين، A وB حصة واحدة لكل منهما، كلاهما يريد الحصة الأخيرة فارغة -
    تعادل تام: أحدهما حتماً يُضحّى به. غير المفضَّل هو من يُضحّى به."""
    d = {
        "meta": {"days": ["يوم1"], "periods_per_day": 2, "grade_order": ["ع1"],
                 "grade_labels": {"ع1": "سابع"}, "nisab_reference": 8},
        "sections": {"ع1": 1},
        "teachers": ["A", "B"],
        "subjects": [_subj("م1", 1, "A"), _subj("م2", 1, "B")],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"empty_periods": _ep(1)}, "B": {"empty_periods": _ep(1)}},
        },
    }
    d.update(extra)
    return d


def _last_teacher(sched):
    return sched["ع1|1"][1]["teacher"]


@pytest.mark.slow
@pytest.mark.parametrize("low,expected_last", [("A", "A"), ("B", "B")])
def test_deprioritized_teacher_is_the_one_sacrificed(low, expected_last):
    _s, sched, _n, f = scheduler.solve_timetable(
        _data(deprioritized_teachers=[low]), max_time_in_seconds=10, num_workers=1)
    assert _last_teacher(sched) == expected_last


@pytest.mark.slow
def test_deprioritized_is_sacrificed_even_when_it_costs_more_total():
    """A غير مفضَّل يطلب تفريغ آخر حصتين (2 خانة)، B يطلب آخر حصة (1 خانة)،
    4 حصص، كل منهما حصتان: كي يُحمى B كلياً يقع A في الحصتين الأخيرتين
    (مخالفتان) - أكثر من لو ضُحّي بـB. يجب أن يُحمى B رغم ذلك."""
    d = _data(deprioritized_teachers=["A"])
    d["meta"]["periods_per_day"] = 4
    d["subjects"] = [_subj("م1", 2, "A"), _subj("م2", 2, "B")]
    d["scheduling_constraints"]["per_teacher"] = {
        "A": {"empty_periods": _ep(2)}, "B": {"empty_periods": _ep(1)}}
    _s, sched, _n, f = scheduler.solve_timetable(d, max_time_in_seconds=10, num_workers=1)
    assert f["B"]["achieved"] == f["B"]["requested"], f


@pytest.mark.slow
def test_preferred_wins_over_deprioritized_listing():
    """مفضَّل ومُدرَج غير مفضَّل في آن واحد: المفضَّل هو الأقوى."""
    _s, sched, _n, _f = scheduler.solve_timetable(
        _data(priority_teachers=["A"], deprioritized_teachers=["A"]),
        max_time_in_seconds=10, num_workers=1)
    assert _last_teacher(sched) == "B"


def test_unknown_names_ignored():
    scheduler.solve_timetable(_data(deprioritized_teachers=["غير_موجود"]),
                              max_time_in_seconds=5, num_workers=1)


def test_admin_route_saves_and_excludes_preferred(admin_client, tmp_workspace):
    import json
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
