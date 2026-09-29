"""لوحة الأدمن الكبير: ضبط أستاذ (أساتذة) مفضَّلين لمدرسة مشرف معيّن -
تفضيل خفيف في تحقيق الرغبات عند التوليد (انظر test_priority_teacher.py
لاختبارات محرك الحل نفسه). tiny_data تحوي أساتذة: أحمد، بشير."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def test_admin_sets_priority_teacher(admin_client, tmp_workspace):
    r = admin_client.post(
        "/admin/users/test_supervisor/priority-teachers",
        data={"priority_teachers": ["أحمد"]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    disk = json.loads(tmp_workspace["test_file"].read_text(encoding="utf-8"))
    assert disk["priority_teachers"] == ["أحمد"]


def test_admin_can_clear_priority_teachers(admin_client, tmp_workspace):
    admin_client.post(
        "/admin/users/test_supervisor/priority-teachers",
        data={"priority_teachers": ["أحمد"]},
    )
    r = admin_client.post(
        "/admin/users/test_supervisor/priority-teachers",
        data={},  # لا شيء مُحدَّد - يمسح التفضيل بالكامل
        follow_redirects=False,
    )
    assert r.status_code == 303
    disk = json.loads(tmp_workspace["test_file"].read_text(encoding="utf-8"))
    assert disk["priority_teachers"] == []


def test_admin_priority_teachers_ignores_unknown_name(admin_client, tmp_workspace):
    r = admin_client.post(
        "/admin/users/test_supervisor/priority-teachers",
        data={"priority_teachers": ["أحمد", "اسم_غير_موجود"]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    disk = json.loads(tmp_workspace["test_file"].read_text(encoding="utf-8"))
    assert disk["priority_teachers"] == ["أحمد"]  # الاسم غير الموجود تجاهُلاً، لا خطأ


def test_admin_priority_teachers_drops_supervisor_cache(admin_client, tmp_workspace):
    """المشرف يقرأ التفضيل الجديد فوراً في الطلب التالي، بلا إعادة تسجيل دخول."""
    from timetable_web.state.store import _stores
    from timetable_web.app import create_app

    with TestClient(create_app()) as sup:
        sup.post("/login", data={"username": "test_supervisor", "password": "test_pw"})
        sup.get("/teachers")  # يحمّل الـ store
        assert "test_supervisor" in _stores

    admin_client.post(
        "/admin/users/test_supervisor/priority-teachers",
        data={"priority_teachers": ["بشير"]},
    )
    assert "test_supervisor" not in _stores


def test_priority_teachers_requires_admin(client):
    r = client.post(
        "/admin/users/test_supervisor/priority-teachers",
        data={"priority_teachers": ["أحمد"]},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_admin_page_shows_priority_dialog_with_teacher_checkboxes(admin_client):
    r = admin_client.get("/admin")
    assert r.status_code == 200
    assert "أستاذ مفضَّل" in r.text
    assert 'name="priority_teachers"' in r.text
    assert 'value="أحمد"' in r.text
