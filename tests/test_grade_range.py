"""تمديد نطاق الصفوف المدعومة من "سابع - بكالوريا" إلى "أول - بكالوريا"
(14 صفاً). فقط المدارس الجديدة تحصل على الصفوف الإضافية (أول-سادس) -
المدارس الحالية تبقى بنطاقها القديم كما هو تماماً (grade_order لا يُعاد
بناؤه لمدرسة موجودة أصلاً)."""

from __future__ import annotations

from timetable_web.core import scheduler


def test_new_blank_data_includes_all_14_grades_in_order():
    data = scheduler.new_blank_data(["الأحد", "الاثنين"], 6, 18)
    assert data["meta"]["grade_order"] == [
        "ب1", "ب2", "ب3", "ب4", "ب5", "ب6",
        "ع1", "ع2", "ع3", "ثا1أ", "ثا1ع", "ثا2أ", "ثا2ع", "ثا3",
    ]


def test_new_blank_data_labels_the_new_primary_grades():
    data = scheduler.new_blank_data(["الأحد"], 6, 18)
    labels = data["meta"]["grade_labels"]
    assert labels["ب1"] == "أول"
    assert labels["ب2"] == "ثاني"
    assert labels["ب3"] == "ثالث"
    assert labels["ب4"] == "رابع"
    assert labels["ب5"] == "خامس"
    assert labels["ب6"] == "سادس"
    # الصفوف القديمة (سابع - بكالوريا) لم تتغيّر
    assert labels["ع1"] == "سابع"
    assert labels["ثا3"] == "بكالوريا أدبي"


def test_new_blank_data_gives_every_grade_one_default_section():
    data = scheduler.new_blank_data(["الأحد"], 6, 18)
    for g in data["meta"]["grade_order"]:
        assert data["sections"][g] == 1


def test_fresh_school_with_new_grades_has_no_incomplete_or_crash():
    """صحة سريعة: صفوف جديدة بلا مواد بعد لا تُسبِّب أي خطأ في الدوال
    التي تقرأ grade_order/sections ديناميكياً."""
    data = scheduler.new_blank_data(["الأحد", "الاثنين"], 6, 18)
    totals = scheduler.grade_period_totals(data)
    assert set(totals.keys()) == set(data["meta"]["grade_order"])
    assert all(v == 0.0 for v in totals.values())

    incomplete = scheduler.incomplete_grades(data)
    # كل الصفوف فيها شعبة واحدة بلا أي مادة بعد - جميعها "غير مكتملة"
    # (الفجوة = كامل نصاب الأسبوع)، وهذا سلوك متوقع تماماً، وليس خطأ.
    assert len(incomplete) == len(data["meta"]["grade_order"])


def _old_style_school():
    return {
        "meta": {
            "days": ["الأحد"], "periods_per_day": 6,
            "grade_order": ["ع1", "ع2", "ع3", "ثا1أ", "ثا1ع", "ثا2أ", "ثا2ع", "ثا3"],
            "grade_labels": {
                "ع1": "سابع", "ع2": "ثامن", "ع3": "تاسع",
                "ثا1أ": "عاشر أدبي", "ثا1ع": "عاشر علمي",
                "ثا2أ": "حادي عشر أدبي", "ثا2ع": "حادي عشر علمي",
                "ثا3": "بكالوريا أدبي",
            },
            "nisab_reference": 18,
        },
        "sections": {"ع1": 5, "ع2": 4, "ع3": 5, "ثا1أ": 0, "ثا1ع": 0, "ثا2أ": 0, "ثا2ع": 0, "ثا3": 0},
        "subjects": [],
        "teachers": [],
    }


# ---------- ensure_full_grade_range: ترقية ملفات المدارس القديمة -------

def test_ensure_full_grade_range_backfills_missing_grades_with_zero_sections():
    data = _old_style_school()
    scheduler.ensure_full_grade_range(data)
    assert data["meta"]["grade_order"] == [
        "ب1", "ب2", "ب3", "ب4", "ب5", "ب6",
        "ع1", "ع2", "ع3", "ثا1أ", "ثا1ع", "ثا2أ", "ثا2ع", "ثا3",
    ]
    for g in ("ب1", "ب2", "ب3", "ب4", "ب5", "ب6"):
        assert data["sections"][g] == 0
        assert data["meta"]["grade_labels"][g]  # موجودة وغير فارغة


def test_ensure_full_grade_range_does_not_touch_existing_grades():
    data = _old_style_school()
    scheduler.ensure_full_grade_range(data)
    # الصفوف القديمة (وأعداد شعبها الفعلية) بقيت كما هي بالضبط
    assert data["sections"]["ع1"] == 5
    assert data["sections"]["ع2"] == 4
    assert data["meta"]["grade_labels"]["ع1"] == "سابع"


def test_ensure_full_grade_range_is_idempotent():
    data = _old_style_school()
    scheduler.ensure_full_grade_range(data)
    first = list(data["meta"]["grade_order"])
    scheduler.ensure_full_grade_range(data)  # مرة ثانية - لا شيء يتغيّر
    assert data["meta"]["grade_order"] == first


def test_ensure_full_grade_range_noop_on_already_full_school():
    data = scheduler.new_blank_data(["الأحد"], 6, 18)  # 14 صفاً بالفعل
    before = list(data["meta"]["grade_order"])
    scheduler.ensure_full_grade_range(data)
    assert data["meta"]["grade_order"] == before


def test_old_school_still_works_after_backfill_no_crash():
    """صحة سريعة: مدرسة قديمة بعد الترقية لا تُسبِّب أي خطأ في الدوال
    التي تقرأ grade_order/sections."""
    data = _old_style_school()
    scheduler.ensure_full_grade_range(data)
    totals = scheduler.grade_period_totals(data)
    assert set(totals.keys()) == {"ع1", "ع2", "ع3"}  # فقط الصفوف بشعب > 0
    incomplete = scheduler.incomplete_grades(data)
    assert {g for g, *_ in incomplete} <= set(data["meta"]["grade_order"])


def test_store_load_auto_upgrades_an_old_school_file(tmp_path):
    """التكامل: Store.load() الفعلي (وليس استدعاء مباشر للدالة) يُرقّي أي
    ملف مدرسة قديم فور فتحه - يُحاكي بالضبط ما سيحدث للملفات الحقيقية."""
    import json
    from timetable_web.state.store import Store

    old_file = tmp_path / "old_school.json"
    old_file.write_text(json.dumps(_old_style_school(), ensure_ascii=False), encoding="utf-8")

    store = Store()
    store.load(old_file)
    assert store.data["meta"]["grade_order"][:6] == ["ب1", "ب2", "ب3", "ب4", "ب5", "ب6"]
    assert store.data["sections"]["ب1"] == 0
    # الصفوف الأصلية وشعبها الفعلية لم تتأثر
    assert store.data["sections"]["ع1"] == 5


def test_admin_created_supervisor_gets_full_14_grade_range(admin_client, tmp_workspace):
    r = admin_client.post("/admin/users/create", data={
        "username": "new_full_range_school", "password": "pw123456",
        "periods_per_day": "6", "nisab_reference": "18",
        "day_الأحد": "on", "day_الاثنين": "on",
    }, follow_redirects=False)
    assert r.status_code == 303

    import json
    created = json.loads((tmp_workspace["schools_dir"] / "new_full_range_school.json").read_text(encoding="utf-8"))
    assert created["meta"]["grade_order"][:6] == ["ب1", "ب2", "ب3", "ب4", "ب5", "ب6"]
    assert len(created["meta"]["grade_order"]) == 14
