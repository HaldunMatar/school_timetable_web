"""انحدار (regression): إزالة أستاذ "حر" (بلا إسناد إجباري) من مادة، بينما
باقي أساتذتها مُسنَدون إجبارياً وتبقى حصص لم تُسنَد، كانت تُسقِط كل صفحة تستدعي
scheduler.teacher_current_periods أو scheduler.teacher_roster بخطأ 500 غير
معالَج (pack_subject يرفع RuntimeError عن قصد في هذه الحالة، لكن تلك الدوال
لم تكن تتوقّع ذلك رغم أنها مجرّد إحصائيات عرض توضيحية).
"""

from __future__ import annotations


def _make_unassignable(client, store):
    """يجعل مادة "الرياضيات" (subjects[0]) بحالة: أساتذتها كلهم مُسنَدون
    إجبارياً بعد إزالة أحمد، بينما تبقى حصص صف ع2 بلا أستاذ يستلمها تلقائياً."""
    r = client.post("/subjects/0/name/add", data={"name": "بشير"})
    assert r.status_code == 200
    r = client.post(
        "/subjects/0/manual/add",
        data={"teacher": "بشير", "track": "ع1", "section_csv": "1"},
    )
    assert r.status_code == 200
    # الآن: أحمد حر (بلا إسناد إجباري)، بشير مُسنَد فقط لِـ ع1 شعبة 1.
    # حصص ع2 شعبة 1 تُوزَّع تلقائياً على أحمد. إزالة أحمد تترك بشير الوحيد،
    # وهو مُسنَد بالفعل، فتبقى حصص ع2 بلا مُستلِم.
    return client.post("/subjects/0/name/remove", data={"name": "أحمد"})


def test_removing_free_teacher_leaves_subject_unassignable_but_does_not_crash(client, store):
    r = _make_unassignable(client, store)
    assert r.status_code == 200, r.text


def test_dashboard_survives_and_warns_after_unassignable_subject(client, store):
    _make_unassignable(client, store)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "إسناد إجباري غير صالح" in r.text


def test_other_pages_survive_after_unassignable_subject(client, store):
    _make_unassignable(client, store)
    for path in ("/teachers", "/constraints", "/subjects", "/subjects/0"):
        r = client.get(path)
        assert r.status_code == 200, path


def test_teacher_current_periods_skips_unassignable_subject_instead_of_raising(client, store):
    from timetable_web.core import scheduler
    _make_unassignable(client, store)
    # لا يجب أن يرفع استثناء - فقط يتجاهل مساهمة هذه المادة تحديداً.
    total = scheduler.teacher_current_periods(store.data, "بشير")
    assert isinstance(total, float)
