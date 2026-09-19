"""اختبارات نظام الحسابات — تسجيل الدخول، التفعيل، صلاحيات المدير."""

from __future__ import annotations


def test_root_requires_login(anon_client):
    r = anon_client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_page_public(anon_client):
    r = anon_client.get("/login")
    assert r.status_code == 200
    assert "تسجيل الدخول" in r.text


def test_healthz_public(anon_client):
    r = anon_client.get("/healthz")
    assert r.status_code == 200


def test_bad_login(anon_client):
    r = anon_client.post("/login", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    assert "غير صحيحة" in r.text


def test_admin_login_redirects_to_admin(anon_client):
    r = anon_client.post("/login", data={"username": "admin", "password": "admin"},
                         follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/admin"


def test_supervisor_login_redirects_home(anon_client):
    r = anon_client.post("/login", data={"username": "test_supervisor", "password": "test_pw"},
                         follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_supervisor_forbidden_from_admin(client):
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 403


def test_admin_forbidden_from_supervisor_data(admin_client):
    # Admin has no data — get_store() raises 400
    r = admin_client.get("/teachers")
    assert r.status_code == 400
    assert "المدير" in r.text or "بيانات مدرسة" in r.text


def test_admin_can_view_users_page(admin_client):
    r = admin_client.get("/admin")
    assert r.status_code == 200
    assert "إدارة المشرفين" in r.text
    assert "test_supervisor" in r.text


def test_admin_creates_supervisor(admin_client, tmp_workspace):
    r = admin_client.post("/admin/users/create", data={
        "username": "school_two", "password": "another_pw",
        "periods_per_day": "6", "nisab_reference": "18",
        "day_الأحد": "on", "day_الاثنين": "on",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert (tmp_workspace["schools_dir"] / "school_two.json").exists()

    from timetable_web.auth import find_user
    u = find_user("school_two")
    assert u is not None
    assert u.role == "supervisor"
    assert u.active is True


def test_admin_toggle_activation(admin_client):
    from timetable_web.auth import find_user
    assert find_user("test_supervisor").active is True
    admin_client.post("/admin/users/test_supervisor/toggle", follow_redirects=False)
    assert find_user("test_supervisor").active is False
    admin_client.post("/admin/users/test_supervisor/toggle", follow_redirects=False)
    assert find_user("test_supervisor").active is True


def test_deactivated_user_gets_inactive_page(admin_client, tmp_workspace):
    # deactivate the supervisor
    admin_client.post("/admin/users/test_supervisor/toggle", follow_redirects=False)

    # now login as supervisor from a separate client
    from fastapi.testclient import TestClient
    from timetable_web.app import create_app
    app = create_app()
    with TestClient(app) as sup:
        sup.post("/login", data={"username": "test_supervisor", "password": "test_pw"})
        r = sup.get("/")
        assert r.status_code == 403
        assert "غير مفعَّل" in r.text


def test_admin_reset_password(admin_client):
    admin_client.post("/admin/users/test_supervisor/reset-password",
                      data={"password": "new_password"}, follow_redirects=False)
    from timetable_web.auth import find_user, verify_password
    u = find_user("test_supervisor")
    assert verify_password(u, "new_password")
    assert not verify_password(u, "test_pw")


def test_admin_delete_supervisor(admin_client, tmp_workspace):
    admin_client.post("/admin/users/test_supervisor/delete",
                      data={"also_delete_data": "on"}, follow_redirects=False)
    from timetable_web.auth import find_user
    assert find_user("test_supervisor") is None
    assert not (tmp_workspace["schools_dir"] / "test.json").exists()


def test_admin_cannot_delete_admin(admin_client):
    r = admin_client.post("/admin/users/admin/delete", follow_redirects=False)
    assert r.status_code == 400


def test_logout(client):
    r = client.get("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_admin_replaces_supervisor_data(admin_client, tmp_workspace, tiny_data):
    """المدير يستبدل ملف بيانات المشرف — المشرف يعتمد الجديد فوراً."""
    import json
    from timetable_web.state.store import _stores

    # 1. المشرف يعمل تغييراً أولاً (لتفعيل كاش Store له)
    from fastapi.testclient import TestClient
    from timetable_web.app import create_app
    app = create_app()
    with TestClient(app) as sup:
        sup.post("/login", data={"username": "test_supervisor", "password": "test_pw"})
        sup.get("/teachers")  # يحمّل الـ store
        assert "test_supervisor" in _stores

    # 2. المدير يرفع ملفاً جديداً بمواد مختلفة
    replacement = {**tiny_data,
                   "subjects": [{**tiny_data["subjects"][0], "name": "مادة_مستبدَلة"}],
                   "teachers": ["أحمد"]}
    payload = json.dumps(replacement, ensure_ascii=False).encode("utf-8")
    r = admin_client.post(
        "/admin/users/test_supervisor/upload-data",
        files={"file": ("new_data.json", payload, "application/json")},
        follow_redirects=False,
    )
    assert r.status_code == 303

    # 3. كاش المشرف مُسِح (drop_store)
    assert "test_supervisor" not in _stores

    # 4. الملف على القرص فعلاً تحدَّث
    disk = json.loads(tmp_workspace["test_file"].read_text(encoding="utf-8"))
    assert disk["subjects"][0]["name"] == "مادة_مستبدَلة"

    # 5. الطلب التالي من المشرف يقرأ الملف الجديد
    with TestClient(app) as sup:
        sup.post("/login", data={"username": "test_supervisor", "password": "test_pw"})
        r = sup.get("/subjects")
        assert "مادة_مستبدَلة" in r.text
        assert "الرياضيات" not in r.text  # القديم اختفى


def test_admin_upload_rejects_invalid_json(admin_client):
    r = admin_client.post(
        "/admin/users/test_supervisor/upload-data",
        files={"file": ("bad.json", b"not-json", "application/json")},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_admin_upload_rejects_missing_required_fields(admin_client):
    import json
    payload = json.dumps({"only": "junk"}).encode("utf-8")
    r = admin_client.post(
        "/admin/users/test_supervisor/upload-data",
        files={"file": ("bad.json", payload, "application/json")},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "meta" in r.text or "sections" in r.text or "subjects" in r.text


def test_admin_download_supervisor_data(admin_client):
    r = admin_client.get("/admin/users/test_supervisor/download-data")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    import json
    body = json.loads(r.content.decode("utf-8"))
    assert "meta" in body and "subjects" in body


def test_admin_upload_requires_admin(client):
    """مشرف لا يستطيع رفع بيانات لأحد آخر."""
    import json
    payload = json.dumps({}).encode("utf-8")
    r = client.post(
        "/admin/users/test_supervisor/upload-data",
        files={"file": ("x.json", payload, "application/json")},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_supervisor_data_is_isolated(admin_client, tmp_workspace):
    # Create a second supervisor
    admin_client.post("/admin/users/create", data={
        "username": "sup_b", "password": "pw_b",
        "periods_per_day": "5", "nisab_reference": "15",
        "day_الأحد": "on",
    }, follow_redirects=False)

    # Log in as sup_b and verify they see their own (empty) subjects, not test_supervisor's
    from fastapi.testclient import TestClient
    from timetable_web.app import create_app
    app = create_app()
    with TestClient(app) as sup_b:
        sup_b.post("/login", data={"username": "sup_b", "password": "pw_b"})
        r = sup_b.get("/subjects")
        assert r.status_code == 200
        # Fresh school has 0 subjects; supervisor_1 has 2 (الرياضيات + اللغة)
        assert "الرياضيات" not in r.text
        assert "اللغة" not in r.text
