"""Smoke tests — every GET page renders 200 with expected Arabic content."""

from __future__ import annotations

import pytest


ALL_PAGES = [
    ("/", "الرئيسية"),
    ("/healthz", "ok"),
    ("/teachers", "قائمة الأساتذة"),
    ("/teachers/rows", "أحمد"),
    ("/subjects", "البيانات"),
    ("/subjects/0", "البيانات"),
    ("/subjects/0/editor", "تعديل المادة"),
    ("/constraints", "قيود الجدولة"),
    ("/solve", "التوليد"),
    ("/solve/status", "الحالة"),
    ("/dashboard", "لوحة المعلومات"),
    ("/log", "سجل العمليات"),
    ("/log/tail", ""),         # may be empty div
]


@pytest.mark.parametrize("path,needle", ALL_PAGES)
def test_get_ok(client, path, needle):
    r = client.get(path)
    assert r.status_code == 200, f"{path} failed: {r.text[:300]}"
    if needle:
        assert needle in r.text, f"{needle!r} not in response for {path}"


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_static_htmx_served(client):
    r = client.get("/static/htmx.min.js")
    assert r.status_code == 200
    assert "htmx" in r.text.lower()


def test_static_css_served(client):
    r = client.get("/static/app.css")
    assert r.status_code == 200
    assert "--accent" in r.text
