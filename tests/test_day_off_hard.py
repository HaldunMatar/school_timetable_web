"""يوم العطلة ("day_off") أصبح قيداً صلباً، لا تفضيلاً ليّناً كما كان: لا
يجوز أبداً وضع أي حصة لأستاذ في يوم عطلته - إن لم تتسع الأيام الأخرى
لنصابه الفعلي، يفشل التوليد بالكامل (رسالة ودّية مسبقة عبر teacher_capacity)
بدل حشر بعض حصصه في يوم عطلته كحل وسط كما كان يحدث سابقاً (هذا بالضبط ما
اشتكى منه المستخدم: "النظام يقوم بوضع حصص بيوم العطلة له"). "تفريغ حصص
بداية/نهاية اليوم" (empty_periods) يبقى ليّناً كما كان - لم يتغيّر."""

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


def _day_off_specific(days):
    return {"enabled": True, "mode": "specific", "days": list(days), "count": 1}


def _day_off_random(count):
    return {"enabled": True, "mode": "random", "days": [], "count": count}


# ----------------------------------------------------------- teacher_capacity

def test_teacher_capacity_subtracts_specific_day_off():
    data = {
        "meta": {"days": ["يوم1", "يوم2", "يوم3"], "periods_per_day": 3},
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"day_off": _day_off_specific(["يوم2"])}},
        },
    }
    # total_slots = 9، ناقص يوم2 (3 حصص) = 6
    assert scheduler.teacher_capacity(data, "A") == 6


def test_teacher_capacity_subtracts_shortest_days_for_random_mode():
    data = {
        "meta": {
            "days": ["يوم1", "يوم2", "يوم3"], "periods_per_day": 4,
            "periods_per_day_override": {"يوم3": 2},
        },
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"day_off": _day_off_random(1)}},
        },
    }
    # total_slots = 4+4+2 = 10، أقصر يوم واحد (يوم3=2) يُطرَح لأنه أفضل حالة
    # ممكنة يختارها الحل (أكبر سعة متبقية) = 8
    assert scheduler.teacher_capacity(data, "A") == 8


def test_teacher_capacity_unaffected_when_day_off_disabled():
    data = {
        "meta": {"days": ["يوم1", "يوم2"], "periods_per_day": 4},
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {},
        },
    }
    assert scheduler.teacher_capacity(data, "A") == 8


# --------------------------------------------------------------- CP-SAT solve

@pytest.mark.slow
def test_day_off_specific_overload_raises_friendly_error_instead_of_violating():
    """الاختبار الحاسم: الأستاذ A يحتاج 4 حصص أسبوعياً، ويطلب عطلة يوم2
    (3 حصص) - فلا يتسع له سوى 3 حصص في يوم1 فقط. بلا القيد الصلب، كان الحل
    سيضطر لوضع حصة واحدة على الأقل في يوم2 (يوم عطلته) لإتمام نصابه الكامل -
    بالضبط ما اشتكى منه المستخدم. مع القيد الصلب يجب أن يفشل التوليد بالكامل
    برسالة ودّية واضحة (سعة الأستاذ لا تكفي)، لا أن يُخالَف يوم العطلة."""
    data = {
        "meta": {
            "days": ["يوم1", "يوم2"], "periods_per_day": 3,
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["A"],
        "subjects": [_subject("م1", 4, "A")],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"day_off": _day_off_specific(["يوم2"])}},
        },
    }
    with pytest.raises(RuntimeError, match="يستحيل توليد جدول"):
        scheduler.solve_timetable(data, max_time_in_seconds=10, num_workers=2)


@pytest.mark.slow
def test_day_off_specific_feasible_case_never_schedules_on_the_off_day():
    """نفس الفكرة لكن مع نصاب يتّسع فعلاً بعد استبعاد يوم العطلة: الأستاذ A
    يحتاج 3 حصص بالضبط = سعة يوم1 وحده بعد استبعاد يوم2 (يوم عطلته) - يجب أن
    تُعاد جدولة كل حصصه على يوم1، ويبقى يوم2 فارغاً منه تماماً بلا أي استثناء."""
    data = {
        "meta": {
            "days": ["يوم1", "يوم2"], "periods_per_day": 3,
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["A", "B"],
        "subjects": [_subject("م1", 3, "A"), _subject("م2", 3, "B")],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"day_off": _day_off_specific(["يوم2"])}},
        },
    }
    _status, section_sched, _notes, fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=2,
    )
    sched = section_sched["ع1|1"]
    # يوم1 = الفهارس 0،1،2 - يوم2 = الفهارس 3،4،5
    assert all(sched[p] is not None and sched[p]["teacher"] == "A" for p in (0, 1, 2)), sched
    assert all(sched[p] is not None and sched[p]["teacher"] == "B" for p in (3, 4, 5)), sched
    assert "A" not in fulfillment  # لا تتبّع بعد الآن - قيد صلب، ليس تفضيلاً ليّناً


@pytest.mark.slow
def test_day_off_random_overload_raises_friendly_error():
    """نفس فكرة الاختبار الحاسم أعلاه، لنمط "عشوائي": الأستاذ A يحتاج 7 حصص
    من أصل 9 (3 أيام × 3 حصص) لكنه يطلب يوماً عشوائياً واحداً عطلة - حتى في
    أفضل الحالات الممكنة (الحل يختار أقصر الأيام عطلة) يبقى 6 فقط < 7
    المطلوبة، فيجب أن يفشل التوليد مبكراً برسالة ودّية."""
    data = {
        "meta": {
            "days": ["يوم1", "يوم2", "يوم3"], "periods_per_day": 3,
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["A"],
        "subjects": [_subject("م1", 7, "A")],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"day_off": _day_off_random(1)}},
        },
    }
    with pytest.raises(RuntimeError, match="يستحيل توليد جدول"):
        scheduler.solve_timetable(data, max_time_in_seconds=10, num_workers=2)


@pytest.mark.slow
def test_day_off_random_feasible_case_leaves_the_chosen_day_fully_empty():
    """نمط عشوائي، نصاب يتّسع فعلاً: الأستاذ A يحتاج 6 حصص بالضبط من أصل 9
    (يومان كاملان بعد استبعاد يوم واحد عطلة) - أياً كان اليوم الذي يختاره
    الحل عطلة، يجب أن يبقى فارغاً من A تماماً (بلا استثناء واحد)، وتُستكمل
    بقية حصص الشعبة بأستاذ آخر B."""
    data = {
        "meta": {
            "days": ["يوم1", "يوم2", "يوم3"], "periods_per_day": 3,
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["A", "B"],
        "subjects": [_subject("م1", 6, "A"), _subject("م2", 3, "B")],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"day_off": _day_off_random(1)}},
        },
    }
    _status, section_sched, _notes, _fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=2,
    )
    sched = section_sched["ع1|1"]
    periods_per_day = 3
    by_day = [sched[d * periods_per_day:(d + 1) * periods_per_day] for d in range(3)]
    a_day_counts = [sum(1 for c in day if c and c["teacher"] == "A") for day in by_day]
    assert a_day_counts.count(0) == 1, a_day_counts  # يوم واحد بالضبط بلا A إطلاقاً
    assert sum(a_day_counts) == 6  # باقي حصص A الست موزَّعة على اليومين الآخرين
