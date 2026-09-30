"""يوم أقصر من غيره (periods_per_day_override): يوم واحد أو أكثر بعدد حصص
أصغر من العدد الأساسي للمدرسة (مثلاً الخميس 5 بدل 6) - انظر
scheduler.day_period_count/total_slots. الشبكة نفسها تبقى بعرض
periods_per_day الأساسي لكل الأيام دائماً (نفس nslots القديم بلا أي تغيير في
الشكل) - يوم أقصر يترك حصصه الزائدة معطَّلة (ممنوعة تماماً) بدل إعادة تشكيل
الشبكة، وهو ما يفرض على أكثر من قيد قائم مسبقاً (تفريغ نهاية اليوم، حد
النوافذ الفارغة) أن يستعمل عدد ذلك اليوم الفعلي بدل العدد الأساسي العام - وإلا
انكسر أحدهما بصمت (تفريغ اليوم) أو أصبح الآخر يرفض حلولاً سليمة تماماً (حد
النوافذ)."""

from __future__ import annotations

import pytest

from timetable_web.core import scheduler


# --------------------------------------------------- day_period_count/total_slots

def test_day_period_count_defaults_to_base_with_no_override():
    data = {"meta": {"periods_per_day": 6}}
    assert scheduler.day_period_count(data, "أي يوم") == 6


def test_day_period_count_uses_override_for_named_day_only():
    data = {"meta": {"periods_per_day": 6, "periods_per_day_override": {"الخميس": 5}}}
    assert scheduler.day_period_count(data, "الخميس") == 5
    assert scheduler.day_period_count(data, "الأحد") == 6


def test_day_period_count_clamped_to_base_never_exceeds_it():
    # حماية من قيمة فاسدة/قديمة في الملف تتجاوز العدد الأساسي - لا يجوز أن
    # يصبح يوم "أطول" من الشبكة المبنية عليها كل الحسابات (periods_per_day).
    data = {"meta": {"periods_per_day": 6, "periods_per_day_override": {"الخميس": 9}}}
    assert scheduler.day_period_count(data, "الخميس") == 6


def test_total_slots_sums_real_per_day_counts():
    data = {
        "meta": {"days": ["الأحد", "الخميس"], "periods_per_day": 6,
                 "periods_per_day_override": {"الخميس": 5}},
    }
    assert scheduler.total_slots(data) == 11


def test_teacher_capacity_reflects_shortened_day():
    data = {
        "meta": {"days": ["الأحد", "الخميس"], "periods_per_day": 6,
                 "periods_per_day_override": {"الخميس": 5}},
    }
    assert scheduler.teacher_capacity(data, "أي أستاذ") == 11


# ------------------------------------------------------------- HTTP router --

def test_update_day_periods_sets_override(client, store):
    day = store.data["meta"]["days"][-1]
    r = client.post("/file/day-periods", data={"day": day, "count": "2"})
    assert r.status_code == 200, r.text
    assert store.data["meta"]["periods_per_day_override"][day] == 2


def test_update_day_periods_back_to_base_removes_override(client, store):
    day = store.data["meta"]["days"][-1]
    base = store.data["meta"]["periods_per_day"]
    client.post("/file/day-periods", data={"day": day, "count": "2"})
    r = client.post("/file/day-periods", data={"day": day, "count": str(base)})
    assert r.status_code == 200, r.text
    assert day not in store.data["meta"].get("periods_per_day_override", {})


def test_update_day_periods_rejects_unknown_day(client):
    r = client.post("/file/day-periods", data={"day": "يوم غير موجود", "count": "2"})
    assert r.status_code == 400


def test_update_day_periods_rejects_exceeding_base(client, store):
    base = store.data["meta"]["periods_per_day"]
    day = store.data["meta"]["days"][0]
    r = client.post("/file/day-periods", data={"day": day, "count": str(base + 1)})
    assert r.status_code == 400
    assert day not in store.data["meta"].get("periods_per_day_override", {})


def test_update_day_periods_rejects_zero(client, store):
    day = store.data["meta"]["days"][0]
    r = client.post("/file/day-periods", data={"day": day, "count": "0"})
    assert r.status_code == 400


# --------------------------------------------------------- CP-SAT solve ----

def _base_subject(name, periods_track_value, teacher):
    return {
        "name": name, "category": "تربوية", "periods": {"ع1": periods_track_value},
        "names": [teacher], "manual_assignments": [],
        "constraints": {
            "max_consecutive_per_day": {"enabled": False, "max": 2},
            "max_daily_per_section": {"enabled": False, "max": 2},
        },
    }


@pytest.mark.slow
def test_shortened_day_trailing_periods_never_scheduled():
    """الاختبار الحاسم للتعطيل نفسه: مادة واحدة تشغل بالضبط عدد الحصص
    الفعلي للأسبوع (4 يوم1 + 2 يوم2 المقصور = 6) - فيُجبَر الحل على ملء كل
    حصة حقيقية بلا استثناء (6 مطلوبة = 6 متاحة بالضبط، لا خيار آخر)، تاركاً
    الحصتين الزائدتين ليوم2 (المعطَّلتين) فارغتين دائماً. بلا آلية التعطيل
    هذا التوزيع غير مضمون إطلاقاً - الحل حر باختيار أي حصتين من أصل 8 ليتركهما
    فارغتين."""
    data = {
        "meta": {
            "days": ["يوم1", "يوم2"], "periods_per_day": 4,
            "periods_per_day_override": {"يوم2": 2},
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["A"],
        "subjects": [_base_subject("م1", 6, "A")],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {},
        },
    }
    _status, section_sched, _notes, _fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=2,
    )
    sched = section_sched["ع1|1"]
    # يوم1 (فهرس اليوم 0): الحصص 0..3 حقيقية كلها - يجب أن تكون مشغولة كلها.
    assert all(sched[p] is not None for p in range(4)), sched
    # يوم2 (فهرس اليوم 1، slot = 4*1+p): الحصتان 0،1 حقيقيتان (مشغولتان)،
    # 2،3 معطَّلتان (يجب أن تبقيا فارغتين دائماً).
    assert sched[4] is not None and sched[5] is not None, sched
    assert sched[6] is None and sched[7] is None, (
        f"حصتا يوم2 الزائدتان (المعطَّلتان) لا يجوز أن تُجدوَلا - لكن وُجد: "
        f"{sched[6]!r}, {sched[7]!r}"
    )


@pytest.mark.slow
def test_max_gap_windows_ignores_shortened_days_trailing_slots():
    """الاختبار الحاسم لقيد "حد النوافذ الفارغة" (صلب): الأستاذ A يشغل كل
    حصة حقيقية في الأسبوع بلا أي فجوة فعلية على الإطلاق (مادة واحدة تملأ كل
    شيء) مع max_gap_windows=0 (ولا نافذة واحدة مسموحة) - يجب أن يكون الحل
    ممكناً (FEASIBLE) دائماً. بلا حصر حلقة العدّ بعدد حصص يوم2 الفعلي (2 لا
    3)، الانتقال من آخر حصة حقيقية مشغولة إلى الحصة المعطَّلة التالية
    (فارغة قسراً بسبب قصر اليوم، لا لأي فجوة حقيقية) يُحسَب خطأً كبداية
    نافذة فراغ، فيصطدم بقيد max_gaps=0 الصلب ويصبح الحل مستحيلاً (INFEASIBLE)
    من غير أي سبب حقيقي."""
    data = {
        "meta": {
            "days": ["يوم1", "يوم2"], "periods_per_day": 3,
            "periods_per_day_override": {"يوم2": 2},
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["A"],
        "subjects": [_base_subject("م1", 5, "A")],  # = total_slots (3+2)
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"max_gap_windows": {"enabled": True, "max": 0}}},
        },
    }
    status, section_sched, _notes, _fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=2,
    )
    assert status == "OPTIMAL" or status == "FEASIBLE", status
    sched = section_sched["ع1|1"]
    # يوم1 (فهرس 0..2): 3 حصص حقيقية كلها. يوم2 (فهرس 3..5): حصتان حقيقيتان
    # (3،4) وحصة واحدة معطَّلة (5) - periods_per_day=3، عدد يوم2 الفعلي=2.
    assert all(c is not None for c in (sched[0], sched[1], sched[2], sched[3], sched[4])), sched
    assert sched[5] is None, sched  # حصة يوم2 الزائدة (المعطَّلة)


@pytest.mark.slow
def test_empty_periods_end_targets_the_days_real_last_period():
    """الاختبار الحاسم لتفريغ "نهاية اليوم" (ليّن): يوم واحد مقصور على
    حصتين حقيقيتين فقط من أصل 4 (الحصتان 2،3 معطَّلتان دائماً). الأستاذ B
    يطلب تفريغ آخر حصة (نهاية اليوم)، والأستاذ C بلا أي طلب - كلاهما يحتاج
    حصة واحدة بالضبط لنفس الشعبة، فيُجبَران معاً على شغل الحصتين الحقيقيتين
    الوحيدتين (0،1) بينهما - أيّهما يأخذ أيّها هو بالضبط ما يحدّده تفضيل B.
    "نهاية اليوم" الصحيحة هنا هي الحصة الحقيقية الأخيرة (الفهرس 1) لا الفهرس
    3 (المعطَّل أصلاً وفارغ دائماً بلا أي جهد) - فيجب أن ينتقل B قسراً إلى
    الفهرس 0، تاركاً C الفهرس 1."""
    data = {
        "meta": {
            "days": ["يوم1"], "periods_per_day": 4,
            "periods_per_day_override": {"يوم1": 2},
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["B", "C"],
        "subjects": [_base_subject("م1", 1, "B"), _base_subject("م2", 1, "C")],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {
                "B": {"empty_periods": {
                    "enabled": True,
                    "start": {"enabled": False, "count": 1},
                    "end": {"enabled": True, "count": 1},
                    "days_mode": "all", "days": [], "per_day": {},
                }},
            },
        },
    }
    _status, section_sched, _notes, fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=1,
    )
    sched = section_sched["ع1|1"]
    assert sched[0] is not None and sched[0]["teacher"] == "B", sched
    assert sched[1] is not None and sched[1]["teacher"] == "C", sched
    assert sched[2] is None and sched[3] is None  # الحصتان المعطَّلتان
    assert fulfillment["B"]["achieved"] == fulfillment["B"]["requested"] == 1
