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
