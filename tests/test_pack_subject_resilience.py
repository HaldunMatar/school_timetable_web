"""انحدار (regression): إزالة أستاذ "حر" (بلا إسناد إجباري) من مادة، بينما
باقي أساتذتها مُسنَدون إجبارياً وتبقى حصص لم تُسنَد، كانت تُسقِط كل صفحة تستدعي
scheduler.teacher_current_periods أو scheduler.teacher_roster بخطأ 500 غير
معالَج (pack_subject يرفع RuntimeError عن قصد في هذه الحالة، لكن تلك الدوال
لم تكن تتوقّع ذلك رغم أنها مجرّد إحصائيات عرض توضيحية).
"""

from __future__ import annotations


def _make_unassignable(client, store):
    """مادة "الرياضيات" (subjects[0]) في tiny_data: صف ع1 له شعبة واحدة فقط
    افتراضياً. نرفعها إلى 3 شعب، ثم نضيف أستاذين إضافيين (بشير من الوسط
    المركزي + سامي جديد) ونُسنِد كلاً منهما إجبارياً لشعبة واحدة من ع1،
    تاركين أحمد "حراً" يستلم تلقائياً كل ما تبقى (شعبة ع1 الثالثة + كل ع2).
    إزالة أحمد بعد ذلك تترك بشير وسامي مُسنَدين، بلا أحد يستلم البقية."""
    assert client.post("/sections/ع1", data={"count": "3"}).status_code == 200
    assert client.post("/teachers/add", data={"name": "سامي"}).status_code == 200
    assert client.post("/subjects/0/name/add", data={"name": "بشير"}).status_code == 200
    assert client.post("/subjects/0/name/add", data={"name": "سامي"}).status_code == 200
    assert client.post(
        "/subjects/0/manual/add",
        data={"teacher": "بشير", "track": "ع1", "section_csv": "1"},
    ).status_code == 200
    assert client.post(
        "/subjects/0/manual/add",
        data={"teacher": "سامي", "track": "ع1", "section_csv": "2"},
    ).status_code == 200
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
