from openpyxl import load_workbook

from timetable_web.core import scheduler, xlsx_gen


def test_xlsx_sections_and_teachers(tmp_path, tiny_data):
    _s, sched, _n, _f = scheduler.solve_timetable(tiny_data, max_time_in_seconds=10, num_workers=2)
    paths = xlsx_gen.generate_xlsx_files(tiny_data, sched, tmp_path)
    sec = load_workbook(paths["برنامج الشعب (Excel)"])
    assert len(sec.sheetnames) == 2
    vals = [c.value for row in sec.worksheets[0].iter_rows(min_row=4) for c in row if c.value]
    assert any("الرياضيات" in str(v) and "أحمد" in str(v) for v in vals)
    teach = load_workbook(paths["برنامج الأساتذة (Excel)"])
    assert set(teach.sheetnames) == {"أحمد", "بشير"}


def test_shortened_day_cells_are_greyed(tmp_path, tiny_data):
    tiny_data["meta"]["periods_per_day_override"] = {"الثلاثاء": 2}
    tiny_data["subjects"][0]["periods"] = {"ع1": 2, "ع2": 2}
    tiny_data["subjects"][1]["periods"] = {"ع1": 2, "ع2": 2}
    _s, sched, _n, _f = scheduler.solve_timetable(tiny_data, max_time_in_seconds=10, num_workers=2)
    paths = xlsx_gen.generate_xlsx_files(tiny_data, sched, tmp_path)
    ws = load_workbook(paths["برنامج الشعب (Excel)"]).worksheets[0]
    assert ws.cell(4 + 3, 4).fill.fgColor.rgb.endswith("C7C7C7")
    assert ws.cell(4 + 3, 4).value is None
