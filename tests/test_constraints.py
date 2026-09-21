"""تبويب قيود الجدولة."""

from __future__ import annotations

import urllib.parse


TEACHER = "أحمد"
TEACHER_ENC = urllib.parse.quote(TEACHER, safe="")


def test_index_no_teacher(client):
    r = client.get("/constraints")
    assert r.status_code == 200
    assert "الإعدادات الافتراضية العامة" in r.text
    assert "اختر أستاذاً" in r.text


def test_index_with_teacher(client):
    r = client.get("/constraints", params={"teacher": TEACHER})
    assert r.status_code == 200
    assert TEACHER in r.text
    assert "النصاب الحالي" in r.text


def test_teacher_panel_partial(client):
    r = client.get(f"/constraints/teacher/{TEACHER}/panel")
    assert r.status_code == 200
    assert "خصّص هذا القيد لهذا الأستاذ" in r.text


def test_update_default_max_gap(client, store):
    r = client.post(
        "/constraints/defaults/max_gap_windows",
        data={"enabled": "on", "max": "2"},
    )
    assert r.status_code == 200
    g = store.data["scheduling_constraints"]["defaults"]["max_gap_windows"]
    assert g["enabled"] is True
    assert g["max"] == 2


def test_update_default_day_off_specific(client, store):
    r = client.post(
        "/constraints/defaults/day_off",
        data={"enabled": "on", "mode": "specific", "day_الأحد": "on", "day_الاثنين": "on"},
    )
    assert r.status_code == 200
    g = store.data["scheduling_constraints"]["defaults"]["day_off"]
    assert g["enabled"] is True
    assert g["mode"] == "specific"
    assert "الأحد" in g["days"]
    assert "الاثنين" in g["days"]


def test_update_default_day_off_random(client, store):
    r = client.post(
        "/constraints/defaults/day_off",
        data={"enabled": "on", "mode": "random", "count": "2"},
    )
    assert r.status_code == 200
    g = store.data["scheduling_constraints"]["defaults"]["day_off"]
    assert g["mode"] == "random"
    assert g["count"] == 2


def test_update_default_empty_periods(client, store):
    r = client.post(
        "/constraints/defaults/empty_periods",
        data={
            "enabled": "on",
            "start_enabled": "on", "start_count": "1",
            "end_enabled": "on",   "end_count": "2",
            "days_mode": "all",
        },
    )
    assert r.status_code == 200
    g = store.data["scheduling_constraints"]["defaults"]["empty_periods"]
    assert g["start"]["enabled"] is True
    assert g["end"]["count"] == 2
    assert g["days_mode"] == "all"


def test_teacher_override_toggle_on_then_off(client, store):
    # ON → override created
    r = client.post(
        f"/constraints/teacher/{TEACHER}/max_gap_windows/override",
        data={"on": "on"},
    )
    assert r.status_code == 200
    per = store.data["scheduling_constraints"]["per_teacher"]
    assert TEACHER in per
    assert "max_gap_windows" in per[TEACHER]

    # OFF → override removed
    r = client.post(
        f"/constraints/teacher/{TEACHER}/max_gap_windows/override",
        data={},  # no "on" field
    )
    assert r.status_code == 200
    per = store.data["scheduling_constraints"]["per_teacher"]
    # per_teacher[TEACHER] should be deleted when its last override is removed
    assert TEACHER not in per or "max_gap_windows" not in per.get(TEACHER, {})


def test_teacher_update_requires_active_override(client):
    # No override active → update endpoint refuses
    r = client.post(
        f"/constraints/teacher/{TEACHER}/max_gap_windows",
        data={"enabled": "on", "max": "3"},
    )
    assert r.status_code == 400


def test_empty_periods_specific_per_day_defaults(client, store):
    """كل يوم بعدده الخاص: الأحد تفريغ 2 من البداية، الاثنين تفريغ 3 من النهاية."""
    r = client.post(
        "/constraints/defaults/empty_periods",
        data={
            "enabled": "on",
            "days_mode": "specific",
            "day_الأحد_start_enabled": "on", "day_الأحد_start_count": "2",
            "day_الاثنين_end_enabled": "on", "day_الاثنين_end_count": "3",
        },
    )
    assert r.status_code == 200
    g = store.data["scheduling_constraints"]["defaults"]["empty_periods"]
    assert g["enabled"] is True
    assert g["days_mode"] == "specific"
    assert set(g["days"]) == {"الأحد", "الاثنين"}
    assert g["per_day"]["الأحد"]["start"] == {"enabled": True, "count": 2}
    assert g["per_day"]["الأحد"]["end"] == {"enabled": False, "count": 1}
    assert g["per_day"]["الاثنين"]["end"] == {"enabled": True, "count": 3}
    assert g["per_day"]["الاثنين"]["start"] == {"enabled": False, "count": 1}
    # اليوم الثالث (الثلاثاء) لم يُفعَّل فيه شيء -> لا يظهر في per_day إطلاقاً
    assert "الثلاثاء" not in g["per_day"]


def test_empty_periods_specific_per_day_response_reflects_values(client):
    """الرد المُعاد بعد الحفظ يعرض القيم الصحيحة لكل يوم في جدول per-day."""
    r = client.post(
        "/constraints/defaults/empty_periods",
        data={
            "enabled": "on",
            "days_mode": "specific",
            "day_الأحد_start_enabled": "on", "day_الأحد_start_count": "2",
        },
    )
    assert r.status_code == 200
    assert 'name="day_الأحد_start_count" value="2"' in r.text
    assert 'name="day_الأحد_start_enabled"  checked' in r.text or 'name="day_الأحد_start_enabled" checked' in r.text


def test_empty_periods_switching_back_to_all_clears_per_day(client, store):
    """الرجوع من 'أيام محددة' إلى 'كل الأيام' يمسح per_day تماماً."""
    client.post(
        "/constraints/defaults/empty_periods",
        data={
            "enabled": "on", "days_mode": "specific",
            "day_الأحد_start_enabled": "on", "day_الأحد_start_count": "2",
        },
    )
    r = client.post(
        "/constraints/defaults/empty_periods",
        data={"enabled": "on", "days_mode": "all", "start_enabled": "on", "start_count": "1"},
    )
    assert r.status_code == 200
    g = store.data["scheduling_constraints"]["defaults"]["empty_periods"]
    assert g["days_mode"] == "all"
    assert g["per_day"] == {}
    assert g["days"] == []
    assert g["start"] == {"enabled": True, "count": 1}


def test_empty_periods_per_day_for_teacher_override(client, store):
    """نفس ميزة اليوم المخصَّص تعمل أيضاً على مستوى تخصيص أستاذ معيّن."""
    client.post(f"/constraints/teacher/{TEACHER_ENC}/empty_periods/override", data={"on": "on"})
    r = client.post(
        f"/constraints/teacher/{TEACHER_ENC}/empty_periods",
        data={
            "enabled": "on", "days_mode": "specific",
            "day_الثلاثاء_start_enabled": "on", "day_الثلاثاء_start_count": "1",
            "day_الثلاثاء_end_enabled": "on", "day_الثلاثاء_end_count": "2",
        },
    )
    assert r.status_code == 200
    g = store.data["scheduling_constraints"]["per_teacher"][TEACHER]["empty_periods"]
    assert g["per_day"]["الثلاثاء"] == {
        "start": {"enabled": True, "count": 1},
        "end": {"enabled": True, "count": 2},
    }


def test_defaults_response_never_returns_disabled_fields(client):
    """Regression: كان تفعيل قيد افتراضي يُعيد كل الحقول التحتية disabled بالخطأ."""
    r = client.post(
        "/constraints/defaults/empty_periods",
        data={"enabled": "on", "start_count": "1", "end_count": "1", "days_mode": "all"},
    )
    assert r.status_code == 200
    # الرد يجب ألا يحوي 'disabled' في أي input — نحن في لوحة الافتراضيات
    assert "disabled" not in r.text, "توجد حقول disabled في رد لوحة الافتراضيات (bug: يجمد من تحته)"


def test_teacher_response_disables_fields_when_no_override(client):
    """Regression: في لوحة الأستاذ بلا تخصيص، الحقول يجب أن تكون disabled."""
    r = client.get(f"/constraints/teacher/{TEACHER_ENC}/panel")
    assert r.status_code == 200
    assert "disabled" in r.text, "لوحة الأستاذ بلا تخصيص يجب أن تعطّل الحقول"


def test_teacher_save_after_override(client, store):
    client.post(
        f"/constraints/teacher/{TEACHER}/max_gap_windows/override",
        data={"on": "on"},
    )
    r = client.post(
        f"/constraints/teacher/{TEACHER}/max_gap_windows",
        data={"enabled": "on", "max": "4"},
    )
    assert r.status_code == 200
    per_teacher_group = store.data["scheduling_constraints"]["per_teacher"][TEACHER]["max_gap_windows"]
    assert per_teacher_group["max"] == 4
