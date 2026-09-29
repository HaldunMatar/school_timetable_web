"""أستاذ مفضَّل (من لوحة الأدمن الكبير) - تفضيل خفيف (كسر تعادل فقط) في
تحقيق رغباته، بلا أي تأثير على مجموع المخالفات أو عدالة التوزيع بين بقية
الأساتذة. اختبارات محرك الحل مباشرة + مسارات admin.py."""

from __future__ import annotations

import pytest

from timetable_web.core import scheduler


def _tied_instance(priority_teachers=None):
    """يوم واحد × حصتان = خانتان لشعبة واحدة، مادتان (كل منهما حصة واحدة
    فقط) تملآن كامل الأسبوع بين أستاذين A وB. كلاهما يريد "تفريغ آخر حصة"
    (الحصة الثانية) - لكن بما أن الشعبة معبأة بالكامل بين المادتين، فأحدهما
    حتماً سيُدرِّس تلك الحصة والآخر سيكون حراً فيها - تعادل تام بين
    الاحتمالين (لا فرق في إجمالي المخالفات ولا في العدالة)، فيصبح تفضيل
    الأستاذ (إن وُجد) هو الفيصل الوحيد في اختيار أيّهما يُضحّى براحته."""
    ep = {
        "enabled": True,
        "start": {"enabled": False, "count": 1},
        "end": {"enabled": True, "count": 1},
        "days_mode": "all",
        "days": [],
        "per_day": {},
    }
    per_teacher = {
        "A": {"empty_periods": dict(ep)},
        "B": {"empty_periods": dict(ep)},
    }
    data = {
        "meta": {
            "days": ["يوم1"], "periods_per_day": 2,
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["A", "B"],
        "subjects": [
            {
                "name": "م1", "category": "تربوية", "periods": {"ع1": 1},
                "names": ["A"], "manual_assignments": [],
                "constraints": {
                    "max_consecutive_per_day": {"enabled": False, "max": 2},
                    "max_daily_per_section": {"enabled": False, "max": 2},
                },
            },
            {
                "name": "م2", "category": "تربوية", "periods": {"ع1": 1},
                "names": ["B"], "manual_assignments": [],
                "constraints": {
                    "max_consecutive_per_day": {"enabled": False, "max": 2},
                    "max_daily_per_section": {"enabled": False, "max": 2},
                },
            },
        ],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": per_teacher,
        },
    }
    if priority_teachers is not None:
        data["priority_teachers"] = priority_teachers
    return data


def _a_is_violated(section_sched):
    last_slot = section_sched["ع1|1"][1]  # آخر حصة (الفهرس 1) لليوم الوحيد
    return last_slot is not None and last_slot["teacher"] == "A"


@pytest.mark.slow
def test_priority_teacher_consistently_wins_the_tie():
    data = _tied_instance(priority_teachers=["A"])
    for _ in range(3):  # عدة تشغيلات - يجب أن تُحسم دائماً بنفس الاتجاه
        _status, section_sched, _notes, _fulfillment = scheduler.solve_timetable(
            data, max_time_in_seconds=10, num_workers=2,
        )
        assert not _a_is_violated(section_sched), "الأستاذ المفضَّل A يجب ألا يُضحّى براحته أبداً عند التعادل"


@pytest.mark.slow
def test_priority_teacher_for_b_flips_the_outcome():
    """نفس السيناريو تماماً لكن الأفضلية الآن لـB - يثبت أن النتيجة تتبع
    التفضيل فعلاً، وليست مجرد صدفة ترتيب داخلي في المحرك."""
    data = _tied_instance(priority_teachers=["B"])
    _status, section_sched, _notes, _fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=2,
    )
    assert _a_is_violated(section_sched), "بما أن B هو المفضَّل هنا، يجب أن يُضحّى بـA بدلاً منه"


def test_no_priority_teachers_field_is_a_pure_noop():
    """غياب الحقل كلياً (كأي ملف مدرسة لم يُستخدَم فيه هذا الإعداد أبداً)
    لا يرفع أي استثناء ولا يُغيّر شيئاً - فقط لا وجود لأي تفضيل."""
    data = _tied_instance(priority_teachers=None)
    assert "priority_teachers" not in data
    scheduler.solve_timetable(data, max_time_in_seconds=5, num_workers=2)


def test_priority_teacher_not_in_school_is_silently_ignored():
    """اسم في priority_teachers لا يطابق أي أستاذ حقيقي في هذه المدرسة -
    لا يرفع خطأ، فقط يُتجاهَل (لا شيء لتفضيله أصلاً)."""
    data = _tied_instance(priority_teachers=["غير_موجود"])
    scheduler.solve_timetable(data, max_time_in_seconds=5, num_workers=2)
