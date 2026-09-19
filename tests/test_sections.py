"""شريط عدد الشعب لكل صف."""

from __future__ import annotations


def test_update_section_count(client, store):
    r = client.post("/sections/ع1", data={"count": "5"})
    assert r.status_code == 200
    assert store.data["sections"]["ع1"] == 5
    assert store.dirty


def test_update_unknown_grade(client):
    r = client.post("/sections/UNKNOWN", data={"count": "3"})
    assert r.status_code == 404


def test_update_negative_rejected(client):
    r = client.post("/sections/ع1", data={"count": "-1"})
    assert r.status_code == 422  # Form validator (ge=0)
