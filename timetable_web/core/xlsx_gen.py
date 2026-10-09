"""تصدير برنامج الشعب وبرنامج الأساتذة إلى Excel (ورقة لكل شعبة / لكل أستاذ)."""

from __future__ import annotations

import pathlib
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from . import scheduler

_BAD = re.compile(r'[\\/*?:\[\]]')
_THIN = Side(style="thin", color="999999")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
_PERIOD_FILL = PatternFill("solid", fgColor="EEF2F7")
_OFF_FILL = PatternFill("solid", fgColor="C7C7C7")


def _sheet_name(wb, base):
    base = _BAD.sub("-", base).strip()[:31] or "ورقة"
    name, i = base, 2
    while name in wb.sheetnames:
        suffix = f" ({i})"
        name = base[:31 - len(suffix)] + suffix
        i += 1
    return name


def _write_grid(ws, title, days, ppd, real_counts, cell_text):
    ws.sheet_view.rightToLeft = True
    ws.cell(1, 1, title).font = Font(bold=True, size=14)
    ws.cell(1, 1).alignment = Alignment(horizontal="right")
    ws.cell(3, 1, "الحصة")
    for c, day in enumerate(days, start=2):
        ws.cell(3, c, day)
    for c in range(1, len(days) + 2):
        h = ws.cell(3, c)
        h.font = Font(bold=True, color="FFFFFF")
        h.fill = _HEAD_FILL
        h.alignment = Alignment(horizontal="center", vertical="center")
        h.border = _BORDER
    for p in range(ppd):
        r = 4 + p
        pc = ws.cell(r, 1, p + 1)
        pc.font = Font(bold=True)
        pc.fill = _PERIOD_FILL
        pc.alignment = Alignment(horizontal="center", vertical="center")
        pc.border = _BORDER
        ws.row_dimensions[r].height = 42
        for d in range(len(days)):
            cell = ws.cell(r, d + 2)
            cell.border = _BORDER
            cell.alignment = Alignment(
                horizontal="center", vertical="center", wrap_text=True)
            if p >= real_counts[d]:
                cell.fill = _OFF_FILL
            else:
                cell.value = cell_text(d, p)
    ws.column_dimensions["A"].width = 8
    for c in range(len(days)):
        ws.column_dimensions[chr(ord("B") + c)].width = 24


def generate_xlsx_files(data, section_sched, out_dir):
    """Returns {label: path} for برنامج_الشعب.xlsx and برنامج_الأساتذة.xlsx."""
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    days = data["meta"]["days"]
    ppd = data["meta"]["periods_per_day"]
    real = [scheduler.day_period_count(data, d) for d in days]
    labels = data["meta"]["grade_labels"]
    section_ids = scheduler.build_section_ids(data)
    school = (data["meta"].get("school_name") or "").strip()
    prefix = f"{school} — " if school else ""

    wb = Workbook()
    wb.remove(wb.active)
    for track, s in section_ids:
        cells = section_sched[f"{track}|{s}"]
        title = f"{prefix}{labels.get(track, track)} — الشعبة {s}"

        def text(d, p, cells=cells):
            c = cells[d * ppd + p]
            if not c:
                return None
            return c["subject"] + (f"\n{c['teacher']}" if c["teacher"] else "")

        ws = wb.create_sheet(_sheet_name(wb, f"{labels.get(track, track)} {s}"))
        _write_grid(ws, title, days, ppd, real, text)
    sections_path = out_dir / "برنامج_الشعب.xlsx"
    wb.save(sections_path)

    teacher_grids = {}
    for track, s in section_ids:
        for idx, c in enumerate(section_sched[f"{track}|{s}"]):
            if c and c["teacher"]:
                g = teacher_grids.setdefault(c["teacher"], {})
                g[idx] = f"{c['subject']}\n{labels.get(track, track)} / ش{s}"
    wb2 = Workbook()
    wb2.remove(wb2.active)
    for tname in sorted(teacher_grids):
        grid = teacher_grids[tname]
        total = len(grid)
        ws = wb2.create_sheet(_sheet_name(wb2, tname))
        _write_grid(
            ws, f"{prefix}{tname} — إجمالي الحصص الأسبوعية: {total}", days, ppd, real,
            lambda d, p, grid=grid: grid.get(d * ppd + p))
    teachers_path = out_dir / "برنامج_الأساتذة.xlsx"
    wb2.save(teachers_path)

    return {
        "برنامج الشعب (Excel)": str(sections_path),
        "برنامج الأساتذة (Excel)": str(teachers_path),
    }
