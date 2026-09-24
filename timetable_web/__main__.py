"""Entry point: python -m timetable_web

يقرأ المضيف والمنفذ من متغيرات بيئة اختيارية (لنشر الإنتاج خلف بروكسي
عكسي على منفذ مختلف)، مع الحفاظ على نفس السلوك الافتراضي المحلي السابق
(127.0.0.1:8000) إن لم تُضبَط.
"""

from __future__ import annotations

import os

import uvicorn

from .app import create_app


def main() -> None:
    host = os.environ.get("TIMETABLE_HOST", "127.0.0.1")
    port = int(os.environ.get("TIMETABLE_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
