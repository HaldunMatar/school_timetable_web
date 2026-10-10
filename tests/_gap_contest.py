"""سيناريو تنازع مشترك لاختبارات الأولوية: يوم بـ6 حصص، حصتان ثابتتان بلا
أستاذ في الحصتين 3 و5 (فهرس 2 و4)، فتبقى الخانات الحرة {0,1,3,5}. A وB
لكل منهما حصتان وكلاهما max_gap_windows=0 (قيد ليّن): الزوج {0,1} متجاور
بلا نافذة، والزوج {3,5} تفصله حصة ثابتة = نافذة. أحدهما حتماً يُضحّى به
(نافذة واحدة) - تعادل تام تحسمه الأولوية."""

from timetable_web.core import scheduler


def _subj(name, n, teacher):
    return {
        "name": name, "category": "تربوية", "periods": {"ع1": n},
        "names": [teacher] if teacher else [], "manual_assignments": [],
        "constraints": {
            "max_consecutive_per_day": {"enabled": False, "max": 2},
            "max_daily_per_section": {"enabled": False, "max": 2},
        },
    }


def gap_contest(**extra):
    fixed = _subj("ثابتة", 2, None)
    fixed["fixed_no_teacher_slots"] = [
        {"track": "ع1", "sections": "all", "period_index": i} for i in (3, 5)]
    gap0 = {"max_gap_windows": {"enabled": True, "max": 0}}
    d = {
        "meta": {"days": ["يوم1"], "periods_per_day": 6, "grade_order": ["ع1"],
                 "grade_labels": {"ع1": "سابع"}, "nisab_reference": 8},
        "sections": {"ع1": 1},
        "teachers": ["A", "B"],
        "subjects": [_subj("م1", 2, "A"), _subj("م2", 2, "B"), fixed],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": dict(gap0), "B": dict(gap0)},
        },
    }
    d.update(extra)
    return d


def loser(sched):
    """الأستاذ الذي حصل على الزوج المنفصل {3,5} (أي من وقعت عليه النافذة)."""
    return sched["ع1|1"][3]["teacher"]
