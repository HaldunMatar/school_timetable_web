""""الحد الأقصى لعدد الحصص الفارغة المتتالية في اليوم" (max_consecutive_empty) -
قيد صلب جديد، مكمِّل لـ"max_gap_windows" الموجود: ذاك يحدّ عدد نوافذ الفراغ
المنفصلة بغضّ النظر عن طول كل واحدة (busy,empty,busy,empty = نافذتان مهما
طالتا)، وهذا يحدّ طول أي نافذة واحدة بغضّ النظر عن عددها (لا يجوز أكثر من N
حصة فارغة متتالية، مهما كان عدد النوافذ). طُلب من المستخدم بعد أن لاحظ أن
الإعداد الموجود لا يمنع تجمّع عدة حصص فارغة متتالية طالما بقيت ضمن "نافذة"
واحدة."""

from __future__ import annotations

import pytest

from timetable_web.core import scheduler


def _subject(name, periods_track_value, teacher):
    return {
        "name": name, "category": "تربوية", "periods": {"ع1": periods_track_value},
        "names": [teacher], "manual_assignments": [],
        "constraints": {
            "max_consecutive_per_day": {"enabled": False, "max": 2},
            "max_daily_per_section": {"enabled": False, "max": 2},
        },
    }


# --------------------------------------------------------- effective_constraints

def test_default_shape_has_max_consecutive_empty_disabled():
    data = {"scheduling_constraints": {"defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS), "per_teacher": {}}}
    eff = scheduler.effective_constraints(data, "أي أستاذ")
    assert eff["max_consecutive_empty"] == {"enabled": False, "max": 2}


def test_per_teacher_override_merges_independently_of_other_keys():
    data = {
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"max_consecutive_empty": {"enabled": True, "max": 1}}},
        },
    }
    eff = scheduler.effective_constraints(data, "A")
    assert eff["max_consecutive_empty"] == {"enabled": True, "max": 1}
    assert eff["max_gap_windows"] == scheduler.DEFAULT_TEACHER_CONSTRAINTS["max_gap_windows"]


# --------------------------------------------------------------- HTTP router

def test_update_default_max_consecutive_empty(client, store):
    r = client.post(
        "/constraints/defaults/max_consecutive_empty",
        data={"enabled": "on", "max": "1"},
    )
    assert r.status_code == 200, r.text
    g = store.data["scheduling_constraints"]["defaults"]["max_consecutive_empty"]
    assert g == {"enabled": True, "max": 1}


# --------------------------------------------------------------- CP-SAT solve

@pytest.mark.slow
def test_max_consecutive_empty_forbids_long_empty_runs():
    """الاختبار الحاسم: أستاذ A يحتاج حصتين فقط من أصل 5 حصص يوم واحد - بلا
    أي قيد، الحل يترك المطلوب في النهاية (ثبت هذا تجريبياً)، تاركاً 3 حصص
    فارغة متتالية في البداية. مع max_consecutive_empty=1، يجب ألا يتجاوز أي
    امتداد فراغ حصة واحدة متتالية على الإطلاق."""
    data = {
        "meta": {
            "days": ["يوم1"], "periods_per_day": 5,
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["A"],
        "subjects": [_subject("م1", 2, "A")],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"max_consecutive_empty": {"enabled": True, "max": 1}}},
        },
    }
    _status, section_sched, _notes, _fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=2,
    )
    sched = section_sched["ع1|1"]
    run = worst = 0
    for c in sched:
        if c is None:
            run += 1
            worst = max(worst, run)
        else:
            run = 0
    assert worst <= 1, (
        f"أطول امتداد فراغ متتالٍ هو {worst} - يتجاوز الحد الأقصى المطلوب (1): {sched}"
    )


@pytest.mark.slow
def test_max_consecutive_empty_overload_raises_friendly_error():
    """طلب مستحيل رياضياً: max=0 (بلا أي حصة فارغة متتالية مسموحة إطلاقاً)
    يعني عملياً "كل حصص اليوم يجب أن تكون مشغولة" (نافذة بحجم 1: كل حصة
    بمفردها يجب أن تحوي حصة مشغولة) - لكن الأستاذ A يحتاج حصة واحدة فقط من
    أصل 3 حصص ذلك اليوم، فيستحيل تحقيق الشرطين معاً (مشغول بالكامل كل يوم
    له فيه حصص، مع حصة واحدة فقط مطلوبة). يجب أن يفشل التوليد (INFEASIBLE)،
    لا أن يتجاوز الحد بصمت."""
    data = {
        "meta": {
            "days": ["يوم1"], "periods_per_day": 3,
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["A"],
        "subjects": [_subject("م1", 1, "A")],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"max_consecutive_empty": {"enabled": True, "max": 0}}},
        },
    }
    with pytest.raises(RuntimeError):
        scheduler.solve_timetable(data, max_time_in_seconds=10, num_workers=2)


@pytest.mark.slow
def test_max_consecutive_empty_exempts_a_full_day_off():
    """الاختبار الحاسم المكتشَف على بيانات حقيقية: "يوم عطلة" فارغ بالكامل
    عمداً (قيد صلب منفصل تماماً) لا يجوز أن يتعارض أبداً مع
    max_consecutive_empty - وإلا لصار أي يوم عطلة (أطول امتداد فراغ ممكن)
    مستحيلاً حتماً مع أي قيمة محدودة لهذا الإعداد. الأستاذ A يطلب يوم2 عطلة
    (3 حصص فارغة متتالية - يتجاوز max=1 بكثير لو طُبِّق هناك) مع
    max_consecutive_empty=1 في آنٍ واحد - يجب أن يبقى التوليد ممكناً تماماً،
    مع تطبيق القيد فقط على يوم1 (يوم عمل فعلي له فيه حصص)."""
    data = {
        "meta": {
            "days": ["يوم1", "يوم2"], "periods_per_day": 3,
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["A"],
        "subjects": [_subject("م1", 3, "A")],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {
                "day_off": {"enabled": True, "mode": "specific", "days": ["يوم2"], "count": 1},
                "max_consecutive_empty": {"enabled": True, "max": 1},
            }},
        },
    }
    _status, section_sched, _notes, _fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=2,
    )
    sched = section_sched["ع1|1"]
    assert all(c is not None and c["teacher"] == "A" for c in sched[0:3]), sched
    assert all(c is None for c in sched[3:6]), sched  # يوم2 فارغ بالكامل - يوم عطلة A
