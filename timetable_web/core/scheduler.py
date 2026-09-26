"""
Core scheduling engine.

Given the school data (sections per grade, subjects with per-grade periods
and a list of teacher names), this module:

1. Packs each subject's required weekly periods into slots for each named
   teacher of that subject, preferring to keep a teacher's sections within
   the same or nearby grades.
2. Groups the resulting (teacher, subject, grade, section, periods)
   requirements by the *real* teacher name, since the same person can teach
   more than one subject.
3. Solves a full weekly timetable (days x periods_per_day) with Google
   OR-Tools CP-SAT, respecting:
      - each subject/section pair gets exactly its required weekly periods
      - a section has at most one subject per time slot
      - a teacher is in at most one place per time slot (across ALL of
        their subjects)

No randomness is used (Date.now()/random are not needed here), so a given
input dataset always produces the same schedule.
"""

import math

from ortools.sat.python import cp_model


# The canonical 8-grade Syrian curriculum structure this app was built
# around, used as the starting point for a brand-new school file (see
# new_blank_data) - a new school still teaches the same grades, it just
# starts with no subjects/sections/teachers of its own yet.
GRADE_ORDER_TEMPLATE = ["ع1", "ع2", "ع3", "ثا1أ", "ثا1ع", "ثا2أ", "ثا2ع", "ثا3"]
GRADE_LABELS_TEMPLATE = {
    "ع1": "سابع", "ع2": "ثامن", "ع3": "تاسع",
    "ثا1أ": "عاشر أدبي", "ثا1ع": "عاشر علمي",
    "ثا2أ": "حادي عشر أدبي", "ثا2ع": "حادي عشر علمي",
    "ثا3": "بكالوريا أدبي",
}
DEFAULT_DAYS = ["الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس"]
ALL_WEEKDAYS = ["الأحد", "الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]

# Arabic ordinal words used when auto-naming placeholder teachers for small
# counts ("أستاذ اللغة العربية الثاني") - falls back to a plain number
# beyond this range rather than growing the table indefinitely.
_ARABIC_ORDINAL_WORDS = {
    1: "الأول", 2: "الثاني", 3: "الثالث", 4: "الرابع", 5: "الخامس",
    6: "السادس", 7: "السابع", 8: "الثامن", 9: "التاسع", 10: "العاشر",
    11: "الحادي عشر", 12: "الثاني عشر", 13: "الثالث عشر", 14: "الرابع عشر",
    15: "الخامس عشر", 16: "السادس عشر", 17: "السابع عشر", 18: "الثامن عشر",
    19: "التاسع عشر", 20: "العشرون",
}


def _ordinal_ar(n):
    return _ARABIC_ORDINAL_WORDS.get(n, str(n))


def new_blank_data(days, periods_per_day, nisab_reference):
    """
    Build a brand-new, empty school dataset (no subjects yet, one section
    per grade as a starting point) - used by the "ملف > مدرسة جديدة..."
    wizard. `days` is the list of school days (e.g. Sunday-Thursday),
    `periods_per_day` how many periods are in each day, and
    `nisab_reference` the default per-teacher weekly period quota used
    later by ensure_min_teachers() to size auto-generated placeholder
    teachers for any subject left without enough named teachers.
    """
    grade_order = list(GRADE_ORDER_TEMPLATE)
    return {
        "meta": {
            "days": list(days),
            "periods_per_day": int(periods_per_day),
            "grade_order": grade_order,
            "grade_labels": dict(GRADE_LABELS_TEMPLATE),
            "nisab_reference": float(nisab_reference),
        },
        "sections": {g: 1 for g in grade_order},
        "subjects": [],
        "teachers": [],
        "scheduling_constraints": {
            "defaults": {k: dict(v) for k, v in DEFAULT_TEACHER_CONSTRAINTS.items()},
            "per_teacher": {},
        },
    }


def subject_required_periods(data, subject):
    """Total weekly periods this subject needs, summed across all its sections."""
    cols = data["meta"]["grade_order"]
    sections = data["sections"]
    vals = subject["periods"]
    total = 0.0
    for c in cols:
        periods = float(vals.get(c, 0) or 0)
        if periods <= 0:
            continue
        total += periods * int(sections.get(c, 0) or 0)
    return total


def grade_period_totals(data):
    """
    Total weekly periods entered (summed across all subjects) for ONE
    section of each grade that actually has at least one section. Every
    section of the same grade needs exactly this many periods filled in
    the final timetable (a subject's periods are defined per grade, and
    apply identically to every section of that grade) - so this is the
    number to compare against periods_per_day * len(days) to know whether
    a grade's curriculum is complete yet.
    """
    cols = data["meta"]["grade_order"]
    sections = data["sections"]
    totals = {c: 0.0 for c in cols if int(sections.get(c, 0) or 0) > 0}
    for subject in data["subjects"]:
        for c in totals:
            totals[c] += float(subject["periods"].get(c, 0) or 0)
    return totals


def incomplete_grades(data):
    """
    Grades (with at least one section) whose subjects don't yet sum to
    exactly one full week (periods_per_day * len(days)) of periods - too
    few and the timetable is forced to leave slots empty for that grade,
    too many and there's no room left in the week. Returns
    [(grade, label, total, nslots), ...], sorted in grade_order, empty
    when every grade with sections lines up exactly.
    """
    cols = data["meta"]["grade_order"]
    days = data["meta"]["days"]
    periods_per_day = data["meta"]["periods_per_day"]
    nslots = len(days) * periods_per_day
    labels = data["meta"]["grade_labels"]
    totals = grade_period_totals(data)
    mismatched = []
    for grade in cols:
        if grade not in totals:
            continue
        total = totals[grade]
        if round(total) != nslots:
            mismatched.append((grade, labels.get(grade, grade), total, nslots))
    return mismatched


def ensure_min_teachers(data):
    """
    Make sure every subject that needs periods has SOMEONE to teach them.

    Two different situations, handled differently on purpose:

    - The subject already has one or more real teacher names: they are
      left alone UNLESS their combined capacity (each teacher can take at
      most one weekly slot's worth, nslots) genuinely cannot cover the
      subject's total periods - a human may deliberately staff a subject
      above or below the نصاب reference, and that legitimate choice must
      never be silently "corrected" just because the average doesn't
      match نصاب exactly. Only true infeasibility triggers a top-up.
    - The subject has NO teacher names at all: نصاب
      (data["meta"]["nisab_reference"], the target weekly periods per
      teacher) is used as a sensible default to decide how many
      placeholder teachers to invent from scratch.

    Either way, auto-generated names look like "أستاذ <المادة>
    <الأول/الثاني/...>" and are only ever ADDED, never renaming or
    removing an existing entry. Returns [(subject_name, [new names
    added]), ...] for the subjects that actually got new placeholder
    names, so a caller (e.g. the GUI) can report or refresh around it.
    """
    nisab = float(data["meta"].get("nisab_reference", 0) or 0)
    days = data["meta"]["days"]
    periods_per_day = data["meta"]["periods_per_day"]
    nslots = len(days) * periods_per_day
    added_report = []
    for subject in data["subjects"]:
        total = subject_required_periods(data, subject)
        if total <= 0:
            continue
        names = subject["names"]
        if names:
            capacity = len(names) * nslots
            if capacity >= total:
                continue
            needed = max(len(names) + 1, math.ceil(total / nslots) if nslots > 0 else len(names) + 1)
        else:
            needed = max(1, math.ceil(total / nisab)) if nisab > 0 else 1
        existing = set(names)
        roster = data.setdefault("teachers", [])
        roster_set = set(roster)
        added = []
        while len(names) < needed:
            idx = len(names) + 1
            candidate = f"أستاذ {subject['name']} {_ordinal_ar(idx)}"
            if candidate in existing:
                candidate = f"أستاذ {subject['name']} {idx}"
            names.append(candidate)
            existing.add(candidate)
            added.append(candidate)
            # Auto-generated placeholder teachers are still real entries as
            # far as the central roster is concerned - register them here
            # too, otherwise they'd be usable in this subject but invisible
            # in "قائمة الأساتذة" and unavailable for picking into any OTHER
            # subject (since that picker only ever offers roster names).
            if candidate not in roster_set:
                roster.append(candidate)
                roster_set.add(candidate)
        if added:
            added_report.append((subject["name"], added))
    return added_report


# Disabled by default, so a dataset with no "scheduling_constraints" key (or
# an older file predating this feature) behaves EXACTLY as before: no gaps,
# days off, or start/end rules are forced on anyone unless explicitly turned
# on, either for everyone (defaults) or for one named teacher (per_teacher).
#
# "day_off" supports ONE OR MORE days off per week, not just a single day:
#   - mode "specific": `days` is the explicit list of day names the user
#     picked (the number of days off IS len(days) - no separate count is
#     stored for this mode).
#   - mode "random": `count` is how many days the solver should pick
#     automatically each week (`days` is unused/ignored in this mode).
# Both fields are always present regardless of mode, purely so every
# day_off dict has the same shape everywhere in the file; only the field
# matching the current mode is actually read.
#
# "empty_periods" supports BOTH "start of day" and "end of day" emptying at
# once (independently enabled, each with its own count), and can be scoped
# to either every day or a chosen set of specific days:
#   - "start"/"end": each {"enabled": bool, "count": int} - either or both
#     may be enabled at the same time (e.g. "empty the first period AND the
#     last period of every day").
#   - "days_mode": "all" applies the SAME "start"/"end" rule(s) above to
#     every day of the week; "specific" ignores the top-level "start"/"end"
#     entirely and instead gives EACH day listed in "days" its own
#     independent start/end rule via "per_day" (e.g. empty 2 periods at the
#     start of Sunday, and 3 periods at the end of Monday, in one group).
#   - "days": the explicit list of day names actually targeted, used only
#     when days_mode == "specific" (ignored, but always present, in "all"
#     mode) - always equal to the keys of "per_day".
#   - "per_day": {day_name: {"start": {...}, "end": {...}}}, one entry per
#     day in "days", each shaped exactly like the top-level "start"/"end" -
#     used only when days_mode == "specific". Empty ({}) in "all" mode, and
#     also empty for any file saved before this per-day feature existed
#     (every day then falls back to the shared top-level "start"/"end",
#     which is exactly how "specific" mode behaved previously).
DEFAULT_TEACHER_CONSTRAINTS = {
    "empty_periods": {
        "enabled": False,
        "start": {"enabled": False, "count": 1},
        "end": {"enabled": False, "count": 1},
        "days_mode": "all",
        "days": [],
        "per_day": {},
    },
    "day_off": {"enabled": False, "mode": "specific", "days": [], "count": 1},
    "max_gap_windows": {"enabled": False, "max": 1},
    "start_from_beginning": {"enabled": False},
}


def _normalize_day_off_group(group):
    """
    Upgrade a possibly-legacy day_off dict in place to the current shape:
    old files (saved before multi-day support) store a single
    `"day": "<name>" | None` instead of `"days": [...]`. Safe to call on an
    already-current dict (no-op). Returns the same dict for convenience.
    """
    if not isinstance(group, dict):
        return group
    if "days" not in group and "day" in group:
        legacy_day = group.pop("day")
        group["days"] = [legacy_day] if legacy_day else []
    group.setdefault("days", [])
    group.setdefault("count", 1)
    return group


def _normalize_empty_periods_group(group):
    """
    Upgrade a possibly-legacy empty_periods dict to the current shape: old
    files (saved before simultaneous start+end support) store a single
    `"position": "start"|"end"` plus `"count": int`, always applied to every
    day (no day-scoping concept existed). A later generation added
    "days_mode"/"days" but no "per_day" (every specific day shared the same
    top-level start/end). Returns a NEW dict - it never mutates the dict it
    was given (or any nested dict inside it), so it is always safe to call
    on a dict that is still referenced elsewhere (e.g. live data straight
    from a loaded JSON file). Safe to call on an already-current dict too
    (no-op besides the defensive copy).
    """
    if not isinstance(group, dict):
        return group
    group = dict(group)
    if "position" in group or ("start" not in group and "end" not in group):
        legacy_position = group.pop("position", "start")
        legacy_count = group.pop("count", 1)
        group.setdefault("start", {"enabled": legacy_position == "start", "count": legacy_count})
        group.setdefault("end", {"enabled": legacy_position == "end", "count": legacy_count})
    start = dict(group.get("start") or {})
    end = dict(group.get("end") or {})
    start.setdefault("enabled", False)
    start.setdefault("count", 1)
    end.setdefault("enabled", False)
    end.setdefault("count", 1)
    group["start"] = start
    group["end"] = end
    group.setdefault("days_mode", "all")
    group.setdefault("days", [])

    # "per_day" (per-day start/end overrides, only meaningful in "specific"
    # mode): absent entirely on any file saved before this feature existed,
    # in which case every day in "days" simply falls back to the shared
    # top-level start/end above - identical to the old single-value-for-
    # every-specific-day behavior, so this is a no-op for old data.
    raw_per_day = group.get("per_day")
    per_day = {}
    if isinstance(raw_per_day, dict):
        for day_name, cfg in raw_per_day.items():
            cfg = cfg if isinstance(cfg, dict) else {}
            pd_start = dict(cfg.get("start") or {})
            pd_start.setdefault("enabled", False)
            pd_start.setdefault("count", 1)
            pd_end = dict(cfg.get("end") or {})
            pd_end.setdefault("enabled", False)
            pd_end.setdefault("count", 1)
            per_day[day_name] = {"start": pd_start, "end": pd_end}
    group["per_day"] = per_day
    return group


# Subject-level scheduling constraints (as opposed to the per-teacher ones
# above): these describe how a SUBJECT's own periods may be laid out for a
# given section, regardless of which teacher ends up teaching it. Disabled
# by default, so a subject saved before this feature existed (or with
# nothing turned on) behaves exactly as before - no extra restriction on
# top of the normal one-subject-per-slot rule.
#   - "max_consecutive_per_day": the largest number of CONSECUTIVE periods
#     of this subject allowed on the same day for the same section (e.g.
#     max 2 -> periods 3-4-5 of this subject back-to-back in one day for
#     one section is blocked, but 3-4 then a gap then 6 is fine).
#   - "max_daily_per_section": the largest TOTAL number of periods of this
#     subject allowed on the same day for the same section, whether or not
#     they are consecutive.
# Unlike the per-teacher "تفريغ حصص"/"يوم عطلة" preferences, both of these
# are HARD rules (see solve_timetable) - if honoring them turns out to be
# impossible given the subject's weekly period count for a section,
# generation fails outright (INFEASIBLE) instead of silently ignoring the
# limit, exactly like any other hard rule in this program.
DEFAULT_SUBJECT_CONSTRAINTS = {
    "max_consecutive_per_day": {"enabled": False, "max": 2},
    "max_daily_per_section": {"enabled": False, "max": 2},
}


def ensure_subject_constraints(subject):
    """
    Make sure `subject["constraints"]` has both subject-level scheduling
    constraint groups above, filling in the all-disabled defaults for
    whichever are missing (e.g. a subject saved before this feature
    existed) - without touching any value already present. Returns the
    (possibly just-created) dict, mutating `subject` in place - meant for
    the GUI's subject editor, which needs a real, persisted dict to read
    from and write into. Safe to call repeatedly.
    """
    cfg = subject.setdefault("constraints", {})
    for key, base in DEFAULT_SUBJECT_CONSTRAINTS.items():
        cfg.setdefault(key, dict(base))
    return cfg


def effective_subject_constraints(subject):
    """
    Same shape guarantee as ensure_subject_constraints, but purely
    read-only (never mutates `subject`) - meant for the solver and for any
    other code that only needs to READ the effective settings, on a
    subject dict that may or may not have ever had ensure_subject_
    constraints() called on it (e.g. a subject loaded from an old file).
    """
    cfg = subject.get("constraints") or {}
    result = {}
    for key, base in DEFAULT_SUBJECT_CONSTRAINTS.items():
        merged = dict(base)
        merged.update(cfg.get(key) or {})
        result[key] = merged
    return result


def get_all_teacher_names(data):
    """Every unique teacher name appearing in any subject's names list."""
    names = set()
    for subject in data["subjects"]:
        for n in subject["names"]:
            names.add(n)
    return sorted(names)


# ---------------------------------------------------------- teacher roster
#
# data["teachers"] is the single, centrally-managed master list of every
# teacher the program knows about. Unlike get_all_teacher_names() above
# (a derived view: only names currently assigned to some subject), this is
# a persisted registry that can also hold a teacher who isn't assigned to
# anything yet. Add/remove/rename all go through the three functions below
# so every part of the file (subjects, manual_assignments,
# scheduling_constraints.per_teacher) always agrees on one canonical
# spelling per real person - the GUI's subject editor no longer lets a
# brand-new name be typed in directly; it only offers a pick-from-roster
# list (see gui.py's SubjectEditor names_card).

def ensure_teacher_roster(data):
    """
    Make sure data["teachers"] exists and contains at least every name
    already in use by some subject - so a JSON file saved before this
    feature existed (or hand-edited outside the app) still lists every
    real teacher it already has, instead of hiding them from the new
    "قائمة الأساتذة" tab and the subject-editor picker. Only ever ADDS
    names here, never removes or reorders ones already present.
    """
    roster = data.setdefault("teachers", [])
    existing = set(roster)
    for name in get_all_teacher_names(data):
        if name not in existing:
            roster.append(name)
            existing.add(name)
    return roster


def add_teacher_to_roster(data, name):
    """
    Register a brand-new teacher centrally. This is the ONLY place a new
    teacher name may be created - subject editors only ever pick an
    existing roster name, never type a new one, so every teacher the
    program knows about always has exactly one canonical spelling.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("اسم الأستاذ لا يمكن أن يكون فارغاً.")
    roster = data.setdefault("teachers", [])
    if name in roster:
        raise ValueError(f"الأستاذ \"{name}\" موجود بالفعل في قائمة الأساتذة.")
    roster.append(name)
    return name


def remove_teacher_from_roster(data, name):
    """
    Remove a teacher from the central roster - blocked (raises
    RuntimeError, naming the subjects) while they are still assigned to
    any subject, so deleting them here can never silently orphan a
    subject's teacher list. The user must remove them from every subject
    first (from that subject's own "أسماء الأساتذة" card), then delete
    them centrally.
    """
    using_subjects = [s["name"] for s in data["subjects"] if name in s["names"]]
    if using_subjects:
        raise RuntimeError(
            f"لا يمكن حذف الأستاذ \"{name}\" من القائمة لأنه ما يزال مُسنَداً للمواد التالية: "
            + "، ".join(using_subjects) +
            " - أزِله أولاً من كل مادة من هذه (من بطاقة \"أسماء الأساتذة\" في محرر المادة)، "
            "ثم احذفه من هنا."
        )
    roster = data.setdefault("teachers", [])
    if name in roster:
        roster.remove(name)
    per_teacher = data.get("scheduling_constraints", {}).get("per_teacher", {})
    per_teacher.pop(name, None)


def rename_teacher_in_roster(data, old_name, new_name):
    """
    Rename a teacher everywhere at once: the roster entry itself, every
    subject's "names" list and manual_assignments rows that reference
    them, and their scheduling_constraints.per_teacher override (if any) -
    so a rename done centrally can never leave a stale or duplicate
    spelling anywhere else in the file. This is now the ONLY way to rename
    a teacher (the old per-subject "تعديل الاسم" button is gone).
    """
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("اسم الأستاذ الجديد لا يمكن أن يكون فارغاً.")
    roster = data.setdefault("teachers", [])
    if old_name not in roster:
        raise ValueError(f"الأستاذ \"{old_name}\" غير موجود في قائمة الأساتذة.")
    if new_name == old_name:
        return
    if new_name in roster:
        raise ValueError(
            f"الأستاذ \"{new_name}\" موجود بالفعل في القائمة - لا يمكن استخدام نفس الاسم لأستاذين.")
    roster[roster.index(old_name)] = new_name
    for subject in data["subjects"]:
        subject["names"] = [new_name if n == old_name else n for n in subject["names"]]
        for row in subject.get("manual_assignments", []) or []:
            if row.get("teacher") == old_name:
                row["teacher"] = new_name
    per_teacher = data.get("scheduling_constraints", {}).get("per_teacher", {})
    if old_name in per_teacher:
        per_teacher[new_name] = per_teacher.pop(old_name)


def teacher_current_periods(data, name):
    """
    This teacher's current total weekly periods, summed across every
    subject they are already assigned to (exactly the load pack_subject
    would hand them right now) - used to show a live "how loaded is this
    teacher already" side-info figure when picking them for another
    subject, without needing to run the full solver. Only packs subjects
    that actually reference this name, so it stays cheap to call on every
    selection change in the GUI.
    """
    total = 0.0
    for subject in data["subjects"]:
        if name not in subject["names"]:
            continue
        try:
            slots = pack_subject(data, subject)
        except RuntimeError:
            # مادة وصلت مؤقتاً لحالة يتعذّر توزيعها (كل أساتذتها أصبح لديهم
            # إسناد إجباري يدوي بلا أستاذ حر يستلم الباقي) - هذا مجرد رقم
            # عرض توضيحي وليس بوابة تحقق، فلا يجوز أن يُسقِط أي صفحة تستدعيه
            # (مثل لوحة المعلومات التي يُفترض أن تُظهر تحذيراً واضحاً عبر
            # validate_manual_assignments بدل الانهيار قبل الوصول إليه).
            continue
        for slot in slots:
            if slot["name"] == name:
                total += slot["total"]
    return total


def _merge_group(base_group, override_group):
    if not override_group:
        return dict(base_group)
    merged = dict(base_group)
    merged.update(override_group)
    return merged


def effective_constraints(data, teacher_name):
    """
    The settings that actually apply to one teacher: start from the global
    defaults, then apply that teacher's own overrides (if any) on top - key
    by key, so a teacher can override just e.g. "day_off" while still
    inheriting the global "max_gap_windows" setting.
    """
    sc = data.get("scheduling_constraints", {})
    defaults = sc.get("defaults", {})
    per_teacher = sc.get("per_teacher", {}).get(teacher_name, {})

    result = {}
    for key, base in DEFAULT_TEACHER_CONSTRAINTS.items():
        default_override = defaults.get(key)
        teacher_override = per_teacher.get(key)
        if key == "day_off":
            # Defensive migration: a JSON file saved before multi-day
            # support (or hand-edited) may still carry the legacy single
            # "day" field instead of "days". This MUST happen on each raw
            # override BEFORE merging - not only on the final merged
            # result - otherwise a legacy override's "day" would be
            # shadowed by the already-current "days": [] that _merge_group
            # inherits from the base/default group underneath it, and the
            # legacy value would be silently lost instead of migrated.
            if default_override:
                default_override = _normalize_day_off_group(dict(default_override))
            if teacher_override:
                teacher_override = _normalize_day_off_group(dict(teacher_override))
        if key == "empty_periods":
            # Same reasoning as the day_off migration just above: this MUST
            # happen on each raw override before merging, since _merge_group
            # is a shallow dict.update() - an un-migrated legacy override's
            # "position"/"count" would otherwise sit alongside (not replace)
            # the current-shape "start"/"end" inherited from the base/default
            # underneath it, and never actually get read by solve_timetable.
            if default_override:
                default_override = _normalize_empty_periods_group(default_override)
            if teacher_override:
                teacher_override = _normalize_empty_periods_group(teacher_override)
        merged_default = _merge_group(base, default_override)
        result[key] = _merge_group(merged_default, teacher_override)
    return result


def teacher_capacity(data, teacher_name):
    """
    Worst-case max usable weekly periods for this teacher: simply every
    slot in the week. Neither "تفريغ حصص في بداية/نهاية اليوم" (empty_periods)
    nor "يوم عطلة كامل" (day_off) reserve anything here - both are
    best-effort preferences in the solver (see solve_timetable) rather than
    hard slot removals, so a teacher whose weekly load leaves no room to
    fully honor one of them isn't blocked from generating at all; the
    solver simply satisfies as much of the preference as it can and notes
    the rest. max_gap_windows and start_from_beginning constrain
    arrangement, not total count, so they never reduce this bound either.
    Used for a fast, friendly feasibility pre-check (no teacher may need
    more periods than literally exist in the week) before the full CP-SAT
    model is built.
    """
    days = data["meta"]["days"]
    periods_per_day = data["meta"]["periods_per_day"]
    return len(days) * periods_per_day


def validate_teacher_constraints(data):
    """
    Raise a clear Arabic error for directly self-contradictory settings,
    instead of letting CP-SAT fail later with a bare INFEASIBLE status.
    """
    days = data["meta"]["days"]
    for name in get_all_teacher_names(data):
        eff = effective_constraints(data, name)

        ep = eff["empty_periods"]
        sfb = eff["start_from_beginning"]
        if ep["enabled"]:
            specific_mode = ep.get("days_mode") == "specific"
            per_day = ep.get("per_day") or {}

            # تعارض مع "إلزام البدء من أول حصة" (قيد صارم يُطبَّق على كل
            # الأيام دائماً بلا استثناء): في نمط "أيام محددة" يُفحص كل يوم
            # بعدده الخاص، وفي نمط "كل الأيام" يُفحص الإعداد العام الموحّد.
            if sfb["enabled"]:
                if specific_mode:
                    conflicting_day = next(
                        (d for d, cfg in per_day.items()
                         if cfg.get("start", {}).get("enabled")
                         and int(cfg["start"].get("count") or 0) >= 1),
                        None,
                    )
                    if conflicting_day:
                        raise RuntimeError(
                            f"تعارض في إعدادات الأستاذ {name}: خيار \"تفريغ بداية اليوم\" "
                            f"ليوم {conflicting_day} يتعارض مع خيار \"إلزام الحصص بالبدء من "
                            f"أول اليوم\" في آنٍ واحد."
                        )
                elif ep["start"]["enabled"] and int(ep["start"]["count"] or 0) >= 1:
                    raise RuntimeError(
                        f"تعارض في إعدادات الأستاذ {name}: خيار \"تفريغ حصص في بداية اليوم\" "
                        f"يتعارض مع خيار \"إلزام الحصص بالبدء من أول اليوم\" في آنٍ واحد."
                    )

            if specific_mode:
                chosen = list(dict.fromkeys(ep.get("days") or []))
                if not chosen:
                    raise RuntimeError(
                        f"إعداد تفريغ الحصص غير مكتمل للأستاذ {name}: النمط \"أيام محددة\" "
                        f"مفعّل لكن لم يُختَر أي يوم بعد - فعِّل تفريغ بداية و/أو نهاية ليوم "
                        f"واحد على الأقل، أو بدّل النمط إلى \"كل الأيام\"."
                    )
                bad = [d for d in chosen if d not in days]
                if bad:
                    raise RuntimeError(
                        f"إعداد تفريغ الحصص غير صالح للأستاذ {name}: "
                        f"\"{'، '.join(bad)}\" ليس من أيام الأسبوع الدراسي المعرَّفة."
                    )
                # كل يوم "مختار" (ظاهر في "days") يجب أن يحمل فعلاً بداية
                # و/أو نهاية مفعَّلة في per_day، وإلا فهو يوم بلا أي أثر -
                # بيانات غير متّسقة (مثل ملف عُدِّل يدوياً خارج الواجهة).
                empty_days = [
                    d for d in chosen
                    if not (
                        (per_day.get(d) or {}).get("start", {}).get("enabled")
                        or (per_day.get(d) or {}).get("end", {}).get("enabled")
                    )
                ]
                if empty_days:
                    raise RuntimeError(
                        f"إعداد تفريغ الحصص غير صالح للأستاذ {name}: اليوم/الأيام "
                        f"\"{'، '.join(empty_days)}\" مُختارة لكن بلا بداية أو نهاية "
                        f"مفعَّلة لها - فعِّل أحدهما لكل يوم مختار، أو أزِله من القائمة."
                    )
            else:
                if not (ep["start"]["enabled"] or ep["end"]["enabled"]):
                    raise RuntimeError(
                        f"إعداد تفريغ الحصص غير مكتمل للأستاذ {name}: القيد مفعّل لكن لم "
                        f"يُفعَّل أي من \"بداية اليوم\" أو \"نهاية اليوم\" - فعّل أحدهما على "
                        f"الأقل، أو عطّل هذا القيد بالكامل."
                    )

        day_off = eff["day_off"]
        if day_off["enabled"]:
            if day_off["mode"] == "specific":
                chosen = list(dict.fromkeys(day_off.get("days") or []))
                if not chosen:
                    raise RuntimeError(
                        f"إعداد يوم العطلة غير مكتمل للأستاذ {name}: النمط \"يوم محدد\" مفعّل "
                        f"لكن لم يُختَر أي يوم بعد - اختر يوماً واحداً على الأقل أو عطّل هذا القيد."
                    )
                bad = [d for d in chosen if d not in days]
                if bad:
                    raise RuntimeError(
                        f"إعداد يوم العطلة غير صالح للأستاذ {name}: "
                        f"\"{'، '.join(bad)}\" ليس من أيام الأسبوع الدراسي المعرَّفة."
                    )
            else:  # "random"
                count = int(day_off.get("count", 1) or 0)
                if count < 1:
                    raise RuntimeError(
                        f"إعداد يوم العطلة غير صالح للأستاذ {name}: عدد أيام العطلة العشوائية "
                        f"يجب أن يكون 1 على الأقل."
                    )


def build_section_ids(data):
    cols = data["meta"]["grade_order"]
    sections = data["sections"]
    ids = []
    for track in cols:
        for s in range(1, int(sections[track]) + 1):
            ids.append((track, s))
    return ids


def pack_subject(data, subject):
    """
    Split one subject's per-grade periods into len(names) teacher slots.

    Any (track, section) pair listed in subject["manual_assignments"] is
    handed directly to its named teacher first (a mandatory, manual
    override) and removed from the pool that gets auto-balanced.

    Any teacher who actually has at least one CLAIMED (track, section) atom
    from manual_assignments in this subject (a "manually-pinned" teacher -
    a manual-assignment row with an empty "sections" list claims nothing
    and does NOT pin them) is then excluded ENTIRELY from the automatic
    distribution of whatever remains unclaimed - not just for the (track,
    section) pairs they were explicitly given, but for every other
    unclaimed atom in the subject too. Once a teacher has actually received
    a manual assignment here, nothing more is ever piled onto them
    automatically; the remaining atoms are balanced only among this
    subject's OTHER teachers (the ones with no manual assignment at all),
    using the same greedy target-balance as before, just restricted to
    that smaller pool. Subjects with no "manual_assignments" (the default -
    absent key) behave exactly as before, since every teacher is then
    eligible.

    Raises RuntimeError if every teacher in the subject ends up manually
    pinned while unclaimed periods still remain - there would be no
    eligible teacher left to hand the remainder to (validate_manual_
    assignments also catches this earlier, with the same message, so it
    surfaces as a friendly warning/blocker before generation rather than a
    bare exception here). Exempt: a subject with only one teacher total
    always keeps getting the remainder itself, since there is no
    alternative teacher to give it to.

    merged_groups (see validate_merged_groups) act exactly like an extra,
    implicit manual assignment pinning ONE named teacher onto BOTH sections
    of the pair at once - no separate manual_assignments row is needed. The
    higher-numbered section of the pair is additionally tagged
    "merge_primary_section" pointing at its partner, so solve_timetable can
    force their time slots to be identical later (a real joint lesson: same
    teacher, same slots, in both sections' schedules). Its own atom keeps
    its own "periods" count intact here (it still needs its own full weekly
    quota scheduled) - only the LOAD/DISPLAY total below excludes it, since
    those periods don't consume any additional time from the teacher's
    week (they happen at the very same slots as the primary section's).
    """
    cols = data["meta"]["grade_order"]
    sections = data["sections"]
    vals = subject["periods"]
    names = subject["names"]
    n = len(names)
    if n == 0:
        return []

    atoms = []
    for c in cols:
        periods = float(vals.get(c, 0) or 0)
        if periods <= 0:
            continue
        for s in range(1, int(sections[c]) + 1):
            atoms.append({"track": c, "section": s, "periods": periods})

    manual = subject.get("manual_assignments", []) or []
    claimed = {}  # (track, section) -> teacher name
    pinned_names = set()
    for row in manual:
        teacher = row.get("teacher")
        track = row.get("track")
        if teacher not in names:
            continue
        for sec in row.get("sections", []) or []:
            claimed[(track, sec)] = teacher
            pinned_names.add(teacher)

    merge_shadow_of = {}  # (track, shadow_section) -> primary_section
    for grp in subject.get("merged_groups", []) or []:
        teacher = grp.get("teacher")
        track = grp.get("track")
        secs = sorted(set(grp.get("sections", []) or []))
        if teacher not in names or len(secs) != 2:
            continue
        primary, shadow = secs
        claimed[(track, primary)] = teacher
        claimed[(track, shadow)] = teacher
        pinned_names.add(teacher)
        merge_shadow_of[(track, shadow)] = primary

    for atom in atoms:
        primary = merge_shadow_of.get((atom["track"], atom["section"]))
        if primary is not None:
            atom["merge_primary_section"] = primary

    name_idx = {name: i for i, name in enumerate(names)}
    teachers = [[] for _ in range(n)]
    remaining_atoms = []
    for atom in atoms:
        forced_teacher = claimed.get((atom["track"], atom["section"]))
        if forced_teacher is not None:
            teachers[name_idx[forced_teacher]].append(atom)
        else:
            remaining_atoms.append(atom)

    eligible_idx = [name_idx[nm] for nm in names if nm not in pinned_names]
    if not eligible_idx and n == 1:
        # The subject's only teacher is unavoidably "pinned" (there is no
        # alternative teacher to give the remainder to) - fall back to
        # letting them keep the rest too, exactly as before this feature
        # existed, rather than raising a pointless error for a subject that
        # only ever had one teacher in the first place.
        eligible_idx = [0]
    if remaining_atoms and not eligible_idx:
        raise RuntimeError(
            f"تعذّر توزيع حصص مادة \"{subject['name']}\": كل أساتذة هذه المادة أصبح لديهم "
            f"إسناد إجباري يدوي، ولم يعد يوجد أستاذ بلا إسناد يدوي يمكن أن تُوزَّع عليه بقية "
            f"الحصص تلقائياً. إمّا أسند بقية الشعب يدوياً أيضاً، أو اترك أستاذاً واحداً على "
            f"الأقل بلا إسناد يدوي في هذه المادة."
        )

    remaining_total = sum(a["periods"] for a in remaining_atoms)
    target = remaining_total / len(eligible_idx) if eligible_idx else 0
    pos = 0
    for atom in remaining_atoms:
        # Advance past any teacher(s) already at/over target - a while
        # loop (not a single "if") because a teacher may already be over
        # target purely from earlier auto-assigned atoms, before this loop
        # even reaches them.
        while pos < len(eligible_idx) - 1 and sum(
                a["periods"] for a in teachers[eligible_idx[pos]]) >= target:
            pos += 1
        teachers[eligible_idx[pos]].append(atom)

    slots = []
    for name, atoms_for_teacher in zip(names, teachers):
        slots.append({
            "subject": subject["name"],
            "name": name,
            "atoms": atoms_for_teacher,
            # A merged pair's shadow atom occupies no EXTRA time of its own
            # (see merge_shadow_of above) - excluded here so a teacher's
            # displayed weekly load reflects actual occupied slots, not a
            # double-count of the same joint lesson.
            "total": sum(
                a["periods"] for a in atoms_for_teacher
                if "merge_primary_section" not in a
            ),
        })
    return slots


def validate_manual_assignments(data):
    """
    Raise a clear Arabic error for any invalid or conflicting manual
    (forced) section assignment, instead of letting pack_subject silently
    ignore a bad row or letting two teachers end up double-booked on the
    same section. Also pre-flights the "every teacher manually pinned but
    periods remain unclaimed" situation that would otherwise make
    pack_subject itself raise (see its docstring) - so this shows up as a
    friendly warning/blocker (Dashboard tab, and before generation) instead
    of a bare exception surfacing later.
    """
    cols = data["meta"]["grade_order"]
    sections_count = data["sections"]
    for subject in data["subjects"]:
        manual = subject.get("manual_assignments", []) or []
        if not manual:
            continue
        claimed_by = {}
        pinned_names = set()
        for row in manual:
            teacher = row.get("teacher")
            track = row.get("track")
            if teacher not in subject["names"]:
                raise RuntimeError(
                    f"إسناد غير صالح في مادة \"{subject['name']}\": الأستاذ \"{teacher}\" "
                    f"ليس ضمن قائمة أساتذة هذه المادة."
                )
            if track not in cols:
                raise RuntimeError(
                    f"إسناد غير صالح في مادة \"{subject['name']}\": الصف \"{track}\" غير معروف."
                )
            periods_for_track = float(subject["periods"].get(track, 0) or 0)
            if periods_for_track <= 0:
                raise RuntimeError(
                    f"إسناد غير صالح في مادة \"{subject['name']}\": لا توجد حصص لمادة "
                    f"\"{subject['name']}\" في صف \"{track}\" أصلاً، فلا يمكن إسناد شعب منه."
                )
            max_section = int(sections_count.get(track, 0) or 0)
            for sec in row.get("sections", []) or []:
                if not (1 <= sec <= max_section):
                    raise RuntimeError(
                        f"إسناد غير صالح في مادة \"{subject['name']}\": الشعبة {sec} غير موجودة "
                        f"في صف \"{track}\" (المتاح حالياً: من 1 إلى {max_section})."
                    )
                key = (track, sec)
                if key in claimed_by and claimed_by[key] != teacher:
                    raise RuntimeError(
                        f"تعارض إسناد في مادة \"{subject['name']}\": الشعبة {sec} من صف "
                        f"\"{track}\" أُسندت لأكثر من أستاذ ({claimed_by[key]} و{teacher})."
                    )
                claimed_by[key] = teacher
                # "Pinned" (excluded from auto-balancing - see pack_subject)
                # only counts once a row actually claims at least one
                # section - an empty "sections" list (e.g. a row added in
                # the UI but not filled in yet) claims nothing, so it must
                # NOT by itself exclude that teacher from the automatic
                # distribution of every OTHER unclaimed atom.
                pinned_names.add(teacher)

        # A manually-pinned teacher (one with ANY manual-assignment row
        # here) is excluded entirely from this subject's automatic
        # balancing (see pack_subject) - so if EVERY teacher ends up
        # pinned while some of the subject's periods are still unclaimed,
        # there is no eligible teacher left for the remainder to land on.
        # Exception: a subject with only ONE teacher total has no
        # alternative to give the remainder to anyway, so that single
        # teacher keeps getting it automatically exactly as before this
        # feature existed - only flag this for subjects with 2+ teachers.
        if len(subject["names"]) > 1 and set(pinned_names) == set(subject["names"]):
            claimed_periods = sum(
                float(subject["periods"].get(track, 0) or 0) for (track, _sec) in claimed_by
            )
            total_periods = subject_required_periods(data, subject)
            if claimed_periods + 1e-9 < total_periods:
                raise RuntimeError(
                    f"تعذّر توزيع حصص مادة \"{subject['name']}\": كل أساتذة هذه المادة أصبح "
                    f"لديهم إسناد إجباري يدوي، بينما ما تزال هناك حصص ({total_periods - claimed_periods:g}"
                    f" حصة) لم تُسنَد بعد ولا يوجد أستاذ بلا إسناد يدوي تُوزَّع عليه تلقائياً. "
                    f"إمّا أسند بقية الشعب يدوياً أيضاً لهذه المادة، أو اترك أستاذاً واحداً على "
                    f"الأقل بلا إسناد يدوي فيها."
                )


def validate_merged_groups(data):
    """
    Raise a clear Arabic error for any invalid "دمج شعبتين" (merge two
    sections onto the same teacher, same time slots - a genuine joint
    lesson) configuration, mirroring validate_manual_assignments above:
    a friendly pre-flight check (Dashboard tab, and before generation)
    instead of a bare exception surfacing later from pack_subject/
    solve_timetable. A merge group acts like an implicit manual assignment
    (see pack_subject), so it must not also collide with an explicit one.
    """
    cols = data["meta"]["grade_order"]
    sections_count = data["sections"]
    for subject in data["subjects"]:
        groups = subject.get("merged_groups", []) or []
        if not groups:
            continue
        manual_claimed = set()
        for row in subject.get("manual_assignments", []) or []:
            for sec in row.get("sections", []) or []:
                manual_claimed.add((row.get("track"), sec))

        claimed_by = {}
        for grp in groups:
            teacher = grp.get("teacher")
            track = grp.get("track")
            secs = grp.get("sections", []) or []
            if teacher not in subject["names"]:
                raise RuntimeError(
                    f"دمج شعب غير صالح في مادة \"{subject['name']}\": الأستاذ \"{teacher}\" "
                    f"ليس ضمن قائمة أساتذة هذه المادة."
                )
            if track not in cols:
                raise RuntimeError(
                    f"دمج شعب غير صالح في مادة \"{subject['name']}\": الصف \"{track}\" غير معروف."
                )
            if float(subject["periods"].get(track, 0) or 0) <= 0:
                raise RuntimeError(
                    f"دمج شعب غير صالح في مادة \"{subject['name']}\": لا توجد حصص لمادة "
                    f"\"{subject['name']}\" في صف \"{track}\" أصلاً."
                )
            distinct_secs = sorted(set(secs))
            if len(secs) != 2 or len(distinct_secs) != 2:
                raise RuntimeError(
                    f"دمج شعب غير صالح في مادة \"{subject['name']}\": يجب اختيار شعبتين "
                    f"مختلفتين بالضبط للدمج."
                )
            max_section = int(sections_count.get(track, 0) or 0)
            for sec in distinct_secs:
                if not (1 <= sec <= max_section):
                    raise RuntimeError(
                        f"دمج شعب غير صالح في مادة \"{subject['name']}\": الشعبة {sec} غير "
                        f"موجودة في صف \"{track}\" (المتاح حالياً: من 1 إلى {max_section})."
                    )
                key = (track, sec)
                if key in claimed_by:
                    raise RuntimeError(
                        f"دمج شعب متعارض في مادة \"{subject['name']}\": الشعبة {sec} من صف "
                        f"\"{track}\" مضمومة في أكثر من عملية دمج واحدة."
                    )
                if key in manual_claimed:
                    raise RuntimeError(
                        f"دمج شعب متعارض في مادة \"{subject['name']}\": الشعبة {sec} من صف "
                        f"\"{track}\" لها أيضاً إسناد إجباري منفصل - أزل الإسناد الإجباري "
                        f"عنها أولاً، أو عدّل عملية الدمج."
                    )
                claimed_by[key] = teacher


def build_all_slots(data):
    """Pack every subject; return the flat list of (subject, teacher, atoms)."""
    slots = []
    for subject in data["subjects"]:
        slots.extend(pack_subject(data, subject))
    return slots


def requirements_from_slots(slots):
    """Collapse a slot's atoms into one requirement per (track, section)."""
    requirements = []
    for slot in slots:
        by_ts = {}
        merge_primary = {}
        for a in slot["atoms"]:
            key = (a["track"], a["section"])
            by_ts[key] = by_ts.get(key, 0) + a["periods"]
            if "merge_primary_section" in a:
                merge_primary[key] = a["merge_primary_section"]
        for (track, sec), periods in by_ts.items():
            req = {
                "teacher": slot["name"], "subject": slot["subject"],
                "track": track, "section": sec, "periods": int(round(periods)),
            }
            if (track, sec) in merge_primary:
                # A "شعبة مدمجة": solve_timetable forces this requirement's
                # time slots to be identical to its primary partner's (see
                # pack_subject's merge_shadow_of), a genuine joint lesson.
                req["merge_primary_section"] = merge_primary[(track, sec)]
            requirements.append(req)
    return requirements


def solve_timetable(data, max_time_in_seconds=300, num_workers=8, progress=None,
                     warm_start=None):
    """
    Solve the full weekly timetable.

    max_time_in_seconds defaults to 5 minutes (raised from an earlier 2
    minutes): CP-SAT's soft "تفريغ حصص"/"يوم عطلة" objective is heavily
    weighted (see SOFT_VIOLATION_WEIGHT below) but the search is still
    time-limited - a run that stops at "FEASIBLE" (rather than "OPTIMAL")
    only means the time budget ran out before the solver could PROVE no
    better arrangement exists, not that none does. A longer budget gives
    it more room to find an arrangement with fewer/no violations for
    teachers whose preference was actually achievable but not yet found -
    it can only ever help or do nothing, never make a solution worse, so
    this is a pure trade of a few extra minutes of generation time for a
    chance at a better result. It cannot, however, manufacture periods
    that don't exist: a teacher genuinely near their weekly capacity limit
    will still show a violation no matter how long the solver runs (see
    teacher_capacity) - only reducing that teacher's actual load fixes
    that case.

    Fairness (min-max) objective: the base objective only ever minimized
    the TOTAL number of violated "should stay empty" slots across every
    teacher combined - which is mathematically indifferent between piling
    every violation onto one unlucky teacher and spreading the same total
    count thinly across several. To stop the solver from favoring either
    outcome arbitrarily, a second term is added on top that specifically
    minimizes the WORST single teacher's violation count (see
    max_violation_var below), weighted heavily enough that it always wins
    out over the plain total - so between two schedules with the same
    worst-case teacher, the total-violation term still breaks the tie, but
    the solver will never accept "teacher A now has 3 violations instead of
    1" merely to shave a couple of violations off other teachers combined.
    This does not change what is achievable, only how the unavoidable
    violations (if any) are distributed among teachers.

    Priority between the two soft preferences: for any teacher who has
    BOTH "يوم عطلة" (day_off) and "تفريغ حصص بداية/نهاية اليوم"
    (empty_periods) enabled at once, and whose real weekly load makes it
    impossible to satisfy both in full, day_off is always protected first -
    the solver sacrifices empty_periods slots instead, never the other way
    around (see DAY_OFF_WEIGHT / EMPTY_PERIODS_WEIGHT below). This holds
    even when protecting the day off costs MORE total violated slots than
    giving it up would.

    warm_start: optionally, a previous solve's section_sched (the same dict
    shape returned as this function's second return value) to seed the
    search from via CP-SAT hints (model.AddHint). When the requirements are
    unchanged or only lightly modified since that previous run, this lets
    the solver spend its whole time budget refining a known-good starting
    point instead of rediscovering one from scratch, typically converging
    to as good or a better result faster. Safe to pass a warm_start that no
    longer matches the current data exactly (e.g. a section was renamed or
    removed) - any assignment that doesn't correspond to a live requirement
    slot is simply ignored rather than raising an error.

    Returns (status_name, section_sched, constraint_notes, constraint_fulfillment):
      - section_sched maps "track|section" -> list of NSLOTS entries, each
        either None or {"subject": ..., "teacher": ...}. Slot index =
        day*periods_per_day + period.
      - constraint_notes maps teacher name -> a list of one-paragraph Arabic
        notes, present only for teachers whose "تفريغ حصص" (empty_periods)
        and/or "يوم عطلة" (day_off) preference could not be fully honored on
        every day (see soft_violation_terms below) - meant to be shown at
        the end of that teacher's PDF program.
      - constraint_fulfillment maps teacher name -> {"requested": int,
        "achieved": int} - the total number of "should stay empty" slots
        asked for (across every enabled empty_periods/day_off group) versus
        how many of them actually ended up empty in the solved schedule.
        Present for every teacher with at least one enabled empty_periods or
        day_off group, WHETHER OR NOT any violation occurred (a fully
        satisfied teacher still gets an entry with achieved == requested),
        so it can be turned into an exact per-teacher fulfillment percentage
        (see teacher_fulfillment_report) - unlike constraint_notes, which
        only exists for teachers with at least one violation.

    Raises RuntimeError if no feasible schedule exists (e.g. a teacher would
    need more periods in a week than there are slots available - this is
    still a hard failure; only empty_periods and day_off are best-effort).
    Two SUBJECT-level constraints (as opposed to the per-teacher ones above)
    are likewise hard, not best-effort: "max_consecutive_per_day" (no run of
    more than N consecutive periods of a given subject in one day, for a
    given section) and "max_daily_per_section" (no more than N total
    periods of a given subject in one day, for a given section) - see
    effective_subject_constraints. If a subject's own weekly period count
    for some section makes one of these impossible to honor, generation
    fails outright (INFEASIBLE) exactly like the teacher-overload case
    above, rather than silently ignoring the limit.
    """
    days = data["meta"]["days"]
    periods_per_day = data["meta"]["periods_per_day"]
    nslots = len(days) * periods_per_day

    def slot_day(s):
        return s // periods_per_day

    validate_teacher_constraints(data)
    validate_manual_assignments(data)
    validate_merged_groups(data)
    ensure_min_teachers(data)

    # Grades whose entered subjects don't yet sum to a full week are NOT
    # blocked - their sections are scheduled with whatever periods ARE
    # entered, and the remaining slots are simply left blank (common while
    # a school's curriculum is still being entered). This is informational
    # only; see incomplete_grades() for the
    # proactive warning shown in the Dashboard tab before generation.
    incomplete = incomplete_grades(data)
    if incomplete and progress:
        parts = []
        for grade, label, total, needed in incomplete:
            total_i = int(round(total))
            parts.append(f"{label} ({total_i}/{needed})")
        progress("تنبيه: حصص غير مكتملة لبعض الصفوف (ستبقى فارغة في الجدول): "
                  + "، ".join(parts))

    section_ids = build_section_ids(data)
    slots = build_all_slots(data)
    requirements = requirements_from_slots(slots)

    # requirements_from_slots() guarantees at most ONE requirement per
    # (subject, track, section) triple (pack_subject hands each whole
    # (track, section) atom to exactly one teacher, never splitting it), so
    # this lookup is unambiguous. Built once here and reused below both for
    # merge-linking and for the subject-level hard constraints.
    requirement_by_subject_section = {
        (r["subject"], r["track"], r["section"]): i for i, r in enumerate(requirements)
    }

    # "دمج شعبتين": a shadow requirement's time slots must be forced
    # identical to its primary partner's (see pack_subject/
    # requirements_from_slots) - a genuine joint lesson, same teacher, same
    # slots, in both sections. shadow_req_idxs is excluded from per-teacher
    # load/exclusivity below (its occupancy is already fully accounted for
    # via its primary partner), everywhere else it behaves like any other
    # requirement (own periods-count constraint, own section exclusivity,
    # own subject-level hard caps).
    merge_links = []  # (primary_i, shadow_j)
    shadow_req_idxs = set()
    for j, r in enumerate(requirements):
        primary_sec = r.get("merge_primary_section")
        if primary_sec is None:
            continue
        i = requirement_by_subject_section.get((r["subject"], r["track"], primary_sec))
        if i is None:
            continue
        merge_links.append((i, j))
        shadow_req_idxs.add(j)

    if progress:
        progress(f"عدد المتطلبات: {len(requirements)} — إجمالي الحصص: "
                  f"{sum(r['periods'] for r in requirements)}")

    # Quick feasibility pre-check: no teacher may need more periods than
    # literally exist in the week. This is a pure sanity check now - it does
    # NOT account for empty_periods/day_off, since both are best-effort
    # preferences (see teacher_capacity) rather than hard slot reservations,
    # so they can never make generation impossible on their own.
    per_teacher_total = {}
    for i, r in enumerate(requirements):
        if i in shadow_req_idxs:
            continue
        per_teacher_total[r["teacher"]] = per_teacher_total.get(r["teacher"], 0) + r["periods"]
    overloaded = {}
    for t, p in per_teacher_total.items():
        cap = teacher_capacity(data, t)
        if p > cap:
            overloaded[t] = (p, cap)
    if overloaded:
        details = "، ".join(
            f"{t} ({p} حصة > {cap} حصة في الأسبوع)"
            for t, (p, cap) in overloaded.items()
        )
        raise RuntimeError(
            f"يستحيل توليد جدول: الأستاذ/الأساتذة التالية يحتاجون حصصاً أكثر من "
            f"عدد حصص الأسبوع بالكامل: {details}"
        )

    model = cp_model.CpModel()
    x = {}
    for i, r in enumerate(requirements):
        for s in range(nslots):
            x[i, s] = model.NewBoolVar(f"x_{i}_{s}")

    # Warm start: seed every x[i, s] with a hint derived from a previous
    # solve's section_sched, if one was given. A requirement whose
    # (track, section) no longer appears in warm_start, or whose slot list
    # is a different length (e.g. periods_per_day changed), is simply left
    # unhinted rather than raising - CP-SAT is fine with partial hints.
    if warm_start:
        for i, r in enumerate(requirements):
            prev_slots = warm_start.get(f"{r['track']}|{r['section']}")
            if not prev_slots or len(prev_slots) != nslots:
                continue
            for s in range(nslots):
                entry = prev_slots[s]
                was_assigned = bool(
                    entry and entry.get("subject") == r["subject"]
                    and entry.get("teacher") == r["teacher"]
                )
                model.AddHint(x[i, s], 1 if was_assigned else 0)

    for i, r in enumerate(requirements):
        model.Add(sum(x[i, s] for s in range(nslots)) == r["periods"])

    # دمج شعبتين: force the shadow requirement's slots to exactly mirror its
    # primary partner's - same teacher (already guaranteed by pack_subject),
    # now also same time, in every slot.
    for i, j in merge_links:
        for s in range(nslots):
            model.Add(x[i, s] == x[j, s])

    by_section = {}
    for i, r in enumerate(requirements):
        by_section.setdefault((r["track"], r["section"]), []).append(i)
    for sid, idxs in by_section.items():
        for s in range(nslots):
            model.Add(sum(x[i, s] for i in idxs) <= 1)

    # A shadow requirement is excluded here - it is not a separate teaching
    # slot, only the mirror image of its primary partner (linked above), so
    # counting both would wrongly forbid the teacher from occupying the
    # merged pair's own shared slot (x[i,s] == x[j,s] == 1 together is
    # exactly the point). by_teacher is also reused below (busy[d, p]) for
    # every per-teacher soft preference, so this single exclusion point
    # keeps a merged teacher's empty_periods/day_off/gap-window accounting
    # correct too - each merged slot counted once, not twice.
    by_teacher = {}
    for i, r in enumerate(requirements):
        if i in shadow_req_idxs:
            continue
        by_teacher.setdefault(r["teacher"], []).append(i)
    for teacher, idxs in by_teacher.items():
        for s in range(nslots):
            model.Add(sum(x[i, s] for i in idxs) <= 1)

    # Subject-level scheduling constraints (max consecutive periods/day, max
    # total periods/day for one section) — see effective_subject_constraints
    # for the exact semantics. Unlike the per-teacher preferences below,
    # both are HARD rules: added directly with model.Add(...), never via the
    # soft-violation/objective machinery, so generation fails outright
    # (INFEASIBLE) rather than silently ignoring one if a subject's weekly
    # period count for a section makes it impossible to honor.
    #
    grade_order = data["meta"]["grade_order"]
    sections_count = data["sections"]
    for subject in data["subjects"]:
        sub_cfg = effective_subject_constraints(subject)
        mc_cfg = sub_cfg["max_consecutive_per_day"]
        md_cfg = sub_cfg["max_daily_per_section"]
        if not (mc_cfg["enabled"] or md_cfg["enabled"]):
            continue
        max_consec = max(0, int(mc_cfg["max"] or 0)) if mc_cfg["enabled"] else None
        max_daily = max(0, int(md_cfg["max"] or 0)) if md_cfg["enabled"] else None
        for track in grade_order:
            if float(subject["periods"].get(track, 0) or 0) <= 0:
                continue
            for sec in range(1, int(sections_count.get(track, 0) or 0) + 1):
                i = requirement_by_subject_section.get((subject["name"], track, sec))
                if i is None:
                    continue
                for d in range(len(days)):
                    day_vars = [x[i, d * periods_per_day + p] for p in range(periods_per_day)]
                    if max_daily is not None:
                        model.Add(sum(day_vars) <= max_daily)
                    if max_consec is not None:
                        # Sliding-window trick: in every window of
                        # (max_consec + 1) consecutive periods, at most
                        # max_consec of them may belong to this subject -
                        # which forces at least one non-subject period
                        # inside any such window, i.e. no run of
                        # max_consec + 1 (or more) consecutive periods can
                        # ever form. A no-op when max_consec + 1 exceeds
                        # periods_per_day (no window that size exists).
                        window = max_consec + 1
                        for start_p in range(0, periods_per_day - window + 1):
                            model.Add(sum(day_vars[start_p:start_p + window]) <= max_consec)

    # Per-teacher scheduling constraints (empty periods, day off, gap
    # windows, start-from-beginning) — applied only to teachers who have at
    # least one enabled setting (globally via "defaults", or via a
    # "per_teacher" override), so datasets/teachers with nothing configured
    # are completely unaffected.
    #
    # Both "تفريغ حصص في بداية/نهاية اليوم" (empty_periods) and "يوم عطلة
    # كامل" (day_off) are SOFT preferences, not hard rules: violating one
    # (leaving a requested period busy anyway) is heavily penalized in the
    # objective below, so the solver always satisfies them fully whenever
    # that's possible, but falls back to satisfying as much as it can —
    # instead of the whole generation failing outright — when the teacher's
    # actual weekly load leaves no room to keep every requested period (or
    # the whole day off) empty. Each violation is tracked here so a note can
    # be added to that teacher's PDF program explaining exactly which
    # days/periods couldn't be freed.
    # Every soft violation is tagged by its SOURCE ("day_off" vs
    # "empty_periods"): when the same teacher has BOTH settings enabled and
    # satisfying both in full turns out to be impossible, "يوم عطلة"
    # (day_off) must be protected first, at the expense of "تفريغ حصص
    # بداية/نهاية اليوم" (empty_periods) - never the other way around. This
    # priority is enforced purely through objective weighting (see
    # DAY_OFF_WEIGHT / EMPTY_PERIODS_WEIGHT right before model.Minimize()
    # below), not by any hard rule here.
    soft_violation_terms_emptyperiods = []  # flat, every teacher, empty_periods source only
    soft_violation_terms_dayoff = []        # flat, every teacher, day_off source only
    soft_violation_terms_by_teacher = {}  # teacher -> [(var, "day_off"|"empty_periods"), ...],
                                           # tagged terms for the min-max fairness objective below
    empty_period_targets = {}  # teacher -> {"position", "count", "vars": {(d, p): var}}
    day_off_targets = {}  # teacher -> {"mode": "specific", "days": {d_idx: {p: var}}}
                           #         | {"mode": "random", "off_vars": [...], "viol_vars": {(d, p): var}, "count": n}
    for teacher in sorted(by_teacher.keys()):
        eff = effective_constraints(data, teacher)
        if not any(eff[k]["enabled"] for k in eff):
            continue

        idxs = by_teacher[teacher]

        busy = {}
        for d in range(len(days)):
            for p in range(periods_per_day):
                s = d * periods_per_day + p
                b = model.NewBoolVar(f"busy_{teacher}_{d}_{p}")
                model.Add(b == sum(x[i, s] for i in idxs))
                busy[d, p] = b

        # 1) تفريغ عدد حصص محدد في بداية اليوم و/أو في نهايته (قيد ليّن -
        #    انظر الشرح أعلاه)، على كل الأيام بنفس العدد، أو على أيام محددة
        #    فقط - وفي هذه الحالة الثانية لكل يوم عدده الخاص (مثال: تفريغ
        #    حصتين من بداية الأحد، وثلاث حصص من نهاية الاثنين، في نفس
        #    المجموعة). بدل إلزام هذه الحصص بالفراغ (ما قد يجعل الحل
        #    مستحيلاً بالكامل)، تُدرَج في هدف التحسين بوزن كبير فتُترك فارغة
        #    كلما أمكن، وتبقى مشغولة فقط عند الضرورة القصوى. "بداية اليوم"
        #    و"نهاية اليوم" ليسا خيارين متبادلين - قد يكونا مفعَّلين معاً
        #    (كل بعدده الخاص)، أو واحد منهما فقط، لكل يوم على حدة في نمط
        #    "أيام محددة".
        ep = eff["empty_periods"]
        if ep["enabled"]:
            specific_mode = ep.get("days_mode") == "specific"
            per_day_cfg = ep.get("per_day") or {}
            if specific_mode:
                target_day_names = [
                    d for d in dict.fromkeys(ep.get("days") or []) if d in days
                ]
            else:  # "all"
                target_day_names = list(days)

            target_vars = {}
            day_config = {}
            for day_name in target_day_names:
                d = days.index(day_name)
                # في نمط "أيام محددة" لهذا اليوم عدده الخاص إن وُجد
                # (per_day)، وإلا يرث عدد المجموعة العام - وهذا بالضبط ما
                # كان يحدث دائماً قبل إضافة إمكانية التخصيص لكل يوم (توافقية
                # كاملة مع أي ملف بيانات قديم). في نمط "كل الأيام" يُستخدم
                # عدد المجموعة العام مباشرة لكل الأيام دائماً.
                day_override = per_day_cfg.get(day_name) if specific_mode else None
                start_cfg = (day_override or {}).get("start", ep["start"])
                end_cfg = (day_override or {}).get("end", ep["end"])
                start_count = (
                    max(0, min(int(start_cfg.get("count") or 0), periods_per_day))
                    if start_cfg.get("enabled") else 0
                )
                end_count = (
                    max(0, min(int(end_cfg.get("count") or 0), periods_per_day))
                    if end_cfg.get("enabled") else 0
                )
                if not start_count and not end_count:
                    continue

                # A union, not two separate loops - so a small periods_per_day
                # where the start-count and end-count ranges overlap (e.g. a
                # 3-period day with both "empty first 2" and "empty last 2"
                # enabled) still only counts/penalizes each slot ONCE rather
                # than double-weighting it in the objective.
                targeted_periods = set()
                if start_count:
                    targeted_periods.update(range(start_count))
                if end_count:
                    targeted_periods.update(range(periods_per_day - end_count, periods_per_day))
                for p in sorted(targeted_periods):
                    soft_violation_terms_emptyperiods.append(busy[d, p])
                    soft_violation_terms_by_teacher.setdefault(teacher, []).append(
                        (busy[d, p], "empty_periods"))
                    target_vars[d, p] = busy[d, p]
                day_config[d] = {
                    "start_enabled": bool(start_count),
                    "start_count": start_count,
                    "end_enabled": bool(end_count),
                    "end_count": end_count,
                }
            if target_vars:
                empty_period_targets[teacher] = {
                    "vars": target_vars,
                    "day_config": day_config,
                }

        # 2) يوم/أيام عطلة أسبوعية (قيد ليّن أيضاً - نفس فلسفة القيد أعلاه):
        #    إما أيام محددة بالاسم (واحد أو أكثر)، أو عدد أيام يختاره الحل
        #    تلقائياً. يُحاول الحل دائماً تفريغ كل الأيام المطلوبة بالكامل،
        #    لكن إن تعذّر ذلك بسبب النصاب الفعلي لا يفشل التوليد بالكامل -
        #    تبقى بعض حصص تلك الأيام مجدولة عند الضرورة القصوى فقط، وتُسجَّل
        #    هذه الحالات هنا لملاحظة لاحقة (لكل يوم على حدة).
        day_off = eff["day_off"]
        if day_off["enabled"]:
            if day_off["mode"] == "specific":
                target_days = list(dict.fromkeys(day_off.get("days") or []))
                target_days = [d for d in target_days if d in days]
                by_day_vars = {}
                for day_name in target_days:
                    d_idx = days.index(day_name)
                    day_vars = {}
                    for p in range(periods_per_day):
                        soft_violation_terms_dayoff.append(busy[d_idx, p])
                        soft_violation_terms_by_teacher.setdefault(teacher, []).append(
                            (busy[d_idx, p], "day_off"))
                        day_vars[p] = busy[d_idx, p]
                    by_day_vars[d_idx] = day_vars
                if by_day_vars:
                    day_off_targets[teacher] = {"mode": "specific", "days": by_day_vars}
            else:  # "random" — الحل يختار عدداً محدداً من الأيام لتكون عطلة.
                n_days = max(1, min(int(day_off.get("count", 1) or 1), len(days)))
                off_vars = [model.NewBoolVar(f"dayoff_{teacher}_{d}") for d in range(len(days))]
                model.Add(sum(off_vars) == n_days)
                viol_vars = {}
                for d in range(len(days)):
                    for p in range(periods_per_day):
                        # v == 1 exactly when this slot is both busy AND on
                        # one of the chosen off-days (standard boolean-AND
                        # linearization); minimization pushes v down to that
                        # true value whenever the objective allows it.
                        v = model.NewBoolVar(f"dayoffviol_{teacher}_{d}_{p}")
                        model.Add(v >= busy[d, p] + off_vars[d] - 1)
                        soft_violation_terms_dayoff.append(v)
                        soft_violation_terms_by_teacher.setdefault(teacher, []).append((v, "day_off"))
                        viol_vars[d, p] = v
                day_off_targets[teacher] = {
                    "mode": "random", "off_vars": off_vars, "viol_vars": viol_vars,
                    "count": n_days,
                }

        # 3) حد أقصى لعدد "نوافذ" الفراغ في اليوم الواحد (أكثر من نافذة واحدة
        #    إن أردنا)، حيث تُحسب كل انتقال من "مشغول" إلى "فارغ" كبداية نافذة.
        gap_cfg = eff["max_gap_windows"]
        if gap_cfg["enabled"]:
            max_gaps = max(0, int(gap_cfg["max"] or 0))
            for d in range(len(days)):
                gap_vars = []
                for p in range(1, periods_per_day):
                    g = model.NewBoolVar(f"gap_{teacher}_{d}_{p}")
                    prev_b, cur_b = busy[d, p - 1], busy[d, p]
                    model.AddBoolAnd([prev_b, cur_b.Not()]).OnlyEnforceIf(g)
                    model.AddBoolOr([prev_b.Not(), cur_b]).OnlyEnforceIf(g.Not())
                    gap_vars.append(g)
                if gap_vars:
                    model.Add(sum(gap_vars) <= max_gaps)

        # 4) إلزام أن تبدأ حصص اليوم من أول حصة (لا فراغ في البداية) في أي
        #    يوم لدى الأستاذ فيه حصص أصلاً.
        sfb = eff["start_from_beginning"]
        if sfb["enabled"]:
            for d in range(len(days)):
                has_any = model.NewBoolVar(f"hasany_{teacher}_{d}")
                day_sum = sum(busy[d, p] for p in range(periods_per_day))
                model.Add(day_sum >= 1).OnlyEnforceIf(has_any)
                model.Add(day_sum == 0).OnlyEnforceIf(has_any.Not())
                model.Add(busy[d, 0] == 1).OnlyEnforceIf(has_any)

    penalty_terms = []
    for i, r in enumerate(requirements):
        for d in range(len(days)):
            day_slots = [s for s in range(nslots) if slot_day(s) == d]
            cnt = model.NewIntVar(0, periods_per_day, f"cnt_{i}_{d}")
            model.Add(cnt == sum(x[i, s] for s in day_slots))
            excess = model.NewIntVar(0, periods_per_day, f"excess_{i}_{d}")
            model.Add(excess >= cnt - 1)
            penalty_terms.append(excess)

    # A violation of a soft "تفريغ حصص" (empty_periods) preference is
    # weighted far above any other penalty term here (see penalty_terms
    # above), so the solver only ever accepts one when there is truly no
    # way to avoid it. A violation of a soft "يوم عطلة" (day_off) preference
    # is weighted even higher - strictly higher than the combined weight of
    # EVERY possible empty_periods violation added together (same "weight
    # dominance" technique as MAX_VIOLATION_WEIGHT below) - so whenever a
    # teacher has BOTH settings enabled and the two turn out to conflict
    # (the teacher's real weekly load leaves no room to satisfy both in
    # full), the solver always sacrifices empty_periods slots first and
    # protects the requested day(s) off, never the other way around.
    EMPTY_PERIODS_WEIGHT = 5000
    DAY_OFF_WEIGHT = EMPTY_PERIODS_WEIGHT * (len(soft_violation_terms_emptyperiods) + 1)

    objective_terms = list(penalty_terms)
    for v in soft_violation_terms_emptyperiods:
        objective_terms.append(v * EMPTY_PERIODS_WEIGHT)
    for v in soft_violation_terms_dayoff:
        objective_terms.append(v * DAY_OFF_WEIGHT)

    # Fairness (min-max) on top of the plain weighted total above: minimize
    # the worst single teacher's violation LOAD too (see the docstring
    # above solve_timetable for the "spread vs. concentrate" problem this
    # fixes) - measured in the SAME weighted units as above (not a raw
    # violation count), so the day_off-over-empty_periods priority holds
    # here as well: a teacher with several sacrificed empty_periods slots
    # but a protected day off is correctly treated as better off than a
    # teacher with a single violated day off, even though the former has
    # more individual violated slots. MAX_VIOLATION_WEIGHT is set high
    # enough that improving the worst case by even the smallest unit always
    # outweighs any possible swing in the plain weighted total term, so it
    # is effectively optimized first, with the plain total acting only as a
    # tie-breaker among schedules sharing the same worst case.
    if soft_violation_terms_emptyperiods or soft_violation_terms_dayoff:
        weight_of = {"empty_periods": EMPTY_PERIODS_WEIGHT, "day_off": DAY_OFF_WEIGHT}
        max_possible_weighted_total = (
            len(soft_violation_terms_emptyperiods) * EMPTY_PERIODS_WEIGHT
            + len(soft_violation_terms_dayoff) * DAY_OFF_WEIGHT
        )
        max_violation_var = model.NewIntVar(0, max_possible_weighted_total, "max_teacher_violation")
        for teacher, tagged_terms in soft_violation_terms_by_teacher.items():
            terms_upper_bound = sum(weight_of[tag] for _, tag in tagged_terms)
            teacher_violation_load = model.NewIntVar(
                0, terms_upper_bound, f"violation_load_{teacher}")
            model.Add(teacher_violation_load == sum(
                var * weight_of[tag] for var, tag in tagged_terms))
            model.Add(max_violation_var >= teacher_violation_load)
        MAX_VIOLATION_WEIGHT = max_possible_weighted_total + 1
        objective_terms.append(max_violation_var * MAX_VIOLATION_WEIGHT)

    model.Minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_time_in_seconds
    solver.parameters.num_search_workers = num_workers
    if progress:
        progress("جاري حل الجدولة (قد يستغرق حتى 5 دقائق لإيجاد أفضل ترتيب ممكن)...")
    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"تعذّر إيجاد جدول صالح (الحالة: {status_name}).")

    section_sched = {sid: [None] * nslots for sid in section_ids}
    for i, r in enumerate(requirements):
        sid = (r["track"], r["section"])
        for s in range(nslots):
            if solver.Value(x[i, s]):
                section_sched[sid][s] = {"subject": r["subject"], "teacher": r["teacher"]}

    # A section whose entered subjects don't yet add up to a full week
    # simply keeps its remaining slots as None (printed as blank cells in
    # the PDFs) rather than blocking generation - see incomplete_grades()
    # above for the informational warning about this.
    result = {f"{t}|{s}": section_sched[(t, s)] for (t, s) in section_ids}

    # Check which of the soft "تفريغ حصص" / "يوم عطلة" preferences ended up
    # violated (a requested-empty period, or a period on the requested day
    # off, had to stay busy after all) and turn each into a friendly note -
    # see the comment above soft_violation_terms for why this can happen
    # instead of the generation simply failing. A teacher can end up with
    # notes from both sources at once, so each teacher maps to a LIST.
    constraint_notes = {}
    constraint_fulfillment = {}

    def _add_note(teacher, text):
        constraint_notes.setdefault(teacher, []).append(text)

    def _add_fulfillment(teacher, requested, achieved):
        entry = constraint_fulfillment.setdefault(teacher, {"requested": 0, "achieved": 0})
        entry["requested"] += requested
        entry["achieved"] += achieved

    for teacher, info in empty_period_targets.items():
        by_day = {}
        for (d, p), var in info["vars"].items():
            by_day.setdefault(d, []).append(p)
        day_violations = {}
        for d, ps in by_day.items():
            violated = sum(1 for p in ps if solver.Value(info["vars"][d, p]))
            if violated:
                day_violations[d] = (violated, len(ps))
        total_target = len(info["vars"])
        total_violated = sum(1 for var in info["vars"].values() if solver.Value(var))
        _add_fulfillment(teacher, requested=total_target, achieved=total_target - total_violated)
        if day_violations:
            # كل يوم قد يكون له عدده الخاص المطلوب (نمط "أيام محددة")، لذا
            # يُبنى وصف الطلب لكل يوم على حدة بدل جملة واحدة موحّدة للجميع.
            parts = []
            for d in sorted(day_violations):
                violated, target = day_violations[d]
                left_empty = target - violated
                cfg = info["day_config"][d]
                req_parts = []
                if cfg["start_enabled"]:
                    unit = "حصة" if cfg["start_count"] == 1 else "حصص"
                    req_parts.append(f"{cfg['start_count']} {unit} من البداية")
                if cfg["end_enabled"]:
                    unit = "حصة" if cfg["end_count"] == 1 else "حصص"
                    req_parts.append(f"{cfg['end_count']} {unit} من النهاية")
                req_desc = " و".join(req_parts) if req_parts else "الحصص المطلوبة"
                parts.append(f"{days[d]} (المطلوب {req_desc} — تم تفريغ {left_empty} من {target})")
            _add_note(teacher, (
                "ملاحظة: تعذّر تفريغ الحصص المطلوبة بالكامل «تفريغ حصص في بداية/نهاية "
                "اليوم» في بعض الأيام لهذا الأستاذ، بسبب العدد الفعلي لحصصه الأسبوعية: "
                + "، ".join(parts) + "."
            ))

    for teacher, info in day_off_targets.items():
        if info["mode"] == "specific":
            violated_days = []  # [(day_name, violated_count), ...]
            for d_idx, day_vars in info["days"].items():
                violated = sum(1 for p in range(periods_per_day) if solver.Value(day_vars[p]))
                if violated:
                    violated_days.append((days[d_idx], violated))
            total_target = len(info["days"]) * periods_per_day
            total_violated = sum(
                1 for day_vars in info["days"].values() for p in range(periods_per_day)
                if solver.Value(day_vars[p])
            )
            _add_fulfillment(teacher, requested=total_target, achieved=total_target - total_violated)
            if not violated_days:
                continue
            if len(info["days"]) == 1:
                day_name, violated = violated_days[0]
                _add_note(teacher, (
                    f"ملاحظة: تعذّر تفريغ يوم {day_name} بالكامل كيوم عطلة لهذا الأستاذ "
                    f"كما هو مطلوب، بسبب العدد الفعلي لحصصه الأسبوعية — بقيت {violated} حصة "
                    f"مجدولة في ذلك اليوم من أصل {periods_per_day}."
                ))
            else:
                requested = "، ".join(days[d] for d in info["days"])
                details = "، ".join(f"{name} (بقيت {v} حصة)" for name, v in violated_days)
                _add_note(teacher, (
                    f"ملاحظة: طُلب لهذا الأستاذ {len(info['days'])} أيام عطلة أسبوعية محددة "
                    f"({requested})، لكن تعذّر تفريغ بعضها بالكامل بسبب العدد الفعلي لحصصه "
                    f"الأسبوعية: {details} (من أصل {periods_per_day} حصة/يوم)."
                ))
        else:  # "random"
            chosen_days = [d for d in range(len(days)) if solver.Value(info["off_vars"][d])]
            if not chosen_days:
                continue
            violated_days = []
            for d_idx in chosen_days:
                violated = sum(
                    1 for p in range(periods_per_day) if solver.Value(info["viol_vars"][d_idx, p]))
                if violated:
                    violated_days.append((days[d_idx], violated))
            total_target = len(chosen_days) * periods_per_day
            total_violated = sum(
                1 for d_idx in chosen_days for p in range(periods_per_day)
                if solver.Value(info["viol_vars"][d_idx, p])
            )
            _add_fulfillment(teacher, requested=total_target, achieved=total_target - total_violated)
            if not violated_days:
                continue
            if len(chosen_days) == 1:
                day_name, violated = violated_days[0]
                _add_note(teacher, (
                    f"ملاحظة: اختار الجدول يوم {day_name} ليكون يوم عطلة هذا الأستاذ، لكن "
                    f"تعذّر تفريغه بالكامل بسبب العدد الفعلي لحصصه الأسبوعية — بقيت {violated} "
                    f"حصة مجدولة فيه من أصل {periods_per_day}."
                ))
            else:
                chosen_names = "، ".join(days[d] for d in chosen_days)
                details = "، ".join(f"{name} (بقيت {v} حصة)" for name, v in violated_days)
                _add_note(teacher, (
                    f"ملاحظة: اختار الجدول {len(chosen_days)} أيام لتكون أيام عطلة هذا الأستاذ "
                    f"({chosen_names})، لكن تعذّر تفريغ بعضها بالكامل بسبب العدد الفعلي لحصصه "
                    f"الأسبوعية: {details} (من أصل {periods_per_day} حصة/يوم)."
                ))

    if progress:
        progress(f"تم إيجاد جدول صالح ({status_name}).")
        for teacher, notes in constraint_notes.items():
            for note in notes:
                progress(f"{teacher}: {note}")
    return status_name, result, constraint_notes, constraint_fulfillment


def teacher_roster(data):
    """
    Build the per-(subject,teacher) roster rows (grades/sections/total),
    plus the list of real teachers who cover more than one subject.
    """
    cols = data["meta"]["grade_order"]
    grade_labels = data["meta"]["grade_labels"]
    order_idx = {c: i for i, c in enumerate(cols)}

    def compress_ranges(nums):
        nums = sorted(nums)
        ranges = []
        start = prev = nums[0]
        for n in nums[1:]:
            if n == prev + 1:
                prev = n
            else:
                ranges.append((start, prev))
                start = prev = n
        ranges.append((start, prev))
        return ",".join(f"{a}-{b}" if a != b else f"{a}" for a, b in ranges)

    slots = build_all_slots(data)
    rows = []
    for slot in slots:
        by_track = {}
        for a in slot["atoms"]:
            by_track.setdefault(a["track"], []).append(a["section"])
        tracks_sorted = sorted(by_track.keys(), key=lambda c: order_idx[c])
        grades_str = "، ".join(grade_labels[tr] for tr in tracks_sorted)
        sections_str = " | ".join(
            f"{grade_labels[tr]}: شعبة {compress_ranges(by_track[tr])}" for tr in tracks_sorted
        )
        rows.append({
            "teacher": slot["name"], "subject": slot["subject"],
            "grades": grades_str, "sections": sections_str,
            "total": int(round(slot["total"])),
        })

    subject_order = []
    seen = set()
    for slot in slots:
        if slot["subject"] not in seen:
            subject_order.append(slot["subject"])
            seen.add(slot["subject"])
    subj_rank = {s: i for i, s in enumerate(subject_order)}
    rows.sort(key=lambda r: (subj_rank[r["subject"]], r["teacher"]))

    combined = {}
    for r in rows:
        combined.setdefault(r["teacher"], {"subjects": [], "total": 0})
        combined[r["teacher"]]["subjects"].append(r["subject"])
        combined[r["teacher"]]["total"] += r["total"]
    multi = {k: v for k, v in combined.items() if len(v["subjects"]) > 1}

    return rows, multi, len(combined)


# ------------------------------------------------------ constraints report
#
# A textual report (see pdf_gen._build_constraints_report_flowables) of
# exactly which scheduling constraints are active for which teacher, in
# full detail - independent of section_sched, so it can be built even
# before the solver has run. This is deliberately separate from
# constraint_notes (solve_timetable's best-effort VIOLATION log): this
# report describes what was ASKED FOR, not whether the solver managed to
# honor it.

CONSTRAINT_TITLES = {
    "empty_periods": "تفريغ حصص في بداية/نهاية اليوم",
    "day_off": "يوم عطلة أسبوعي",
    "max_gap_windows": "الحد الأقصى لعدد نوافذ الفراغ في اليوم",
    "start_from_beginning": "إلزام البدء من أول حصة في اليوم",
}


def _describe_constraint_detail(key, group):
    """
    One human-readable Arabic sentence describing an ENABLED constraint
    group's exact settings (day names, counts, position) - not just which
    option is turned on.
    """
    if key == "empty_periods":
        if group.get("days_mode") == "specific":
            chosen = list(dict.fromkeys(group.get("days") or []))
            if not chosen:
                return "تفريغ حصص - أيام محددة: لم يُختَر أي يوم بعد"
            per_day = group.get("per_day") or {}
            lines = []
            for day_name in chosen:
                cfg = per_day.get(day_name) or {}
                start = cfg.get("start") or group.get("start") or {}
                end = cfg.get("end") or group.get("end") or {}
                day_parts = []
                if start.get("enabled"):
                    count = int(start.get("count", 1) or 0)
                    unit = "حصة" if count == 1 else "حصص"
                    day_parts.append(f"{count} {unit} من البداية")
                if end.get("enabled"):
                    count = int(end.get("count", 1) or 0)
                    unit = "حصة" if count == 1 else "حصص"
                    day_parts.append(f"{count} {unit} من النهاية")
                lines.append(f"{day_name}: " + (" و".join(day_parts) if day_parts else "بلا تفريغ"))
            return "تفريغ حصص - أيام محددة (لكل يوم عدده الخاص): " + "؛ ".join(lines)
        start = group.get("start") or {}
        end = group.get("end") or {}
        parts = []
        if start.get("enabled"):
            count = int(start.get("count", 1) or 0)
            unit = "حصة" if count == 1 else "حصص"
            parts.append(f"{count} {unit} في بداية اليوم")
        if end.get("enabled"):
            count = int(end.get("count", 1) or 0)
            unit = "حصة" if count == 1 else "حصص"
            parts.append(f"{count} {unit} في نهاية اليوم")
        detail = "تفريغ " + (" و".join(parts) if parts else "(لم يُفعَّل شيء)")
        detail += " - كل أيام الأسبوع"
        return detail
    if key == "day_off":
        if group.get("mode") == "specific":
            days = list(dict.fromkeys(group.get("days") or []))
            if not days:
                return "يوم عطلة محدد: لم يُختَر أي يوم بعد"
            return "يوم عطلة محدد: " + "، ".join(days)
        count = int(group.get("count", 1) or 0)
        unit = "يوم" if count == 1 else "أيام"
        return f"يوم عطلة عشوائي: {count} {unit} يختارها الحل تلقائياً"
    if key == "max_gap_windows":
        m = int(group.get("max", 1) or 0)
        unit = "نافذة" if m == 1 else "نوافذ"
        return f"حد أقصى {m} {unit} فراغ في اليوم الواحد"
    if key == "start_from_beginning":
        return "إلزام البدء من أول حصة في اليوم (بلا فراغ في البداية)"
    return ""


def describe_teacher_constraints(data, teacher_name):
    """
    Every ENABLED constraint that actually applies to this teacher, after
    merging global defaults with any per-teacher override (see
    effective_constraints) - each as {"key", "title", "detail", "source"}
    where source is "خاص" when this teacher has their OWN override for
    that specific key, or "عام" when it is inherited unchanged from the
    general defaults.
    """
    eff = effective_constraints(data, teacher_name)
    per_teacher_overrides = data.get("scheduling_constraints", {}).get(
        "per_teacher", {}).get(teacher_name, {})
    items = []
    for key, title in CONSTRAINT_TITLES.items():
        group = eff[key]
        if not group.get("enabled"):
            continue
        items.append({
            "key": key,
            "title": title,
            "detail": _describe_constraint_detail(key, group),
            "source": "خاص" if key in per_teacher_overrides else "عام",
        })
    return items


def teacher_constraints_report(data):
    """
    One entry per teacher who has at least one enabled scheduling
    constraint (via the global defaults and/or their own override), each
    with the full list of their active constraints in detail (see
    describe_teacher_constraints) plus which subjects they teach - for the
    "تقرير الشروط الخاصة بجدولة الأساتذة" PDF (see pdf_gen.py). Teachers
    with nothing enabled at all are left out entirely, since there is
    nothing to report for them.
    """
    teacher_subjects = {}
    for subject in data["subjects"]:
        for name in subject["names"]:
            teacher_subjects.setdefault(name, []).append(subject["name"])

    rows = []
    for name in get_all_teacher_names(data):
        items = describe_teacher_constraints(data, name)
        if not items:
            continue
        subjects = list(dict.fromkeys(teacher_subjects.get(name, [])))
        rows.append({"teacher": name, "subjects": subjects, "items": items})
    return rows


FULFILLMENT_CATEGORIES = ("كامل", "جزئي", "معدوم")


def teacher_fulfillment_report(data, constraint_fulfillment):
    """
    Combine each teacher's active scheduling constraints (see
    teacher_constraints_report) with how much of them the SOLVED schedule
    actually managed to honor (constraint_fulfillment, returned by
    solve_timetable) into one of three buckets per teacher:
      - "كامل"   (100% - every requested empty/day-off slot was honored;
                  this also covers a teacher whose only active constraints
                  are the hard ones, max_gap_windows/start_from_beginning,
                  which are never tracked in constraint_fulfillment at all
                  since they either hold completely or the solve fails
                  outright - no entry there is treated as 100%).
      - "جزئي"   (something between 0% and 100% was honored).
      - "معدوم"  (0% - every requested slot stayed busy / every requested
                  day off remained fully scheduled).
    Each row also carries the exact percentage, for a precise per-teacher
    figure alongside the three-bucket breakdown. Used for the "تقرير نسبة
    تحقق رغبات الأساتذة" PDF (see pdf_gen.py) - this is deliberately
    separate from teacher_constraints_report (which only says what was
    ASKED FOR): this says how much of it the actual solved schedule
    delivered.
    """
    rows = teacher_constraints_report(data)
    out = []
    for r in rows:
        f = (constraint_fulfillment or {}).get(r["teacher"])
        if not f or f["requested"] <= 0:
            pct = 100.0
        else:
            pct = 100.0 * f["achieved"] / f["requested"]
        if pct >= 99.95:
            category = "كامل"
        elif pct <= 0.05:
            category = "معدوم"
        else:
            category = "جزئي"
        out.append({
            "teacher": r["teacher"], "subjects": r["subjects"], "items": r["items"],
            "percent": round(pct, 1), "category": category,
        })
    return out


def fulfillment_category_counts(fulfillment_rows):
    """
    {"كامل": n, "جزئي": n, "معدوم": n} counts over teacher_fulfillment_report's
    rows, always including all three keys (zero for any bucket with no
    teachers) so the chart/legend in pdf_gen.py never has to guess which
    categories exist.
    """
    counts = {cat: 0 for cat in FULFILLMENT_CATEGORIES}
    for r in fulfillment_rows:
        counts[r["category"]] += 1
    return counts


def _constraint_difficulty(key, group):
    """
    How demanding ONE active constraint group's own settings are, as a
    single number: a base 1.0 point just for being enabled (this is the
    part that drives a simple "how many constraint types" count), plus an
    extra amount reflecting how demanding the specific numbers/choices
    within it are - so two teachers who both merely have "day_off enabled"
    don't score the same if one asked for 1 day off and the other asked
    for 3, or one asked for a strict "no more than 0 gap windows" while the
    other allows 3. Used by teacher_constraint_complexity_report below.
    """
    if key == "day_off":
        if group.get("mode") == "specific":
            n = len(list(dict.fromkeys(group.get("days") or [])))
        else:
            n = int(group.get("count", 1) or 1)
        return 1.0 + max(0, n - 1) * 1.0
    if key == "empty_periods":
        chosen_days = list(dict.fromkeys(group.get("days") or []))
        if group.get("days_mode") == "specific" and chosen_days:
            per_day = group.get("per_day") or {}
            total_count = 0
            both_count = 0
            for day_name in chosen_days:
                cfg = per_day.get(day_name) or {}
                start = cfg.get("start") or group.get("start") or {}
                end = cfg.get("end") or group.get("end") or {}
                if start.get("enabled"):
                    total_count += int(start.get("count", 1) or 1)
                if end.get("enabled"):
                    total_count += int(end.get("count", 1) or 1)
                if start.get("enabled") and end.get("enabled"):
                    both_count += 1
            extra = both_count * 1.0 + max(0, len(chosen_days) - 1) * 0.5
            return 1.0 + max(0, total_count - 1) * 0.5 + extra
        start = group.get("start") or {}
        end = group.get("end") or {}
        total_count = 0
        if start.get("enabled"):
            total_count += int(start.get("count", 1) or 1)
        if end.get("enabled"):
            total_count += int(end.get("count", 1) or 1)
        extra = 1.0 if (start.get("enabled") and end.get("enabled")) else 0.0
        return 1.0 + max(0, total_count - 1) * 0.5 + extra
    if key == "max_gap_windows":
        m = int(group.get("max", 1) or 0)
        return 1.0 + max(0, 2 - m) * 0.5
    if key == "start_from_beginning":
        return 1.0
    return 1.0


def teacher_constraint_complexity_report(data):
    """
    Rank every teacher who has at least one active scheduling constraint
    by how numerous AND how demanding their combined constraints are,
    MOST complex first - for the "ترتيب الأساتذة حسب كثرة وتعقيد الشروط"
    PDF (see pdf_gen.py). Two figures per teacher:
      - "count": how many of the 4 constraint TYPES are active (1-4) -
        the "كثرة" (multiplicity) half of the ask.
      - "score": a weighted difficulty total (see _constraint_difficulty)
        - the "تعقيد" (complexity) half: two teachers with the same
        COUNT don't necessarily score the same (a single 3-day-off
        request outranks a single easy 1-day-off request).
    Sorted by score first, then count, then name, so the ranking is
    driven primarily by how demanding the combination actually is rather
    than merely how many boxes are ticked.
    """
    rows = teacher_constraints_report(data)
    out = []
    for r in rows:
        eff = effective_constraints(data, r["teacher"])
        score = sum(_constraint_difficulty(it["key"], eff[it["key"]]) for it in r["items"])
        out.append({
            "teacher": r["teacher"], "subjects": r["subjects"], "items": r["items"],
            "count": len(r["items"]), "score": round(score, 2),
        })
    out.sort(key=lambda r: (-r["score"], -r["count"], r["teacher"]))
    return out
