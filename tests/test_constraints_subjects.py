"""قسم قيود المواد في صفحة /constraints."""

from __future__ import annotations


def test_constraints_page_lists_subjects(client):
    r = client.get("/constraints")
    assert r.status_code == 200
    assert "قيود المواد" in r.text
    # المواد من tiny_data يجب أن تظهر
    assert "الرياضيات" in r.text
    assert "اللغة" in r.text
    # كل مادة لها القيدان
    assert "max_consecutive_per_day" in r.text
    assert "max_daily_per_section" in r.text


def test_subject_constraint_saves_via_htmx_endpoint(client, store):
    """تفعيل max_consecutive_per_day عبر الـ endpoint الذي يستدعيه HTMX من قسم قيود المواد."""
    r = client.post(
        "/subjects/0/constraint/max_consecutive_per_day",
        data={"enabled": "on", "max_value": "3"},
    )
    assert r.status_code == 200
    c = store.data["subjects"][0]["constraints"]["max_consecutive_per_day"]
    assert c["enabled"] is True
    assert c["max"] == 3
