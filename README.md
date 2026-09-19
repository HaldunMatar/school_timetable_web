# نسخة الويب — برنامج توزيع الأساتذة والحصص

نسخة ويب من نفس البرنامج، مبنية على FastAPI + Jinja2 + HTMX، تحمل **نفس محرك CP-SAT** وتوليد PDF من `app/` (منسوخَين إلى `timetable_web/core/`).

مشروع منفصل عن `../app/` تماماً — لا تعتمد الواجهة القديمة على هذا، ولا العكس.

## الاختبارات

```bash
pip install -e ".[dev]"
pytest              # كل شيء (77 اختباراً)
pytest -m "not slow"  # بلا اختبار CP-SAT الكامل
```

**التغطية:** 8 ملفات اختبار تغطي كل مسار في التطبيق — smoke + teachers + subjects + sections + constraints + solve (بلا وبمع CP-SAT) + files. البيانات معزولة في `tmp_path` والـ store يُعاد إنشاؤه من الصفر لكل اختبار.

## التشغيل

```bash
cd web
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m timetable_web
```

يفتح على `http://127.0.0.1:8000` — افتحه في أي متصفح.

## البنية

```
web/
├── timetable_web/
│   ├── core/           # نسخة من app/scheduler.py و app/pdf_gen.py
│   ├── state/          # حالة الملف المحمَّل حالياً (in-memory)
│   ├── routers/        # مسارات FastAPI لكل تبويب
│   ├── templates/      # Jinja + HTMX
│   └── static/         # CSS + htmx.min.js + الخطوط
├── data/               # school_data_default.json (البذرة الافتراضية)
├── assets/fonts/       # Amiri للـ PDF
└── output/             # مكان حفظ PDFs المولَّدة
```
