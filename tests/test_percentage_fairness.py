"""عدالة "نسبة تحقق الرغبات" بدل عدد الخانات المخالفة الخام في هدف
محرك الحل: أستاذ طلب حصة واحدة وفقدها (0%) لا يجوز أن يُعامَل بمساواة مع
أستاذ طلب عدة حصص وفقد واحدة منها فقط (نسبة عالية) - انظر شرح solve_
timetable حول max_frac_var."""

from __future__ import annotations

import pytest

from timetable_web.core import scheduler


def _instance():
    """يومان × حصتان لشعبة واحدة، مادتان (كل منهما حصة واحدة لكل يوم = حصتان
    إجمالاً) تملآن الأسبوع بالكامل بين أستاذين A وB.

    B يطلب فقط "تفريغ آخر حصة يوم1" (طلب صغير: حصة واحدة مطلوبة).
    A يطلب "تفريغ آخر حصة" في كل الأيام (طلب أكبر: حصتان مطلوبتان).

    آخر حصة من يوم1 هي نقطة التنازع الوحيدة الحتمية (الشعبة معبأة بالكامل
    بين A وB، فأحدهما حتماً يُدرِّس حينها) - أياً من الاثنين "يخسر" هناك،
    يتحدد بذلك: يوم2 لا تنازع فيه إطلاقاً (B لا يطلب شيئاً فيه، فيمكن دائماً
    ترك A حراً فيه بلا أي تكلفة على الإطلاق)."""
    ep_all_days = {
        "enabled": True,
        "start": {"enabled": False, "count": 1},
        "end": {"enabled": True, "count": 1},
        "days_mode": "all",
        "days": [],
        "per_day": {},
    }
    ep_day1_only = {
        "enabled": True,
        "start": {"enabled": False, "count": 1},
        "end": {"enabled": True, "count": 1},
        "days_mode": "specific",
        "days": ["يوم1"],
        "per_day": {
            "يوم1": {
                "start": {"enabled": False, "count": 1},
                "end": {"enabled": True, "count": 1},
            },
        },
    }
    return {
        "meta": {
            "days": ["يوم1", "يوم2"], "periods_per_day": 2,
            "grade_order": ["ع1"], "grade_labels": {"ع1": "سابع"},
            "nisab_reference": 8,
        },
        "sections": {"ع1": 1},
        "teachers": ["A", "B"],
        "subjects": [
            {
                "name": "م1", "category": "تربوية", "periods": {"ع1": 2},
                "names": ["A"], "manual_assignments": [],
                "constraints": {
                    "max_consecutive_per_day": {"enabled": False, "max": 2},
                    "max_daily_per_section": {"enabled": False, "max": 2},
                },
            },
            {
                "name": "م2", "category": "تربوية", "periods": {"ع1": 2},
                "names": ["B"], "manual_assignments": [],
                "constraints": {
                    "max_consecutive_per_day": {"enabled": False, "max": 2},
                    "max_daily_per_section": {"enabled": False, "max": 2},
                },
            },
        ],
        "scheduling_constraints": {
            "defaults": dict(scheduler.DEFAULT_TEACHER_CONSTRAINTS),
            "per_teacher": {"A": {"empty_periods": ep_all_days}, "B": {"empty_periods": ep_day1_only}},
        },
    }


def _day1_last_slot_teacher(section_sched):
    return section_sched["ع1|1"][1]["teacher"]  # يوم1 فهرس 0، الحصة الأخيرة فهرس 1


@pytest.mark.slow
def test_percentage_fairness_protects_the_smaller_request():
    """الاختبار الحاسم: عدالة العدد الخام تتساوى تماماً بين الخيارين (خانة
    واحدة مخالفة أياً كان الخاسر) فتفشل هذه المفاضلة - عدالة النسبة يجب أن
    تُغلِّب حماية B (طلبه الأصغر) دائماً، مُحمِّلة A (طلبه الأكبر، فيتحمّل
    نصف طلبه فقط - 50% - بدل تصفير B بالكامل - 0%).

    num_workers=1 عمداً (بدل الافتراضي 8 في الإنتاج): بحث CP-SAT المتوازي
    (عدة استراتيجيات مختلفة تعمل معاً) قد "يتعثّر" أحياناً بالحل الأفضل حتى
    مع الهدف القديم بمحض الصدفة (تأكدتُ من هذا يدوياً)، فيُخفي الفرق
    الحقيقي بين الآليتين. عامل بحث واحد يكشف السلوك الفعلي للهدف نفسه بلا
    تشويش - وبتجربة 10 بذور عشوائية مختلفة يدوياً (خارج هذا الاختبار)،
    الهدف القديم اختار B خاسراً في كل مرة (خطأ)، والجديد اختار A في كل
    مرة (صحيح) - سلوك حتمي في كلتا الحالتين، وليس صدفة."""
    data = _instance()
    _status, section_sched, _notes, fulfillment = scheduler.solve_timetable(
        data, max_time_in_seconds=10, num_workers=1,
    )
    teacher_at_slot = _day1_last_slot_teacher(section_sched)
    assert teacher_at_slot == "A", (
        "يجب أن يخسر A (الطلب الأكبر) لا B (الطلب الأصغر) - "
        f"لكن الحصة وقعت عند {teacher_at_slot}"
    )
    # تأكيد إضافي عبر أرقام التحقق نفسها: B يجب أن يكون محقَّقاً بالكامل
    assert fulfillment["B"]["achieved"] == fulfillment["B"]["requested"] == 1
    assert fulfillment["A"]["requested"] == 2
    assert fulfillment["A"]["achieved"] == 1  # 50% - وليس 0% ولا 100%
