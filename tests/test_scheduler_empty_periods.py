"""اختبارات محرك الحل مباشرةً لقيد "تفريغ حصص" بعدد مختلف لكل يوم (per_day)."""

from __future__ import annotations

import pytest

from timetable_web.core import scheduler


# --------------------------------------------------- normalization -----

def test_normalize_adds_empty_per_day_on_legacy_data():
    legacy = {
        "enabled": True,
        "start": {"enabled": True, "count": 1},
        "end": {"enabled": False, "count": 1},
        "days_mode": "specific",
        "days": ["الأحد", "الاثنين"],
        # لا "per_day" إطلاقاً — ملف قديم قبل هذه الميزة
    }
    normalized = scheduler._normalize_empty_periods_group(legacy)
    assert normalized["per_day"] == {}
    # القيم القديمة لم تتغيّر (fallback يعتمد عليها لاحقاً)
    assert normalized["start"] == {"enabled": True, "count": 1}
    assert normalized["days"] == ["الأحد", "الاثنين"]
    # لا تحوير للأصل (defensive copy)
    assert "per_day" not in legacy


def test_normalize_cleans_up_partial_per_day_entries():
    group = {
        "enabled": True,
        "start": {"enabled": False, "count": 1},
        "end": {"enabled": False, "count": 1},
        "days_mode": "specific",
        "days": ["الأحد"],
        "per_day": {"الأحد": {"start": {"enabled": True}}},  # end مفقود بالكامل
    }
    normalized = scheduler._normalize_empty_periods_group(group)
    assert normalized["per_day"]["الأحد"]["start"] == {"enabled": True, "count": 1}
    assert normalized["per_day"]["الأحد"]["end"] == {"enabled": False, "count": 1}


# --------------------------------------------------- tiny solve instance

def _tiny_instance_with_teacher_constraint(empty_periods_group: dict) -> dict:
    """مدرسة صغيرة: يومان × 4 حصص، صف واحد شعبة واحدة، مادة واحدة يدرّسها
    أستاذ واحد 4 حصص أسبوعياً — بالضبط نصف السعة، بما يكفي من مساحة
    لاختبار best-effort دون تشبّع كامل."""
    return {
        "meta": {
            "days": ["الأحد", "الاثنين"],
            "periods_per_day": 4,
            "grade_order": ["ع1"],
            "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["معلم1"],
        "subjects": [{
            "name": "مادة1",
            "category": "تربوية",
            "periods": {"ع1": 4},
            "names": ["معلم1"],
            "manual_assignments": [],
            "constraints": {
                "max_consecutive_per_day": {"enabled": False, "max": 2},
                "max_daily_per_section": {"enabled": False, "max": 2},
            },
        }],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {
                "معلم1": {"empty_periods": empty_periods_group},
            },
        },
    }


@pytest.mark.slow
def test_solver_respects_different_count_per_day():
    """الأحد: تفريغ 3 حصص من البداية (يبقى فقط سلوت 3 متاحاً بلا مخالفة).
    الاثنين: بلا أي قيد إطلاقاً (كل الأربع سلوتات متاحة بلا مخالفة).
    5 سلوتات "رخيصة" متاحتان لأربع حصص مطلوبة -> يجب أن يتحقق التفضيل
    بالكامل (صفر مخالفات) إن طُبِّق القيد على الأحد فقط دون الاثنين.
    لو طُبِّق القيد خطأً على الاثنين أيضاً (bug: توحيد الإعداد بين الأيام)
    يتبقى سلوت واحد فقط لكل يوم = سلوتان فقط لأربع حصص -> مخالفتان إجبارياً.
    """
    ep_group = {
        "enabled": True,
        "start": {"enabled": False, "count": 1},
        "end": {"enabled": False, "count": 1},
        "days_mode": "specific",
        "days": ["الأحد"],
        "per_day": {
            "الأحد": {
                "start": {"enabled": True, "count": 3},
                "end": {"enabled": False, "count": 1},
            },
        },
    }
    data = _tiny_instance_with_teacher_constraint(ep_group)
    status, section_sched, notes, fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10
    )
    assert status in ("OPTIMAL", "FEASIBLE")

    # لا ملاحظة مخالفة لهذا الأستاذ -> تحقق القيد بالكامل
    assert "معلم1" not in notes, f"توقعنا صفر مخالفات لكن ظهرت ملاحظة: {notes.get('معلم1')}"

    # تحقق مباشر: لا شيء من حصص معلم1 يقع في فترات الأحد 0/1/2 (المطلوب تفريغها)
    cells = section_sched["ع1|1"]
    periods_per_day = 4
    sunday_targeted_slots = [0, 1, 2]  # first 3 slots of day 0 (الأحد)
    for p in sunday_targeted_slots:
        cell = cells[p]
        assert cell is None or cell["teacher"] != "معلم1", (
            f"معلم1 مجدول في فترة الأحد {p} رغم طلب تفريغها تحديداً لهذا اليوم فقط"
        )

    # وفي المقابل، الاثنين (اليوم الثاني، بلا أي قيد) يُستخدَم بحرية
    monday_slots = [periods_per_day + p for p in range(periods_per_day)]
    monday_used = sum(1 for s in monday_slots if cells[s] and cells[s]["teacher"] == "معلم1")
    assert monday_used > 0, "الاثنين بلا أي قيد ويجب أن يُستخدَم لتغطية حصص معلم1"


@pytest.mark.slow
def test_solver_all_days_mode_still_applies_uniformly():
    """تأكيد عدم كسر نمط 'كل الأيام' الحالي بعد إضافة per_day."""
    ep_group = {
        "enabled": True,
        "start": {"enabled": True, "count": 1},
        "end": {"enabled": False, "count": 1},
        "days_mode": "all",
        "days": [],
        "per_day": {},
    }
    data = _tiny_instance_with_teacher_constraint(ep_group)
    status, section_sched, notes, fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10
    )
    assert status in ("OPTIMAL", "FEASIBLE")
    assert "معلم1" not in notes
    cells = section_sched["ع1|1"]
    # أول فترة من كل يوم (0 و 4) يجب أن تبقى فارغة لمعلم1
    for first_of_day in (0, 4):
        cell = cells[first_of_day]
        assert cell is None or cell["teacher"] != "معلم1"
