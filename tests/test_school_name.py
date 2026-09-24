"""اختبارات ميزة "اسم المدرسة" — الإنشاء، التعديل، الظهور في الشريط، PDF."""

from __future__ import annotations


def test_school_name_defaults_empty_after_load(store):
    assert store.data["meta"]["school_name"] == ""


def test_admin_creates_supervisor_with_school_name(admin_client, tmp_workspace):
    r = admin_client.post("/admin/users/create", data={
        "username": "school_with_name", "password": "pw123456",
        "school_name": "مدرسة النور الخاصة",
        "periods_per_day": "6", "nisab_reference": "18",
        "day_الأحد": "on", "day_الاثنين": "on",
    }, follow_redirects=False)
    assert r.status_code == 303

    import json
    created = json.loads((tmp_workspace["schools_dir"] / "school_with_name.json").read_text(encoding="utf-8"))
    assert created["meta"]["school_name"] == "مدرسة النور الخاصة"


def test_admin_creates_supervisor_without_school_name_is_empty(admin_client, tmp_workspace):
    r = admin_client.post("/admin/users/create", data={
        "username": "school_no_name", "password": "pw123456",
        "periods_per_day": "6", "nisab_reference": "18",
        "day_الأحد": "on",
    }, follow_redirects=False)
    assert r.status_code == 303

    import json
    created = json.loads((tmp_workspace["schools_dir"] / "school_no_name.json").read_text(encoding="utf-8"))
    assert created["meta"]["school_name"] == ""


def test_admin_users_page_shows_school_name_column(admin_client, tmp_workspace):
    admin_client.post("/admin/users/create", data={
        "username": "named_school", "password": "pw123456",
        "school_name": "مدرسة الأمل",
        "periods_per_day": "6", "nisab_reference": "18",
        "day_الأحد": "on",
    })
    r = admin_client.get("/admin")
    assert r.status_code == 200
    assert "مدرسة الأمل" in r.text


def test_supervisor_can_update_school_name(client, store):
    r = client.post("/file/school-name", data={"name": "مدرسة الرجاء"})
    assert r.status_code == 200
    assert store.data["meta"]["school_name"] == "مدرسة الرجاء"
    assert store.dirty is True


def test_supervisor_update_school_name_strips_whitespace(client, store):
    client.post("/file/school-name", data={"name": "  مدرسة بمسافات  "})
    assert store.data["meta"]["school_name"] == "مدرسة بمسافات"


def test_school_name_persists_after_save(client, store, tmp_workspace):
    client.post("/file/school-name", data={"name": "مدرسة محفوظة"})
    client.post("/file/save")
    import json
    saved = json.loads(tmp_workspace["test_file"].read_text(encoding="utf-8"))
    assert saved["meta"]["school_name"] == "مدرسة محفوظة"


def test_header_shows_school_name_badge_when_set(client, store):
    client.post("/file/school-name", data={"name": "مدرسة الشريط العلوي"})
    r = client.get("/teachers")
    assert r.status_code == 200
    assert "مدرسة الشريط العلوي" in r.text
    assert "🏫" in r.text


def test_header_shows_generic_subtitle_when_no_school_name(client):
    r = client.get("/teachers")
    assert r.status_code == 200
    assert "إدارة الخطة الدراسية وتوليد الجداول والقوائم" in r.text


def test_admin_header_never_shows_school_badge(admin_client):
    r = admin_client.get("/admin")
    assert r.status_code == 200
    assert "🏫" not in r.text


# ---------- زر الحفظ في الشريط العلوي على كل صفحة ----------

def test_save_button_visible_on_every_supervisor_page(client):
    for path in ("/", "/teachers", "/subjects", "/constraints", "/solve", "/dashboard", "/log"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert 'hx-post="/file/save"' in r.text, f"زر الحفظ غير ظاهر في {path}"


def test_save_button_not_shown_for_admin(admin_client):
    r = admin_client.get("/admin")
    assert r.status_code == 200
    assert 'hx-post="/file/save"' not in r.text


def test_dirty_dot_appears_after_mutation(client):
    # ملاحظة: نص "dirty-dot" يظهر دائماً في قاعدة CSS داخل <style>، لذا
    # نتحقق من العنصر الفعلي <span class="dirty-dot" الذي يُطبَع شرطياً فقط.
    marker = '<span class="dirty-dot"'
    r = client.get("/teachers")
    assert marker not in r.text  # fresh load from disk, not dirty yet

    client.post("/teachers/add", data={"name": "أستاذ جديد للاختبار"})
    r = client.get("/teachers")
    assert marker in r.text


# ---------- PDF: لا يجب أن يتسبب اسم المدرسة بأي خطأ في التوليد ----------

def test_constraints_report_pdf_with_school_name_does_not_crash(client, tmp_workspace):
    client.post("/file/school-name", data={"name": "مدرسة تقرير القيود"})
    client.post(
        "/constraints/defaults/max_gap_windows",
        data={"enabled": "on", "max": "1"},
    )
    r = client.post("/solve/constraints-report")
    assert r.status_code == 200
    files = list(tmp_workspace["output_dir"].glob("*.pdf"))
    assert any("تقرير_الشروط" in p.name for p in files)
    # تأكد أن الملف PDF فعلاً وأن حجمه معقول (لم يتعطّل التوليد بصمت)
    pdf = next(p for p in files if "تقرير_الشروط" in p.name)
    assert pdf.stat().st_size > 500
