"""شريط "عدد الشعب لكل صف" — SectionsEditor equivalent.

عند تقليل عدد الشعب لصف معين، يقوم برنامج التنظيف التلقائي بـ:
  1. إزالة أرقام الشعب المُلغاة (> العدد الجديد) من كل الإسنادات الإجبارية.
  2. إزالة أي إسناد يدوي أصبح فارغاً (لم يبقَ فيه شعبة صالحة).
  3. تسجيل كل التغييرات في سجل العمليات.

الأنصبة (نصاب كل أستاذ) لا تحتاج تحديثاً يدوياً — تُحسَب دائماً على الطاير
من subject.periods[grade] × sections[grade] عبر scheduler.teacher_current_periods.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pathlib import Path

from ..state.store import get_store

BASE_DIR = Path(__file__).resolve().parent.parent

router = APIRouter(prefix="/sections", tags=["sections"])


def _cleanup_manual_assignments(data: dict, grade: str, new_count: int) -> list[str]:
    """يمسح الشعب الملغاة من إسنادات الأساتذة. يعيد قائمة رسائل تلخّص ما جرى."""
    messages: list[str] = []
    for subj in data.get("subjects", []):
        manual = subj.get("manual_assignments", [])
        remaining: list[dict] = []
        for m in manual:
            if m.get("track") != grade:
                remaining.append(m)
                continue
            original = list(m.get("sections", []))
            filtered = [s for s in original if s <= new_count]
            dropped = sorted(set(original) - set(filtered))
            if not filtered:
                messages.append(
                    f"أُلغي إسناد كامل: {m['teacher']} في {subj['name']} — "
                    f"لأنه كان مقتصراً على شعب مُلغاة {dropped}"
                )
            else:
                if dropped:
                    messages.append(
                        f"أُزيلت الشعب {dropped} من إسناد {m['teacher']} في "
                        f"{subj['name']} · {grade}"
                    )
                remaining.append({**m, "sections": filtered})
        subj["manual_assignments"] = remaining
    return messages


@router.post("/{grade}", response_class=HTMLResponse)
def update(grade: str, request: Request, count: int = Form(..., ge=0, le=99)) -> HTMLResponse:
    store = get_store()
    if store.data is None:
        raise HTTPException(400, "لا يوجد ملف محمَّل")
    if grade not in store.data.get("sections", {}):
        raise HTTPException(404, f"صف غير معروف: {grade}")

    old_count = store.data["sections"][grade]
    store.data["sections"][grade] = count

    cleanup_msgs: list[str] = []
    if count < old_count:
        cleanup_msgs = _cleanup_manual_assignments(store.data, grade, count)
        for msg in cleanup_msgs:
            store.log(msg)

    store.mark_dirty()
    store.log(f"عدد شعب {grade} أصبح {count} (كان {old_count})")

    if cleanup_msgs:
        details = "".join(f"<li>{m}</li>" for m in cleanup_msgs)
        return HTMLResponse(
            f'<span class="ok-mark" title="{len(cleanup_msgs)} تعديل تلقائي" '
            f'style="color:#b45309;">✓ ({len(cleanup_msgs)} تنظيف)</span>'
        )
    return HTMLResponse('<span class="ok-mark">✓</span>')
